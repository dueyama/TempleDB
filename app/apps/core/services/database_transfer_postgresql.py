from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import psycopg
from django.apps import apps
from django.db import connection as default_database_connection
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from psycopg import sql

from apps.core.models import DatabaseBackupRun, DatabaseBackupVerificationRun

from . import backup, backup_execution, backup_restore_contract
from . import database_transfer as shared

DatabaseTransferError = shared.DatabaseTransferError

POSTGRESQL_TRANSFER_FORMAT_VERSION = 1
POSTGRESQL_COMPLETION_MARKER_VERSION = 1
TARGET_DATABASE_PATTERN = re.compile(r"templedb_clone_[a-z0-9_]{1,40}")
TARGET_ENV_PREFIX = "TEMPLEDB_TRANSFER_TARGET_"
TARGET_CLUSTER_LOCK_KEY_1 = 1_414_216_244
TARGET_CLUSTER_LOCK_KEY_2 = 1_415_263_151
TRANSFER_DATABASE_PATTERN = re.compile(
    r"templedb_transfer_\d{8}_\d{6}_\d+_[0-9a-f]{16}"
)
DATABASE_COMMENT_PREFIX = "templedb-transfer:"
DATABASE_ENVIRONMENT_KEYS = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_NAME",
        "DATABASE_PASSWORD",
        "DATABASE_PORT",
        "DATABASE_USER",
    }
)


@dataclass(frozen=True)
class PostgreSQLCloneTarget:
    admin: backup.PostgresAdminConfig
    runtime: backup.PostgresConnectionConfig


@dataclass(frozen=True)
class PostgreSQLTransferResult:
    database_name: str
    database_oid: int
    manifest_path: Path
    completion_marker_path: Path
    transferred_object_count: int
    source_backup_run_id: int
    source_verification_run_id: int
    connections_allowed: bool


@dataclass(frozen=True)
class FrozenPostgreSQLCandidateResult:
    database_name: str
    database_oid: int
    connections_allowed: bool
    ownership_token_sha256: str
    validation_summary: dict[str, object]


@dataclass(frozen=True)
class PostgreSQLCandidateState:
    database_name: str
    database_oid: int
    owner: str
    connections_allowed: bool
    ownership_token_sha256: str
    active_connection_count: int


@dataclass(frozen=True)
class _PostgreSQLRoleState:
    can_login: bool
    superuser: bool
    create_database: bool
    create_role: bool
    replication: bool
    bypass_row_level_security: bool


@dataclass(frozen=True)
class _OwnedDatabase:
    name: str
    oid: int
    token: str


@dataclass(frozen=True)
class _DatabaseState:
    name: str
    oid: int
    owner: str
    encoding: str
    connections_allowed: bool
    public_connect_allowed: bool
    public_temporary_allowed: bool
    comment: str


def create_frozen_postgresql_candidate_from_dump(
    *,
    backup_file_path: str | Path,
    expected_backup_size: int,
    expected_backup_sha256: str,
    backup_run_id: int,
    target_database_name: str,
    expected_target_postgresql_major: int,
    expected_restore_summary: dict[str, object],
    expected_installation_id: str,
) -> FrozenPostgreSQLCandidateResult:
    """Restore a verified pack dump into a new, frozen PostgreSQL candidate."""

    target_name = validate_postgresql_clone_database_name(target_database_name)
    expected_summary = _validated_pack_restore_summary(
        expected_restore_summary,
        expected_backup_run_id=backup_run_id,
        expected_installation_id=expected_installation_id,
    )
    source_postgresql_major = _postgresql_major_from_restore_summary(
        expected_summary,
        label="運用パック",
    )
    target_postgresql_major = _validated_target_postgresql_major(
        expected_target_postgresql_major,
        source_postgresql_major=source_postgresql_major,
    )
    source_path = Path(backup_file_path).expanduser()
    source_snapshot = shared._capture_private_file_snapshot(source_path)
    normalized_expected_sha256 = str(expected_backup_sha256 or "").strip().lower()
    if (
        isinstance(expected_backup_size, bool)
        or not isinstance(expected_backup_size, int)
        or expected_backup_size <= 0
        or not re.fullmatch(r"[0-9a-f]{64}", normalized_expected_sha256)
        or source_snapshot.size != expected_backup_size
        or source_snapshot.sha256 != normalized_expected_sha256
    ):
        raise DatabaseTransferError(
            "運用パックのPostgreSQL backupが検証済みmetadataと一致しません。"
        )
    if (
        isinstance(backup_run_id, bool)
        or not isinstance(backup_run_id, int)
        or backup_run_id <= 0
    ):
        raise DatabaseTransferError("運用パックのbackup run IDが不正です。")

    target = resolve_postgresql_clone_target()
    temporary_database: _OwnedDatabase | None = None
    operation_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    completed_result: FrozenPostgreSQLCandidateResult | None = None

    with _target_cluster_guard(target.admin) as admin_connection:
        try:
            cluster_information = _read_target_cluster_information(admin_connection)
            actual_target_postgresql_major = (
                int(cluster_information["server_version_number"]) // 10_000
            )
            if actual_target_postgresql_major != target_postgresql_major:
                raise DatabaseTransferError(
                    "target PostgreSQL majorが確認値と一致しません。"
                )
            _assert_target_cluster_preconditions(
                admin_connection,
                target=target,
                target_database_name=target_name,
            )
            temporary_database = _create_owned_database(
                admin_connection,
                target=target,
                backup_run_id=backup_run_id,
            )
            _harden_postgresql_schema(target.runtime, temporary_database.name)
            _restore_postgresql_database(
                target.runtime,
                temporary_database.name,
                source_path,
                single_transaction=True,
            )
            shared._assert_private_file_matches_snapshot(
                source_path,
                source_snapshot,
            )
            validation_summary = _validate_restored_postgresql_candidate(
                target=target,
                database=temporary_database,
                expected_summary=expected_summary,
                expected_installation_id=expected_installation_id,
                expected_target_postgresql_major=target_postgresql_major,
            )
            shared._assert_private_file_matches_snapshot(
                source_path,
                source_snapshot,
            )
            final_database = _freeze_and_rename_database(
                admin_connection,
                database=temporary_database,
                target_database_name=target_name,
                expected_owner=target.runtime.database_user,
            )
            # A database that has reached its final name must never enter the
            # automatic cleanup path.  Final-name cleanup is always explicit.
            temporary_database = None
            _assert_frozen_database(
                admin_connection,
                database=final_database,
                expected_owner=target.runtime.database_user,
            )
            completed_result = FrozenPostgreSQLCandidateResult(
                database_name=final_database.name,
                database_oid=final_database.oid,
                connections_allowed=False,
                ownership_token_sha256=hashlib.sha256(
                    final_database.token.encode("utf-8")
                ).hexdigest(),
                validation_summary=validation_summary,
            )
        except BaseException as exc:
            operation_error = exc
        finally:
            if temporary_database is not None:
                try:
                    _drop_owned_database(admin_connection, temporary_database)
                except BaseException as exc:
                    cleanup_error = exc

    if cleanup_error is not None:
        message = (
            "所有権を確認できた一時PostgreSQL candidateを削除できなかったため、"
            "処理を完了していません。"
        )
        if operation_error is not None:
            message += " candidate作成処理自体にも失敗があります。"
        raise DatabaseTransferError(message) from cleanup_error
    if operation_error is not None:
        if isinstance(operation_error, DatabaseTransferError):
            raise operation_error
        if isinstance(operation_error, Exception):
            raise DatabaseTransferError(
                "運用パックからPostgreSQL candidateを作成できませんでした。"
            ) from operation_error
        raise operation_error
    if completed_result is None:
        raise DatabaseTransferError(
            "PostgreSQL candidateの完了結果を確認できませんでした。"
        )
    return completed_result


def create_product_postgresql_clone_from_sqlite_backup(
    *,
    backup_run: DatabaseBackupRun,
    target_database_name: str,
    manifest_path: str | Path,
) -> PostgreSQLTransferResult:
    """Create a frozen PostgreSQL clone without changing the live SQLite runtime."""

    if backup.current_database_engine() != "sqlite" or not backup.is_product_sqlite_configured():
        raise DatabaseTransferError(
            "SQLite製品DBから実行した場合だけPostgreSQLクローンを作成できます。"
        )
    if backup_run.database_engine != "sqlite":
        raise DatabaseTransferError("SQLiteバックアップを指定してください。")
    if backup_run.status != "succeeded":
        raise DatabaseTransferError(
            "成功したSQLiteバックアップだけをPostgreSQLへ移送できます。"
        )

    verification_run = shared._require_latest_successful_verification(backup_run)
    target_name = validate_postgresql_clone_database_name(target_database_name)
    final_manifest_path = validate_postgresql_clone_manifest_path(manifest_path)
    target = resolve_postgresql_clone_target()
    shared.assert_database_transfer_model_classification()
    live_identity = shared._read_live_runtime_identity()

    lock_token = None
    try:
        lock_token = backup_execution._acquire_database_maintenance_lock(
            operation_kind="database_transfer",
            record_id=backup_run.id,
        )
        backup_run.refresh_from_db()
        if backup_run.database_engine != "sqlite" or backup_run.status != "succeeded":
            raise DatabaseTransferError("lock取得後にSQLiteバックアップ状態が変更されました。")
        verification_run = shared._require_latest_successful_verification(backup_run)
        backup_file_path = backup.validate_backup_artifact(backup_run)
        source_snapshot = shared._capture_private_file_snapshot(backup_file_path)
        _assert_source_backup_snapshot_matches_run(backup_run, source_snapshot)
        with _target_cluster_guard(target.admin) as admin_connection:
            return _create_postgresql_clone_under_locks(
                backup_run=backup_run,
                verification_run=verification_run,
                backup_file_path=backup_file_path,
                source_snapshot=source_snapshot,
                target=target,
                target_database_name=target_name,
                manifest_path=final_manifest_path,
                live_identity=live_identity,
                admin_connection=admin_connection,
            )
    finally:
        backup_execution._release_backup_lock(lock_token)


def validate_postgresql_clone_database_name(raw_name: str) -> str:
    database_name = (raw_name or "").strip()
    if len(database_name) > 63 or not TARGET_DATABASE_PATTERN.fullmatch(database_name):
        raise DatabaseTransferError(
            "PostgreSQL clone名は templedb_clone_ で始まる小文字英数字・underscoreに限定されます。"
        )
    return database_name


def validate_postgresql_clone_manifest_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise DatabaseTransferError("PostgreSQL移送manifestは絶対pathで指定してください。")
    if path.suffix.lower() != ".json":
        raise DatabaseTransferError("PostgreSQL移送manifestは .json で終わる必要があります。")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise DatabaseTransferError("PostgreSQL移送manifestの親directoryを利用できません。")
    resolved_parent = parent.resolve(strict=True)
    if parent != resolved_parent:
        raise DatabaseTransferError("manifestの親directoryにsymlinkは使用できません。")
    if stat.S_IMODE(resolved_parent.stat().st_mode) != 0o700:
        raise DatabaseTransferError(
            "PostgreSQL移送manifestの親directoryは所有者専用0700にしてください。"
        )
    manifest_path = resolved_parent / path.name
    completion_marker_path = _postgresql_completion_marker_path(manifest_path)
    if any(
        candidate.exists() or candidate.is_symlink()
        for candidate in (manifest_path, completion_marker_path)
    ):
        raise DatabaseTransferError("同名のPostgreSQL移送manifestまたは完了印が既にあります。")
    orphan_patterns = (
        f".{manifest_path.name}.*.part",
        f".{completion_marker_path.name}.*.part",
    )
    if any(next(resolved_parent.glob(pattern), None) for pattern in orphan_patterns):
        raise DatabaseTransferError(
            "同じmanifest名に前回未完了の一時fileがあります。自動削除せず停止します。"
        )
    if not os.access(resolved_parent, os.W_OK):
        raise DatabaseTransferError("PostgreSQL移送manifestの保存先へ書き込めません。")
    return manifest_path


def _postgresql_completion_marker_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(f"{manifest_path.name}.complete")


def resolve_postgresql_clone_target() -> PostgreSQLCloneTarget:
    _reject_ambient_libpq_environment()
    host = _required_target_env("HOST")
    if not (
        host in {"127.0.0.1", "localhost", "::1"}
        or (host.startswith("/") and Path(host).is_absolute())
    ):
        raise DatabaseTransferError(
            "逆移送v1のtarget PostgreSQL hostはloopbackまたは明示Unix socketに限定されます。"
        )
    port = _required_target_env("PORT")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise DatabaseTransferError("target PostgreSQL portが不正です。")
    admin_database = _validated_postgresql_identifier(
        _required_target_env("ADMIN_DATABASE"),
        label="admin database",
    )
    admin_user = _validated_postgresql_identifier(
        _required_target_env("ADMIN_USER"),
        label="admin user",
    )
    owner_user = _validated_postgresql_identifier(
        _required_target_env("OWNER_USER"),
        label="owner user",
    )
    admin_password = os.environ.get(f"{TARGET_ENV_PREFIX}ADMIN_PASSWORD", "")
    owner_password = os.environ.get(f"{TARGET_ENV_PREFIX}OWNER_PASSWORD", "")
    _reject_unsafe_env_value(admin_password, label="admin password")
    _reject_unsafe_env_value(owner_password, label="owner password")
    return PostgreSQLCloneTarget(
        admin=backup.PostgresAdminConfig(
            database_name=admin_database,
            database_user=admin_user,
            database_password=admin_password,
            database_host=host,
            database_port=port,
        ),
        runtime=backup.PostgresConnectionConfig(
            database_name="",
            database_user=owner_user,
            database_password=owner_password,
            database_host=host,
            database_port=port,
        ),
    )


def inspect_postgresql_candidate(
    *,
    database_name: str,
    expected_database_oid: int,
    expected_ownership_token_sha256: str,
    expected_connections_allowed: bool,
) -> PostgreSQLCandidateState:
    """Read and verify one explicitly identified tenant-pack candidate DB."""

    target_name = validate_postgresql_clone_database_name(database_name)
    expected_oid = _validated_candidate_oid(expected_database_oid)
    expected_token_sha256 = _validated_candidate_token_sha256(
        expected_ownership_token_sha256
    )
    if not isinstance(expected_connections_allowed, bool):
        raise DatabaseTransferError(
            "candidate DBの接続許可確認値はboolで指定してください。"
        )
    target = resolve_postgresql_clone_target()
    with _target_cluster_guard(target.admin) as admin_connection:
        return _verified_postgresql_candidate_state(
            admin_connection,
            target=target,
            database_name=target_name,
            expected_database_oid=expected_oid,
            expected_ownership_token_sha256=expected_token_sha256,
            expected_connections_allowed=expected_connections_allowed,
        )


def inspect_connected_postgresql_candidate(
    *,
    database_name: str,
    expected_database_oid: int,
    expected_ownership_token_sha256: str,
    database_connection=None,
) -> PostgreSQLCandidateState:
    """Verify an activated candidate through its unprivileged runtime connection."""

    target_name = validate_postgresql_clone_database_name(database_name)
    expected_oid = _validated_candidate_oid(expected_database_oid)
    expected_token_sha256 = _validated_candidate_token_sha256(
        expected_ownership_token_sha256
    )
    runtime_connection = database_connection or default_database_connection
    if getattr(runtime_connection, "vendor", None) != "postgresql":
        raise DatabaseTransferError(
            "activated candidateの起動前確認にはPostgreSQL接続が必要です。"
        )
    try:
        with runtime_connection.cursor() as cursor:
            cursor.execute(
                "SELECT d.datname, d.oid, pg_get_userbyid(d.datdba), "
                "pg_encoding_to_char(d.encoding), d.datallowconn, "
                "EXISTS ("
                "SELECT 1 FROM aclexplode("
                "COALESCE(d.datacl, acldefault('d', d.datdba))) a "
                "WHERE a.grantee = 0 AND a.privilege_type = 'CONNECT'"
                "), "
                "EXISTS ("
                "SELECT 1 FROM aclexplode("
                "COALESCE(d.datacl, acldefault('d', d.datdba))) a "
                "WHERE a.grantee = 0 AND a.privilege_type = 'TEMPORARY'"
                "), "
                "COALESCE(shobj_description(d.oid, 'pg_database'), ''), "
                "current_user, "
                "(SELECT COUNT(*) FROM pg_stat_activity "
                "WHERE datname = current_database()) "
                "FROM pg_database d WHERE d.datname = current_database()"
            )
            row = cursor.fetchone()
    except Exception as exc:
        raise DatabaseTransferError(
            "activated candidate DBをruntime接続で確認できません。"
        ) from exc
    if row is None or len(row) != 10:
        raise DatabaseTransferError(
            "activated candidate DBをruntime接続で確認できません。"
        )
    state = _DatabaseState(
        name=str(row[0]),
        oid=int(row[1]),
        owner=str(row[2]),
        encoding=str(row[3]),
        connections_allowed=bool(row[4]),
        public_connect_allowed=bool(row[5]),
        public_temporary_allowed=bool(row[6]),
        comment=str(row[7]),
    )
    current_user = str(row[8])
    token_sha256 = hashlib.sha256(state.comment.encode("utf-8")).hexdigest()
    if (
        state.name != target_name
        or state.oid != expected_oid
        or state.owner != current_user
        or state.encoding != "UTF8"
        or not state.connections_allowed
        or state.public_connect_allowed
        or state.public_temporary_allowed
        or token_sha256 != expected_token_sha256
    ):
        raise DatabaseTransferError(
            "activated candidate DBの名前、OID、owner、tokenまたは安全状態が一致しません。"
        )
    _assert_candidate_database_acl_is_owner_only(
        runtime_connection,
        database_name=state.name,
    )
    _assert_candidate_role_is_least_privileged(
        runtime_connection,
        role_name=current_user,
        database_name=state.name,
    )
    return PostgreSQLCandidateState(
        database_name=state.name,
        database_oid=state.oid,
        owner=state.owner,
        connections_allowed=state.connections_allowed,
        ownership_token_sha256=token_sha256,
        active_connection_count=int(row[9]),
    )


def set_postgresql_candidate_connections_allowed(
    *,
    database_name: str,
    expected_database_oid: int,
    expected_ownership_token_sha256: str,
    current_connections_allowed: bool,
    new_connections_allowed: bool,
) -> PostgreSQLCandidateState:
    """Change ALLOW_CONNECTIONS only for the exact owned candidate DB."""

    if (
        not isinstance(current_connections_allowed, bool)
        or not isinstance(new_connections_allowed, bool)
        or current_connections_allowed == new_connections_allowed
    ):
        raise DatabaseTransferError(
            "candidate DBの接続許可は異なるbool値を明示してください。"
        )
    target_name = validate_postgresql_clone_database_name(database_name)
    expected_oid = _validated_candidate_oid(expected_database_oid)
    expected_token_sha256 = _validated_candidate_token_sha256(
        expected_ownership_token_sha256
    )
    target = resolve_postgresql_clone_target()
    with _target_cluster_guard(target.admin) as admin_connection:
        before = _verified_postgresql_candidate_state(
            admin_connection,
            target=target,
            database_name=target_name,
            expected_database_oid=expected_oid,
            expected_ownership_token_sha256=expected_token_sha256,
            expected_connections_allowed=current_connections_allowed,
        )
        if before.active_connection_count:
            raise DatabaseTransferError(
                "candidate DBに接続が残っているため接続許可を変更しません。"
            )
        with admin_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS {}").format(
                    sql.Identifier(target_name),
                    sql.SQL("true" if new_connections_allowed else "false"),
                )
            )
        return _verified_postgresql_candidate_state(
            admin_connection,
            target=target,
            database_name=target_name,
            expected_database_oid=expected_oid,
            expected_ownership_token_sha256=expected_token_sha256,
            expected_connections_allowed=new_connections_allowed,
        )


def _validated_candidate_oid(raw_oid: object) -> int:
    if isinstance(raw_oid, bool) or not isinstance(raw_oid, int) or raw_oid <= 0:
        raise DatabaseTransferError("candidate DBのOIDが不正です。")
    return raw_oid


def _validated_candidate_token_sha256(raw_sha256: object) -> str:
    value = str(raw_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise DatabaseTransferError("candidate DBの所有token SHA256が不正です。")
    return value


def _verified_postgresql_candidate_state(
    admin_connection,
    *,
    target: PostgreSQLCloneTarget,
    database_name: str,
    expected_database_oid: int,
    expected_ownership_token_sha256: str,
    expected_connections_allowed: bool,
) -> PostgreSQLCandidateState:
    state = _read_database_state(admin_connection, database_name)
    if state is None:
        raise DatabaseTransferError("candidate PostgreSQL DBが存在しません。")
    token_sha256 = hashlib.sha256(state.comment.encode("utf-8")).hexdigest()
    if (
        state.oid != expected_database_oid
        or state.owner != target.runtime.database_user
        or state.encoding != "UTF8"
        or state.public_connect_allowed
        or state.public_temporary_allowed
        or token_sha256 != expected_ownership_token_sha256
        or state.connections_allowed is not expected_connections_allowed
    ):
        raise DatabaseTransferError(
            "candidate PostgreSQL DBのOID、owner、tokenまたは安全状態が一致しません。"
        )
    _assert_candidate_database_acl_is_owner_only(
        admin_connection,
        database_name=state.name,
    )
    _assert_candidate_role_is_least_privileged(
        admin_connection,
        role_name=target.runtime.database_user,
        database_name=state.name,
    )
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = %s",
            (database_name,),
        )
        active_connection_count = int(cursor.fetchone()[0])
    if not expected_connections_allowed and active_connection_count:
        raise DatabaseTransferError("凍結candidate DBに予期しない接続が残っています。")
    return PostgreSQLCandidateState(
        database_name=state.name,
        database_oid=state.oid,
        owner=state.owner,
        connections_allowed=state.connections_allowed,
        ownership_token_sha256=token_sha256,
        active_connection_count=active_connection_count,
    )


def _assert_candidate_role_is_least_privileged(
    connection,
    *,
    role_name: str,
    database_name: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (role_name,),
        )
        row = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) FROM pg_auth_members m "
            "JOIN pg_roles candidate ON "
            "(m.member = candidate.oid OR m.roleid = candidate.oid) "
            "WHERE candidate.rolname = %s",
            (role_name,),
        )
        membership_row = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) AS other_owned_databases FROM pg_database d "
            "JOIN pg_roles owner_role ON owner_role.oid = d.datdba "
            "WHERE owner_role.rolname = %s AND d.datname <> %s",
            (role_name, database_name),
        )
        other_database_ownership_row = cursor.fetchone()
    if row is None or len(row) != 6:
        raise DatabaseTransferError(
            "candidate PostgreSQL roleの属性を確認できません。"
        )
    state = _PostgreSQLRoleState(
        can_login=bool(row[0]),
        superuser=bool(row[1]),
        create_database=bool(row[2]),
        create_role=bool(row[3]),
        replication=bool(row[4]),
        bypass_row_level_security=bool(row[5]),
    )
    if state != _PostgreSQLRoleState(
        can_login=True,
        superuser=False,
        create_database=False,
        create_role=False,
        replication=False,
        bypass_row_level_security=False,
    ):
        raise DatabaseTransferError(
            "candidate PostgreSQL roleはlogin専用のleast-privilege属性である必要があります。"
        )
    if (
        membership_row is None
        or len(membership_row) != 1
        or isinstance(membership_row[0], bool)
        or int(membership_row[0]) != 0
    ):
        raise DatabaseTransferError(
            "candidate PostgreSQL roleは他roleとのmembershipを持てません。"
        )
    if (
        other_database_ownership_row is None
        or len(other_database_ownership_row) != 1
        or isinstance(other_database_ownership_row[0], bool)
        or int(other_database_ownership_row[0]) != 0
    ):
        raise DatabaseTransferError(
            "candidate PostgreSQL roleはcandidate以外のDBを所有できません。"
        )


def _assert_candidate_database_acl_is_owner_only(
    connection,
    *,
    database_name: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS non_owner_privileges "
            "FROM pg_database d "
            "CROSS JOIN LATERAL aclexplode("
            "COALESCE(d.datacl, acldefault('d', d.datdba))) a "
            "WHERE d.datname = %s AND a.grantee <> 0 "
            "AND a.grantee <> d.datdba "
            "AND a.privilege_type IN ('CONNECT', 'TEMPORARY')",
            (database_name,),
        )
        row = cursor.fetchone()
    if (
        row is None
        or len(row) != 1
        or isinstance(row[0], bool)
        or int(row[0]) != 0
    ):
        raise DatabaseTransferError(
            "candidate PostgreSQL DBにowner以外の接続または一時領域権限があります。"
        )


def _reject_ambient_libpq_environment() -> None:
    ambient_keys = sorted(
        key for key, value in os.environ.items() if key.startswith("PG") and value
    )
    if ambient_keys:
        raise DatabaseTransferError(
            "target clusterの曖昧化を避けるためambient PG*環境変数は使用できません: "
            + ", ".join(ambient_keys)
        )


def _required_target_env(suffix: str) -> str:
    name = f"{TARGET_ENV_PREFIX}{suffix}"
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise DatabaseTransferError(f"{name}を明示してください。")
    value = value.strip()
    _reject_unsafe_env_value(value, label=name)
    return value


def _reject_unsafe_env_value(value: str, *, label: str) -> None:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise DatabaseTransferError(f"{label}に安全でない文字があります。")


def _validated_postgresql_identifier(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise DatabaseTransferError(f"{label}は安全な小文字PostgreSQL識別子に限定されます。")
    return value


def _assert_source_backup_snapshot_matches_run(
    backup_run: DatabaseBackupRun,
    snapshot: shared.PrivateFileSnapshot,
) -> None:
    expected_sha256 = (backup_run.backup_sha256 or "").strip().lower()
    if snapshot.size != backup_run.backup_file_size or snapshot.sha256 != expected_sha256:
        raise DatabaseTransferError("SQLite backup artifactが監査記録と一致しません。")


def _create_postgresql_clone_under_locks(
    *,
    backup_run: DatabaseBackupRun,
    verification_run: DatabaseBackupVerificationRun,
    backup_file_path: Path,
    source_snapshot: shared.PrivateFileSnapshot,
    target: PostgreSQLCloneTarget,
    target_database_name: str,
    manifest_path: Path,
    live_identity: shared.RuntimeIdentitySnapshot,
    admin_connection,
) -> PostgreSQLTransferResult:
    primary_database: _OwnedDatabase | None = None
    verification_database: _OwnedDatabase | None = None
    operation_error: BaseException | None = None
    cleanup_errors: list[tuple[str, BaseException]] = []
    completed_result: PostgreSQLTransferResult | None = None

    with tempfile.TemporaryDirectory(prefix="templedb-sqlite-to-postgresql-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        os.chmod(temp_dir, 0o700)
        source_copy_path = temp_dir / "verified-source.sqlite3"
        source_fixture = temp_dir / "source.json"
        staged_fixture = temp_dir / "staged-target.json"
        source_metadata_fixture = temp_dir / "source-metadata.json"
        primary_fixture = temp_dir / "primary-target.json"
        primary_metadata_fixture = temp_dir / "primary-target-metadata.json"
        verification_fixture = temp_dir / "restored-target.json"
        verification_metadata_fixture = temp_dir / "restored-target-metadata.json"
        target_dump_path = temp_dir / "target.dump"
        temp_manifest_path = manifest_path.with_name(
            f".{manifest_path.name}.{uuid.uuid4().hex}.part"
        )
        completion_marker_path = _postgresql_completion_marker_path(manifest_path)

        try:
            _assert_target_cluster_preconditions(
                admin_connection,
                target=target,
                target_database_name=target_database_name,
            )
            _copy_verified_sqlite_artifact(
                backup_file_path,
                source_copy_path,
                expected_snapshot=source_snapshot,
            )
            _revalidate_source_artifact(
                backup_run,
                backup_file_path,
                expected_snapshot=source_snapshot,
            )

            source_env = _sqlite_source_environment(source_copy_path)
            shared._run_manage_py(
                ["migrate", "--noinput", "--verbosity", "0"],
                env=source_env,
                stage="private SQLite copyのmigration",
            )
            shared._ensure_no_sqlite_sidecars(source_copy_path)
            source_identity = _read_sqlite_runtime_identity(source_copy_path)
            shared._assert_source_identity_matches_live(source_identity, live_identity)
            source_checks = shared._validate_sqlite_clone(
                source_copy_path,
                expected_identity=source_identity,
            )
            source_migrations = shared._read_sqlite_migrations(source_copy_path)
            shared._run_manage_py(
                ["migrate", "--check", "--verbosity", "0"],
                env=source_env,
                stage="private SQLite copyのmigration確認",
            )
            shared._run_manage_py(
                ["check"],
                env=source_env,
                stage="private SQLite copyのDjango system check",
            )
            shared._dump_fixture(
                source_fixture,
                source_env,
                shared.TRANSFERRED_MODEL_LABELS,
            )
            safety_changes = shared._prepare_staged_clone_fixture(
                source_fixture,
                staged_fixture,
            )
            shared._dump_fixture(
                source_metadata_fixture,
                source_env,
                shared.REGENERATED_MODEL_LABELS,
            )
            source_fingerprints = shared.fixture_fingerprints(
                source_fixture,
                expected_model_labels=shared.TRANSFERRED_MODEL_LABELS,
            )
            expected_target_fingerprints = shared.fixture_fingerprints(
                staged_fixture,
                expected_model_labels=shared.TRANSFERRED_MODEL_LABELS,
            )
            source_metadata_fingerprints = shared.fixture_fingerprints(
                source_metadata_fixture,
                expected_model_labels=shared.REGENERATED_MODEL_LABELS,
            )

            primary_database = _create_owned_database(
                admin_connection,
                target=target,
                backup_run_id=backup_run.id,
            )
            _harden_postgresql_schema(target.runtime, primary_database.name)
            primary_env = _postgresql_transfer_environment(
                target.runtime,
                primary_database.name,
            )
            shared._run_manage_py(
                ["migrate", "--noinput", "--verbosity", "0"],
                env=primary_env,
                stage="一時PostgreSQLの初期migration",
            )
            expected_schema_inventory = _read_postgresql_schema_inventory(
                target.runtime,
                primary_database.name,
            )
            shared._run_manage_py(
                ["loaddata", str(staged_fixture), "--verbosity", "0"],
                env=primary_env,
                stage="一時PostgreSQLへのデータ投入",
            )
            _write_postgresql_runtime_identity(
                target.runtime,
                primary_database.name,
                source_identity,
            )
            primary_validation = _validate_postgresql_clone(
                target=target,
                database=primary_database,
                expected_identity=source_identity,
                expected_migrations=source_migrations,
                env=primary_env,
                fixture_path=primary_fixture,
                metadata_fixture_path=primary_metadata_fixture,
                source_metadata_fixture_path=source_metadata_fixture,
                expected_target_fingerprints=expected_target_fingerprints,
                expected_schema_inventory=expected_schema_inventory,
            )

            with _postgresql_write_guard(
                target.runtime,
                primary_database.name,
            ) as (write_guard_connection, write_guard_backend_pid):
                _dump_postgresql_database(
                    target.runtime,
                    primary_database.name,
                    target_dump_path,
                )
                dump_snapshot = shared._capture_private_file_snapshot(target_dump_path)
                verification_database = _create_owned_database(
                    admin_connection,
                    target=target,
                    backup_run_id=backup_run.id,
                )
                _harden_postgresql_schema(target.runtime, verification_database.name)
                _restore_postgresql_database(
                    target.runtime,
                    verification_database.name,
                    target_dump_path,
                )
                shared._assert_private_file_matches_snapshot(target_dump_path, dump_snapshot)
                verification_env = _postgresql_transfer_environment(
                    target.runtime,
                    verification_database.name,
                )
                verification_validation = _validate_postgresql_clone(
                    target=target,
                    database=verification_database,
                    expected_identity=source_identity,
                    expected_migrations=source_migrations,
                    env=verification_env,
                    fixture_path=verification_fixture,
                    metadata_fixture_path=verification_metadata_fixture,
                    source_metadata_fixture_path=source_metadata_fixture,
                    expected_target_fingerprints=expected_target_fingerprints,
                    expected_schema_inventory=expected_schema_inventory,
                )
                shared._assert_fingerprints_match(
                    primary_validation["model_fingerprints"],
                    verification_validation["model_fingerprints"],
                    category="PostgreSQL dump再復元後の業務データ",
                )
                shared._assert_fingerprints_match(
                    primary_validation["metadata_fingerprints"],
                    verification_validation["metadata_fingerprints"],
                    category="PostgreSQL dump再復元後のmetadata",
                )
                _drop_owned_database(admin_connection, verification_database)
                verification_database = None

                _revalidate_source_artifact(
                    backup_run,
                    backup_file_path,
                    expected_snapshot=source_snapshot,
                )
                _freeze_owned_database(
                    admin_connection,
                    database=primary_database,
                    expected_owner=target.runtime.database_user,
                    preserved_backend_pid=write_guard_backend_pid,
                )
                final_primary_sequence_checks = _validate_postgresql_sequences_on_connection(
                    write_guard_connection
                )
                if final_primary_sequence_checks != verification_validation["sequence_checks"]:
                    raise DatabaseTransferError(
                        "write guard下のprimary sequenceが再復元DBと一致しません。"
                    )
                final_primary_schema_inventory = (
                    _read_postgresql_schema_inventory_on_connection(
                        write_guard_connection
                    )
                )
                if final_primary_schema_inventory != expected_schema_inventory:
                    raise DatabaseTransferError(
                        "凍結直前のprimary schema定義が初期migration時と一致しません: "
                        + _schema_inventory_difference(
                            expected_schema_inventory,
                            final_primary_schema_inventory,
                        )
                    )
                if (
                    final_primary_schema_inventory
                    != verification_validation["schema_inventory"]
                ):
                    raise DatabaseTransferError(
                        "凍結直前のprimary schema定義が再復元DBと一致しません: "
                        + _schema_inventory_difference(
                            verification_validation["schema_inventory"],
                            final_primary_schema_inventory,
                        )
                    )
                cluster_information = _read_target_cluster_information(admin_connection)
                transferred_object_count = sum(
                    int(item["count"]) for item in source_fingerprints.values()
                )
                manifest = _build_postgresql_transfer_manifest(
                    backup_run=backup_run,
                    verification_run=verification_run,
                    target_database_name=target_database_name,
                    completion_marker_path=completion_marker_path,
                    primary_database=primary_database,
                    source_snapshot=source_snapshot,
                    source_identity=source_identity,
                    source_migrations=source_migrations,
                    source_fingerprints=source_fingerprints,
                    expected_target_fingerprints=expected_target_fingerprints,
                    source_metadata_fingerprints=source_metadata_fingerprints,
                    safety_changes=safety_changes,
                    source_checks=source_checks,
                    primary_validation=primary_validation,
                    verification_validation=verification_validation,
                    final_primary_sequence_checks=final_primary_sequence_checks,
                    final_primary_schema_inventory=final_primary_schema_inventory,
                    target_dump_snapshot=dump_snapshot,
                    target=target,
                    cluster_information=cluster_information,
                    transferred_object_count=transferred_object_count,
                )
                shared._write_private_json_file(temp_manifest_path, manifest)
                manifest_snapshot = shared._capture_private_file_snapshot(temp_manifest_path)

            final_database = _rename_frozen_database(
                admin_connection,
                database=primary_database,
                target_database_name=target_database_name,
                expected_owner=target.runtime.database_user,
            )
            primary_database = None
            _publish_postgresql_manifest(
                admin_connection,
                database=final_database,
                expected_owner=target.runtime.database_user,
                temp_manifest_path=temp_manifest_path,
                manifest_snapshot=manifest_snapshot,
                manifest_path=manifest_path,
                completion_marker_path=completion_marker_path,
            )
            completed_result = PostgreSQLTransferResult(
                database_name=final_database.name,
                database_oid=final_database.oid,
                manifest_path=manifest_path,
                completion_marker_path=completion_marker_path,
                transferred_object_count=transferred_object_count,
                source_backup_run_id=backup_run.id,
                source_verification_run_id=verification_run.id,
                connections_allowed=False,
            )
        except BaseException as exc:
            operation_error = exc
        finally:
            for database in (verification_database, primary_database):
                if database is None:
                    continue
                try:
                    _drop_owned_database(admin_connection, database)
                except BaseException as exc:
                    cleanup_errors.append((database.name, exc))
            shared._best_effort_remove_owned_file(temp_manifest_path)

    if cleanup_errors:
        detail = "; ".join(f"{name}: {exc}" for name, exc in cleanup_errors)
        message = (
            "所有権を確認できた一時PostgreSQL DBを削除できなかったため、"
            f"処理を完了していません: {detail}"
        )
        if operation_error is not None:
            message += " 移送処理自体にも失敗があります。"
        raise DatabaseTransferError(message) from cleanup_errors[0][1]
    if operation_error is not None:
        if isinstance(operation_error, DatabaseTransferError):
            raise operation_error
        if isinstance(operation_error, Exception):
            raise DatabaseTransferError(
                "SQLiteからPostgreSQLへの移送に失敗しました。"
            ) from operation_error
        raise operation_error
    if completed_result is None:
        raise DatabaseTransferError("PostgreSQLクローンの完了結果を確認できませんでした。")
    return completed_result


@contextmanager
def _target_cluster_guard(admin_config: backup.PostgresAdminConfig):
    try:
        connection = psycopg.connect(
            **_connection_kwargs(admin_config, admin_config.database_name),
            autocommit=True,
        )
    except Exception as exc:
        raise DatabaseTransferError("target PostgreSQL admin databaseへ接続できません。") from exc
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (TARGET_CLUSTER_LOCK_KEY_1, TARGET_CLUSTER_LOCK_KEY_2),
            )
            if cursor.fetchone() != (True,):
                raise DatabaseTransferError("target PostgreSQLで別のDB移送が実行中です。")
        yield connection
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (TARGET_CLUSTER_LOCK_KEY_1, TARGET_CLUSTER_LOCK_KEY_2),
                )
        finally:
            connection.close()


def _connection_kwargs(config, database_name: str) -> dict[str, object]:
    values = {
        "dbname": database_name,
        "user": config.database_user or None,
        "password": config.database_password or None,
        "host": config.database_host or None,
        "port": config.database_port or None,
    }
    return {key: value for key, value in values.items() if value not in {None, ""}}


def _assert_target_cluster_preconditions(
    admin_connection,
    *,
    target: PostgreSQLCloneTarget,
    target_database_name: str,
) -> None:
    if target.admin.database_name == target_database_name:
        raise DatabaseTransferError("admin databaseをclone名と同じにはできません。")
    if _read_database_state(admin_connection, target_database_name) is not None:
        raise DatabaseTransferError(
            "同名のPostgreSQL DBが既にあります。既存DBは一切変更しません。"
        )
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s",
            (target.runtime.database_user,),
        )
        owner_row = cursor.fetchone()
        cursor.execute(
            "SELECT datname FROM pg_database "
            "WHERE left(datname, %s) = %s ORDER BY datname",
            (len("templedb_transfer_"), "templedb_transfer_"),
        )
        lingering_database_names = [str(row[0]) for row in cursor.fetchall()]
    if owner_row is None or owner_row != (True,):
        raise DatabaseTransferError(
            "target PostgreSQL owner roleが存在しないかloginできません。"
        )
    if lingering_database_names:
        raise DatabaseTransferError(
            "未解決の一時PostgreSQL DBがあるため、新しい移送を開始しません: "
            + ", ".join(lingering_database_names)
        )


def _build_transfer_database_name(backup_run_id: int) -> str:
    timestamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    database_name = (
        f"templedb_transfer_{timestamp}_{backup_run_id}_{uuid.uuid4().hex[:16]}"
    )
    if len(database_name) > 63 or not TRANSFER_DATABASE_PATTERN.fullmatch(database_name):
        raise DatabaseTransferError("安全な一時PostgreSQL DB名を作成できませんでした。")
    return database_name


def _create_owned_database(
    admin_connection,
    *,
    target: PostgreSQLCloneTarget,
    backup_run_id: int,
) -> _OwnedDatabase:
    database_name = _build_transfer_database_name(backup_run_id)
    token = f"{DATABASE_COMMENT_PREFIX}{uuid.uuid4()}"
    try:
        with admin_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE DATABASE {} WITH TEMPLATE template0 ENCODING 'UTF8' OWNER {}"
                ).format(
                    sql.Identifier(database_name),
                    sql.Identifier(target.runtime.database_user),
                )
            )
            cursor.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(database_name),
                    sql.Literal(token),
                )
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC"
                ).format(sql.Identifier(database_name))
            )
        state = _read_database_state(admin_connection, database_name)
        if state is None:
            raise DatabaseTransferError("作成した一時PostgreSQL DBを確認できません。")
        _assert_created_database_state(
            state,
            expected_owner=target.runtime.database_user,
            expected_token=token,
        )
        return _OwnedDatabase(name=database_name, oid=state.oid, token=token)
    except BaseException as exc:
        state = _best_effort_read_database_state(
            admin_connection,
            database_name,
            admin_config=target.admin,
        )
        if state is not None:
            if (
                state.owner == target.runtime.database_user
                and state.comment == token
                and TRANSFER_DATABASE_PATTERN.fullmatch(state.name)
            ):
                owned = _OwnedDatabase(name=state.name, oid=state.oid, token=token)
                try:
                    _drop_owned_database(admin_connection, owned)
                except BaseException as cleanup_exc:
                    raise DatabaseTransferError(
                        f"一時PostgreSQL DB {database_name} の作成確認中に失敗し、"
                        "所有権確認後の削除にも失敗しました。"
                    ) from cleanup_exc
            else:
                raise DatabaseTransferError(
                    f"一時PostgreSQL DB {database_name} が作成された可能性がありますが、"
                    "tokenによる所有権を証明できないため自動削除しません。"
                ) from exc
        if isinstance(exc, DatabaseTransferError):
            raise
        if isinstance(exc, Exception):
            raise DatabaseTransferError("一時PostgreSQL DBを安全に作成できませんでした。") from exc
        raise


def _assert_created_database_state(
    state: _DatabaseState,
    *,
    expected_owner: str,
    expected_token: str,
) -> None:
    if state.owner != expected_owner:
        raise DatabaseTransferError("一時PostgreSQL DBのownerが指定値と一致しません。")
    if state.encoding != "UTF8":
        raise DatabaseTransferError("一時PostgreSQL DBのencodingがUTF8ではありません。")
    if not state.connections_allowed:
        raise DatabaseTransferError("一時PostgreSQL DBが接続可能状態ではありません。")
    if state.public_connect_allowed:
        raise DatabaseTransferError("一時PostgreSQL DBのPUBLIC接続権限を除去できませんでした。")
    if state.public_temporary_allowed:
        raise DatabaseTransferError("一時PostgreSQL DBのPUBLIC一時領域権限を除去できませんでした。")
    if state.comment != expected_token:
        raise DatabaseTransferError("一時PostgreSQL DBの所有tokenが一致しません。")


def _read_database_state(admin_connection, database_name: str) -> _DatabaseState | None:
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "SELECT d.datname, d.oid, pg_get_userbyid(d.datdba), "
            "pg_encoding_to_char(d.encoding), d.datallowconn, "
            "EXISTS ("
            "SELECT 1 FROM aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a "
            "WHERE a.grantee = 0 AND a.privilege_type = 'CONNECT'"
            "), "
            "EXISTS ("
            "SELECT 1 FROM aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a "
            "WHERE a.grantee = 0 AND a.privilege_type = 'TEMPORARY'"
            "), "
            "COALESCE(shobj_description(d.oid, 'pg_database'), '') "
            "FROM pg_database d WHERE d.datname = %s",
            (database_name,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _DatabaseState(
        name=str(row[0]),
        oid=int(row[1]),
        owner=str(row[2]),
        encoding=str(row[3]),
        connections_allowed=bool(row[4]),
        public_connect_allowed=bool(row[5]),
        public_temporary_allowed=bool(row[6]),
        comment=str(row[7]),
    )


def _best_effort_read_database_state(
    admin_connection,
    database_name: str,
    *,
    admin_config: backup.PostgresAdminConfig | None = None,
) -> _DatabaseState | None:
    try:
        return _read_database_state(admin_connection, database_name)
    except BaseException:
        if admin_config is None:
            return None
    try:
        with psycopg.connect(
            **_connection_kwargs(admin_config, admin_config.database_name),
            autocommit=True,
        ) as fresh_connection:
            return _read_database_state(fresh_connection, database_name)
    except BaseException:
        return None


def _drop_owned_database(admin_connection, database: _OwnedDatabase) -> None:
    if not TRANSFER_DATABASE_PATTERN.fullmatch(database.name):
        raise DatabaseTransferError(
            "最終名または不正な名前のPostgreSQL DBは自動削除しません。"
        )
    state = _read_database_state(admin_connection, database.name)
    if state is None:
        return
    if state.oid != database.oid or state.comment != database.token:
        raise DatabaseTransferError(
            "一時PostgreSQL DBのOIDまたはtokenが変化したため自動削除しません。"
        )
    with admin_connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS false").format(
                sql.Identifier(database.name)
            )
        )
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database.name,),
        )
        cursor.fetchall()
        state = _read_database_state(admin_connection, database.name)
        if state is None or state.oid != database.oid or state.comment != database.token:
            raise DatabaseTransferError(
                "削除直前に一時PostgreSQL DBの所有権を再確認できませんでした。"
            )
        cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database.name)))
    if _read_database_state(admin_connection, database.name) is not None:
        raise DatabaseTransferError("一時PostgreSQL DBの削除完了を確認できませんでした。")


@contextmanager
def _postgresql_write_guard(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
):
    try:
        connection = psycopg.connect(**_connection_kwargs(runtime_config, database_name))
    except Exception as exc:
        raise DatabaseTransferError(
            "一時PostgreSQLの最終write guardへ接続できません。"
        ) from exc
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute("SELECT pg_backend_pid()")
            backend_pid = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT n.nspname, c.relname "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('r', 'p') "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "ORDER BY 1, 2"
            )
            table_names = [(str(schema), str(table)) for schema, table in cursor.fetchall()]
            if not table_names:
                raise DatabaseTransferError(
                    "一時PostgreSQLにwrite guard対象tableがありません。"
                )
            cursor.execute(
                sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
                    sql.SQL(", ").join(
                        sql.SQL("{}.{}").format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                        )
                        for schema, table in table_names
                    )
                )
            )
        yield connection, backend_pid
    except DatabaseTransferError:
        connection.rollback()
        raise
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def _freeze_owned_database(
    admin_connection,
    *,
    database: _OwnedDatabase,
    expected_owner: str,
    preserved_backend_pid: int | None = None,
) -> None:
    if not TRANSFER_DATABASE_PATTERN.fullmatch(database.name):
        raise DatabaseTransferError("公開対象の一時PostgreSQL DB名が安全ではありません。")
    state = _read_database_state(admin_connection, database.name)
    if state is None or state.oid != database.oid or state.comment != database.token:
        raise DatabaseTransferError("公開前に一時PostgreSQL DBの所有権を確認できません。")
    if (
        state.owner != expected_owner
        or state.public_connect_allowed
        or state.public_temporary_allowed
    ):
        raise DatabaseTransferError("公開前に一時PostgreSQL DBのownerが変化しました。")
    with admin_connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS false").format(
                sql.Identifier(database.name)
            )
        )
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid() AND pid <> %s",
            (database.name, preserved_backend_pid or -1),
        )
        cursor.fetchall()
        frozen_state = _read_database_state(admin_connection, database.name)
        if (
            frozen_state is None
            or frozen_state.oid != database.oid
            or frozen_state.comment != database.token
            or frozen_state.connections_allowed
            or frozen_state.public_connect_allowed
            or frozen_state.public_temporary_allowed
        ):
            raise DatabaseTransferError("公開直前に一時PostgreSQL DBを凍結できませんでした。")
        cursor.execute(
            "SELECT pid FROM pg_stat_activity WHERE datname = %s ORDER BY pid",
            (database.name,),
        )
        active_backend_pids = [int(row[0]) for row in cursor.fetchall()]
    expected_pids = [preserved_backend_pid] if preserved_backend_pid is not None else []
    if active_backend_pids != expected_pids:
        raise DatabaseTransferError(
            "一時PostgreSQL DBの凍結後に予期しない接続が残っています。"
        )


def _rename_frozen_database(
    admin_connection,
    *,
    database: _OwnedDatabase,
    target_database_name: str,
    expected_owner: str,
) -> _OwnedDatabase:
    state = _read_database_state(admin_connection, database.name)
    if (
        state is None
        or state.oid != database.oid
        or state.comment != database.token
        or state.owner != expected_owner
        or state.connections_allowed
        or state.public_connect_allowed
        or state.public_temporary_allowed
    ):
        raise DatabaseTransferError("rename前の一時PostgreSQL DBが凍結状態ではありません。")
    if _read_database_state(admin_connection, target_database_name) is not None:
        raise DatabaseTransferError(
            "rename直前に同名PostgreSQL DBが作成されたため上書きせず停止しました。"
        )
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = %s",
            (database.name,),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise DatabaseTransferError("rename前の凍結DBに接続が残っています。")
        cursor.execute(
            sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                sql.Identifier(database.name),
                sql.Identifier(target_database_name),
            )
        )
    final_state = _read_database_state(admin_connection, target_database_name)
    if (
        final_state is None
        or final_state.oid != database.oid
        or final_state.comment != database.token
        or final_state.owner != expected_owner
        or final_state.connections_allowed
        or final_state.public_connect_allowed
        or final_state.public_temporary_allowed
    ):
        raise DatabaseTransferError(
            "凍結PostgreSQLクローンのrename後状態を確認できません。自動削除しません。"
        )
    return _OwnedDatabase(
        name=target_database_name,
        oid=database.oid,
        token=database.token,
    )


def _freeze_and_rename_database(
    admin_connection,
    *,
    database: _OwnedDatabase,
    target_database_name: str,
    expected_owner: str,
) -> _OwnedDatabase:
    if _read_database_state(admin_connection, target_database_name) is not None:
        raise DatabaseTransferError(
            "公開直前に同名PostgreSQL DBが作成されたため、既存DBを変更せず停止しました。"
        )
    _freeze_owned_database(
        admin_connection,
        database=database,
        expected_owner=expected_owner,
    )
    return _rename_frozen_database(
        admin_connection,
        database=database,
        target_database_name=target_database_name,
        expected_owner=expected_owner,
    )


def _copy_verified_sqlite_artifact(
    source_path: Path,
    destination_path: Path,
    *,
    expected_snapshot: shared.PrivateFileSnapshot,
) -> None:
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd = os.open(source_path, source_flags)
        source_stat = os.fstat(source_fd)
        _assert_fd_matches_snapshot(source_stat, expected_snapshot)
        destination_fd = os.open(
            destination_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        digest = hashlib.sha256()
        copied_size = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            copied_size += len(chunk)
            offset = 0
            while offset < len(chunk):
                written = os.write(destination_fd, chunk[offset:])
                if written <= 0:
                    raise OSError("private SQLite copyへの書き込みが停止しました。")
                offset += written
        os.fsync(destination_fd)
        _assert_fd_matches_snapshot(os.fstat(source_fd), expected_snapshot)
        if copied_size != expected_snapshot.size or digest.hexdigest() != expected_snapshot.sha256:
            raise DatabaseTransferError("private SQLite copyが検証済みartifactと一致しません。")
    except BaseException:
        shared._best_effort_remove_owned_file(destination_path)
        raise
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
    shared._assert_private_file_matches_snapshot(source_path, expected_snapshot)
    copied_snapshot = shared._capture_private_file_snapshot(destination_path)
    if (
        copied_snapshot.size != expected_snapshot.size
        or copied_snapshot.sha256 != expected_snapshot.sha256
    ):
        shared._best_effort_remove_owned_file(destination_path)
        raise DatabaseTransferError("private SQLite copyの最終照合に失敗しました。")


def _assert_fd_matches_snapshot(
    stat_result: os.stat_result,
    expected_snapshot: shared.PrivateFileSnapshot,
) -> None:
    if not stat.S_ISREG(stat_result.st_mode):
        raise DatabaseTransferError("SQLite backup artifactが通常fileではありません。")
    if stat.S_IMODE(stat_result.st_mode) != 0o600:
        raise DatabaseTransferError("SQLite backup artifactの権限が0600ではありません。")
    if (
        stat_result.st_dev != expected_snapshot.device
        or stat_result.st_ino != expected_snapshot.inode
        or stat_result.st_size != expected_snapshot.size
    ):
        raise DatabaseTransferError("SQLite backup artifactが移送中に差し替えられました。")


def _revalidate_source_artifact(
    backup_run: DatabaseBackupRun,
    backup_file_path: Path,
    *,
    expected_snapshot: shared.PrivateFileSnapshot,
) -> None:
    shared._assert_private_file_matches_snapshot(backup_file_path, expected_snapshot)
    revalidated_path = backup.validate_backup_artifact(backup_run)
    if revalidated_path != backup_file_path:
        raise DatabaseTransferError("SQLite backup artifactの監査pathが変化しました。")
    shared._assert_private_file_matches_snapshot(backup_file_path, expected_snapshot)


def _read_sqlite_runtime_identity(sqlite_path: Path) -> shared.RuntimeIdentitySnapshot:
    try:
        with sqlite3.connect(sqlite_path) as connection:
            rows = connection.execute(
                "SELECT installation_id, runtime_kind, created_at, updated_at "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseTransferError("private SQLite copyのDB identityを読めません。") from exc
    if len(rows) != 1:
        raise DatabaseTransferError("private SQLite copyのDB identityが一意ではありません。")
    installation_id, runtime_kind, raw_created_at, raw_updated_at = rows[0]
    created_at = parse_datetime(str(raw_created_at))
    updated_at = parse_datetime(str(raw_updated_at))
    if created_at is None or updated_at is None:
        raise DatabaseTransferError("private SQLite copyのDB identity日時が不正です。")
    if timezone.is_naive(created_at):
        created_at = timezone.make_aware(created_at, UTC)
    if timezone.is_naive(updated_at):
        updated_at = timezone.make_aware(updated_at, UTC)
    return shared.RuntimeIdentitySnapshot(
        installation_id=str(installation_id),
        runtime_kind=str(runtime_kind),
        created_at=created_at,
        updated_at=updated_at,
    )


def _sanitized_process_environment() -> dict[str, str]:
    env = {}
    for key, value in os.environ.items():
        if (
            key in DATABASE_ENVIRONMENT_KEYS
            or key.startswith("DATABASE_")
            or key.startswith("PG")
            or key.startswith(TARGET_ENV_PREFIX)
        ):
            continue
        if key in {
            "TEMPLEDB_DATABASE_ENGINE",
            "TEMPLEDB_DEMO_MODE",
            "TEMPLEDB_SQLITE_DB_PATH",
        }:
            continue
        env[key] = value
    return env


def _sqlite_source_environment(sqlite_path: Path) -> dict[str, str]:
    env = _sanitized_process_environment()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "TEMPLEDB_DATABASE_ENGINE": "sqlite",
            "TEMPLEDB_DEMO_MODE": "0",
            "TEMPLEDB_SQLITE_DB_PATH": str(sqlite_path),
            "DATABASE_URL": "",
            "DATABASE_HOST": "",
            "DATABASE_NAME": "",
            "DATABASE_USER": "",
            "DATABASE_PASSWORD": "",
            "DATABASE_PORT": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _postgresql_transfer_environment(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> dict[str, str]:
    env = _sanitized_process_environment()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "TEMPLEDB_DATABASE_ENGINE": "postgresql",
            "TEMPLEDB_DEMO_MODE": "0",
            "DATABASE_NAME": database_name,
            "DATABASE_USER": runtime_config.database_user,
            "DATABASE_PASSWORD": runtime_config.database_password,
            "DATABASE_HOST": runtime_config.database_host,
            "DATABASE_PORT": runtime_config.database_port,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _postgresql_command_environment(password: str) -> dict[str, str]:
    env = _sanitized_process_environment()
    env["PGCONNECT_TIMEOUT"] = "10"
    if password:
        env["PGPASSWORD"] = password
    return env


def _postgresql_connection_config(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> backup.PostgresConnectionConfig:
    return backup.PostgresConnectionConfig(
        database_name=database_name,
        database_user=runtime_config.database_user,
        database_password=runtime_config.database_password,
        database_host=runtime_config.database_host,
        database_port=runtime_config.database_port,
    )


def _dump_postgresql_database(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
    output_path: Path,
) -> None:
    config = _postgresql_connection_config(runtime_config, database_name)
    shared._create_private_empty_file(output_path)
    try:
        backup._run_command(
            backup.build_pg_dump_command(config, output_path=output_path),
            env=_postgresql_command_environment(config.database_password),
        )
        shared._fsync_file(output_path)
        shared._capture_private_file_snapshot(output_path)
    except BaseException:
        shared._best_effort_remove_owned_file(output_path)
        raise


def _restore_postgresql_database(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
    backup_file_path: Path,
    *,
    single_transaction: bool = False,
) -> None:
    executable = backup.ensure_command_available("pg_restore") or "pg_restore"
    command = [executable, "--exit-on-error", "--no-owner", "--no-privileges"]
    if single_transaction:
        command.append("--single-transaction")
    if runtime_config.database_host:
        command.extend(["-h", runtime_config.database_host])
    if runtime_config.database_port:
        command.extend(["-p", runtime_config.database_port])
    if runtime_config.database_user:
        command.extend(["-U", runtime_config.database_user])
    command.extend(["-d", database_name, str(backup_file_path)])
    backup._run_command(
        command,
        env=_postgresql_command_environment(runtime_config.database_password),
    )


def _validated_pack_restore_summary(
    raw_restore_summary: object,
    *,
    expected_backup_run_id: int,
    expected_installation_id: str,
) -> dict[str, object]:
    expected_wrapper_fields = {
        "backup_run_id",
        "verification_run_id",
        "status",
        "finished_at",
        "summary",
    }
    if (
        not isinstance(raw_restore_summary, Mapping)
        or set(raw_restore_summary) != expected_wrapper_fields
        or raw_restore_summary.get("status") != "succeeded"
        or raw_restore_summary.get("backup_run_id") != expected_backup_run_id
        or isinstance(raw_restore_summary.get("verification_run_id"), bool)
        or not isinstance(raw_restore_summary.get("verification_run_id"), int)
        or int(raw_restore_summary["verification_run_id"]) <= 0
        or not str(raw_restore_summary.get("finished_at") or "").strip()
    ):
        raise DatabaseTransferError(
            "運用パックのテスト復元記録がbackup runと一致しません。"
        )
    return _validated_postgresql_restore_summary(
        raw_restore_summary.get("summary"),
        expected_installation_id=expected_installation_id,
        label="運用パック",
    )


def _validated_postgresql_restore_summary(
    raw_summary: object,
    *,
    expected_installation_id: str,
    label: str,
) -> dict[str, object]:
    count_fields = {
        "django_migrations",
        "auth_user",
        "imports_household",
        "imports_person",
        "imports_deceasedprofile",
    }
    expected_fields = count_fields | {
        backup_restore_contract.RESTORE_CONTRACT_KEY,
    }
    if not isinstance(raw_summary, Mapping) or set(raw_summary) != expected_fields:
        raise DatabaseTransferError(f"{label}のPostgreSQL復元結果の項目が不正です。")

    normalized_summary: dict[str, object] = {}
    for field in sorted(count_fields):
        value = raw_summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DatabaseTransferError(
                f"{label}のPostgreSQL復元件数が不正です: {field}"
            )
        normalized_summary[field] = value
    try:
        contract = backup_restore_contract.validated_restore_contract(
            raw_summary,
            expected_database_engine="postgresql",
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise DatabaseTransferError(
            f"{label}のPostgreSQL復元契約が不正です。"
        ) from exc
    if (
        contract["database_version_scope"] != "server_major"
        or not str(contract["database_version"]).isdigit()
    ):
        raise DatabaseTransferError(
            f"{label}のPostgreSQL major version契約が不正です。"
        )
    try:
        normalized_installation_id = str(uuid.UUID(str(expected_installation_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DatabaseTransferError("確認用installation IDが不正です。") from exc
    if (
        contract["runtime_identity"]["installation_id"]
        != normalized_installation_id
        or contract["runtime_identity"]["runtime_kind"] != "product"
    ):
        raise DatabaseTransferError(
            f"{label}の製品DB識別情報が確認値と一致しません。"
        )
    normalized_summary[backup_restore_contract.RESTORE_CONTRACT_KEY] = contract
    if dict(raw_summary) != normalized_summary:
        raise DatabaseTransferError(
            f"{label}のPostgreSQL復元結果が正規形式ではありません。"
        )
    return normalized_summary


def _postgresql_major_from_restore_summary(
    summary: Mapping[str, object],
    *,
    label: str,
) -> int:
    raw_contract = summary.get(backup_restore_contract.RESTORE_CONTRACT_KEY)
    if not isinstance(raw_contract, Mapping):
        raise DatabaseTransferError(f"{label}のPostgreSQL復元契約が不正です。")
    raw_major = raw_contract.get("database_version")
    if isinstance(raw_major, bool) or not str(raw_major).isdigit():
        raise DatabaseTransferError(
            f"{label}のPostgreSQL major version契約が不正です。"
        )
    return int(str(raw_major))


def _validated_target_postgresql_major(
    raw_target_major: object,
    *,
    source_postgresql_major: int,
) -> int:
    if (
        isinstance(raw_target_major, bool)
        or not isinstance(raw_target_major, int)
        or raw_target_major <= 0
    ):
        raise DatabaseTransferError("確認用target PostgreSQL majorが不正です。")
    if raw_target_major not in {
        source_postgresql_major,
        source_postgresql_major + 1,
    }:
        raise DatabaseTransferError(
            "PostgreSQL major移行は同一majorまたはちょうど+1だけ許可されます。"
        )
    return raw_target_major


def _assert_postgresql_restore_summaries_match(
    *,
    expected_summary: dict[str, object],
    actual_summary: dict[str, object],
    expected_target_postgresql_major: int,
) -> None:
    expected_contract = dict(
        expected_summary[backup_restore_contract.RESTORE_CONTRACT_KEY]
    )
    actual_contract = dict(
        actual_summary[backup_restore_contract.RESTORE_CONTRACT_KEY]
    )
    if actual_contract["database_version"] != str(expected_target_postgresql_major):
        raise DatabaseTransferError(
            "PostgreSQL candidateのmajor versionが確認値と一致しません。"
        )
    actual_contract["database_version"] = expected_contract["database_version"]
    comparable_actual = dict(actual_summary)
    comparable_actual[backup_restore_contract.RESTORE_CONTRACT_KEY] = actual_contract
    comparable_expected = dict(expected_summary)
    comparable_expected[backup_restore_contract.RESTORE_CONTRACT_KEY] = (
        expected_contract
    )
    if comparable_actual != comparable_expected:
        raise DatabaseTransferError(
            "PostgreSQL candidateの復元結果が運用パックの検証結果と一致しません。"
        )


def _validate_restored_postgresql_candidate(
    *,
    target: PostgreSQLCloneTarget,
    database: _OwnedDatabase,
    expected_summary: dict[str, object],
    expected_installation_id: str,
    expected_target_postgresql_major: int,
) -> dict[str, object]:
    config = _postgresql_connection_config(target.runtime, database.name)
    try:
        inspected_summary = backup_execution.inspect_restored_database(
            config,
            database.name,
        )
    except Exception as exc:
        raise DatabaseTransferError(
            "PostgreSQL candidateの復元結果を検査できません。"
        ) from exc
    actual_summary = _validated_postgresql_restore_summary(
        inspected_summary,
        expected_installation_id=expected_installation_id,
        label="PostgreSQL candidate",
    )
    _assert_postgresql_restore_summaries_match(
        expected_summary=expected_summary,
        actual_summary=actual_summary,
        expected_target_postgresql_major=expected_target_postgresql_major,
    )
    if _public_schema_create_allowed(target.runtime, database.name):
        raise DatabaseTransferError(
            "PostgreSQL candidateのpublic schemaにPUBLIC作成権限が残っています。"
        )
    unvalidated_constraints = _read_unvalidated_constraints(
        target.runtime,
        database.name,
    )
    if unvalidated_constraints:
        raise DatabaseTransferError(
            "PostgreSQL candidateに未検証constraintがあります: "
            + ", ".join(unvalidated_constraints)
        )
    if _count_broken_postgresql_generic_relations(
        target.runtime,
        database.name,
    ):
        raise DatabaseTransferError(
            "PostgreSQL candidateにGenericForeignKey不整合があります。"
        )
    sequence_checks = _validate_postgresql_sequences(
        target.runtime,
        database.name,
    )
    _read_postgresql_schema_inventory(target.runtime, database.name)
    env = _postgresql_transfer_environment(target.runtime, database.name)
    env["TEMPLEDB_RUNTIME_ROLE"] = "staging"
    shared._run_manage_py(
        ["migrate", "--check", "--verbosity", "0"],
        env=env,
        stage="PostgreSQL candidateのmigration確認",
    )
    shared._run_manage_py(
        ["check"],
        env=env,
        stage="PostgreSQL candidateのDjango system check",
    )
    return {
        "restore_summary": actual_summary,
        "source_postgresql_major": _postgresql_major_from_restore_summary(
            expected_summary,
            label="運用パック",
        ),
        "target_postgresql_major": expected_target_postgresql_major,
        "public_schema_create_allowed": False,
        "unvalidated_constraint_count": 0,
        "broken_generic_relation_count": 0,
        "sequence_checks": sequence_checks,
        "django_migration_check": "ok",
        "django_system_check": "ok",
    }


def _write_postgresql_runtime_identity(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
    identity: shared.RuntimeIdentitySnapshot,
) -> None:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE core_databaseruntimeidentity "
                    "SET installation_id = %s, runtime_kind = %s, "
                    "created_at = %s, updated_at = %s WHERE singleton_key = 1",
                    (
                        identity.installation_id,
                        identity.runtime_kind,
                        identity.created_at,
                        identity.updated_at,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DatabaseTransferError(
                        "一時PostgreSQLのDB identityを一意に更新できませんでした。"
                    )
    except DatabaseTransferError:
        raise
    except Exception as exc:
        raise DatabaseTransferError("一時PostgreSQLのDB identityを更新できません。") from exc


def _harden_postgresql_schema(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> None:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    except Exception as exc:
        raise DatabaseTransferError(
            "一時PostgreSQLのpublic schema権限を制限できません。"
        ) from exc
    if _public_schema_create_allowed(runtime_config, database_name):
        raise DatabaseTransferError(
            "一時PostgreSQLのPUBLIC schema作成権限が残っています。"
        )


def _public_schema_create_allowed(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> bool:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 "
                    "FROM pg_namespace n, "
                    "LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a "
                    "WHERE n.nspname = 'public' "
                    "AND a.grantee = 0 AND a.privilege_type = 'CREATE'"
                    ")"
                )
                return bool(cursor.fetchone()[0])
    except Exception as exc:
        raise DatabaseTransferError(
            "一時PostgreSQLのpublic schema権限を確認できません。"
        ) from exc


def _validate_postgresql_clone(
    *,
    target: PostgreSQLCloneTarget,
    database: _OwnedDatabase,
    expected_identity: shared.RuntimeIdentitySnapshot,
    expected_migrations: set[tuple[str, str]],
    env: dict[str, str],
    fixture_path: Path,
    metadata_fixture_path: Path,
    source_metadata_fixture_path: Path,
    expected_target_fingerprints: dict[str, dict[str, object]],
    expected_schema_inventory: dict[str, list[str]],
) -> dict[str, object]:
    actual_identity = _read_postgresql_runtime_identity(target.runtime, database.name)
    if actual_identity != expected_identity:
        raise DatabaseTransferError("PostgreSQLクローンのDB identityが移送元と一致しません。")
    actual_migrations = _read_postgresql_migrations(target.runtime, database.name)
    if actual_migrations != expected_migrations:
        raise DatabaseTransferError(
            "SQLiteとPostgreSQLの適用migration集合が一致しません。"
        )
    session_count = _read_postgresql_session_count(target.runtime, database.name)
    if session_count != 0:
        raise DatabaseTransferError("PostgreSQLクローンにlogin sessionが残っています。")
    if _public_schema_create_allowed(target.runtime, database.name):
        raise DatabaseTransferError(
            "PostgreSQLクローンのpublic schemaにPUBLIC作成権限が残っています。"
        )
    unvalidated_constraints = _read_unvalidated_constraints(target.runtime, database.name)
    if unvalidated_constraints:
        raise DatabaseTransferError(
            "PostgreSQLクローンに未検証constraintがあります: "
            + ", ".join(unvalidated_constraints)
        )
    broken_generic_relations = _count_broken_postgresql_generic_relations(
        target.runtime,
        database.name,
    )
    if broken_generic_relations:
        raise DatabaseTransferError(
            "PostgreSQLクローンにGenericForeignKey不整合があります。"
        )
    sequence_checks = _validate_postgresql_sequences(target.runtime, database.name)
    schema_inventory = _read_postgresql_schema_inventory(target.runtime, database.name)
    if schema_inventory != expected_schema_inventory:
        raise DatabaseTransferError(
            "PostgreSQLクローンのschema object集合が初期migration直後と一致しません: "
            + _schema_inventory_difference(
                expected_schema_inventory,
                schema_inventory,
            )
        )

    shared._run_manage_py(
        ["migrate", "--check", "--verbosity", "0"],
        env=env,
        stage="PostgreSQLクローンのmigration確認",
    )
    shared._run_manage_py(
        ["check"],
        env=env,
        stage="PostgreSQLクローンのDjango system check",
    )
    shared._dump_fixture(
        fixture_path,
        env,
        shared.TRANSFERRED_MODEL_LABELS,
    )
    shared._dump_fixture(
        metadata_fixture_path,
        env,
        shared.REGENERATED_MODEL_LABELS,
    )
    model_fingerprints = shared.fixture_fingerprints(
        fixture_path,
        expected_model_labels=shared.TRANSFERRED_MODEL_LABELS,
    )
    metadata_fingerprints = shared.fixture_fingerprints(
        metadata_fixture_path,
        expected_model_labels=shared.REGENERATED_MODEL_LABELS,
    )
    shared._assert_fingerprints_match(
        expected_target_fingerprints,
        model_fingerprints,
        category="SQLiteからPostgreSQLへの業務データ",
    )
    regenerated_metadata_summary = shared._validate_regenerated_metadata(
        source_metadata_fixture_path,
        metadata_fixture_path,
    )
    return {
        "model_fingerprints": model_fingerprints,
        "metadata_fingerprints": metadata_fingerprints,
        "regenerated_metadata_summary": regenerated_metadata_summary,
        "migration": _migration_summary(actual_migrations),
        "session_count": session_count,
        "public_schema_create_allowed": False,
        "unvalidated_constraint_count": 0,
        "broken_generic_relation_count": 0,
        "sequence_checks": sequence_checks,
        "schema_inventory": schema_inventory,
        "runtime_identity": {
            "installation_id": actual_identity.installation_id,
            "runtime_kind": actual_identity.runtime_kind,
            "created_at": actual_identity.created_at.isoformat(),
            "updated_at": actual_identity.updated_at.isoformat(),
        },
        "django_system_check": "ok",
    }


def _read_postgresql_runtime_identity(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> shared.RuntimeIdentitySnapshot:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT installation_id, runtime_kind, created_at, updated_at "
                    "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQLクローンのDB identityを読めません。") from exc
    if len(rows) != 1:
        raise DatabaseTransferError("PostgreSQLクローンのDB identityが一意ではありません。")
    installation_id, runtime_kind, created_at, updated_at = rows[0]
    return shared.RuntimeIdentitySnapshot(
        installation_id=str(installation_id),
        runtime_kind=str(runtime_kind),
        created_at=created_at,
        updated_at=updated_at,
    )


def _read_postgresql_migrations(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> set[tuple[str, str]]:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT app, name FROM django_migrations")
                return {(str(app), str(name)) for app, name in cursor.fetchall()}
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQLクローンのmigration記録を読めません。") from exc


def _read_postgresql_session_count(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> int:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM django_session")
                return int(cursor.fetchone()[0])
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQLクローンのsession件数を読めません。") from exc


def _read_unvalidated_constraints(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> list[str]:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT n.nspname || '.' || c.conname "
                    "FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE NOT c.convalidated "
                    "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                    "ORDER BY 1"
                )
                return [str(row[0]) for row in cursor.fetchall()]
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQL constraintを検証できません。") from exc


def _read_postgresql_schema_inventory(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> dict[str, list[str]]:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            return _read_postgresql_schema_inventory_on_connection(connection)
    except DatabaseTransferError:
        raise
    except Exception as exc:
        raise DatabaseTransferError(
            "PostgreSQLクローンのschema object集合を確認できません。"
        ) from exc


def _read_postgresql_schema_inventory_on_connection(
    connection,
) -> dict[str, list[str]]:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT n.nspname, pg_get_userbyid(n.nspowner), "
                "COALESCE(array_to_string(n.nspacl, ','), '') "
                "FROM pg_namespace n "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1"
            )
            schemas = [
                f"{schema}:{owner}:{acl}" for schema, owner, acl in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, c.relkind, c.relname, c.relpersistence, "
                "c.relrowsecurity, c.relforcerowsecurity, c.relreplident, "
                "COALESCE(array_to_string(c.relacl, ','), ''), "
                "COALESCE((SELECT string_agg(option, ',' ORDER BY option) "
                "FROM unnest(c.reloptions) option), '') "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f', 'i') "
                "ORDER BY 1, 2, 3"
            )
            relations = [
                ":".join(str(value) for value in row) for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, c.relname, "
                "row_number() OVER (PARTITION BY a.attrelid ORDER BY a.attnum), a.attname, "
                "format_type(a.atttypid, a.atttypmod), a.attnotnull, "
                "a.attidentity, a.attgenerated, "
                "COALESCE(cn.nspname || '.' || coll.collname, ''), "
                "COALESCE(pg_get_expr(ad.adbin, ad.adrelid), '') "
                "FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum "
                "LEFT JOIN pg_collation coll ON coll.oid = a.attcollation "
                "LEFT JOIN pg_namespace cn ON cn.oid = coll.collnamespace "
                "WHERE a.attnum > 0 AND NOT a.attisdropped "
                "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "ORDER BY 1, 2, 3"
            )
            columns = [
                ":".join(str(value) for value in row) for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, COALESCE(c.relname, ''), con.conname, "
                "con.contype, con.condeferrable, con.condeferred, con.convalidated, "
                "pg_get_constraintdef(con.oid, true) "
                "FROM pg_constraint con "
                "JOIN pg_namespace n ON n.oid = con.connamespace "
                "LEFT JOIN pg_class c ON c.oid = con.conrelid "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "ORDER BY 1, 2, 3"
            )
            constraints = []
            for row in cursor.fetchall():
                *identity, definition = row
                schema_name, table_name, constraint_name = (
                    str(identity[0]),
                    str(identity[1]),
                    str(identity[2]),
                )
                constraints.append(
                    ":".join(str(value) for value in identity)
                    + ":"
                    + _schema_definition_sha256(
                        _normalize_constraint_definition(
                            schema_name=schema_name,
                            table_name=table_name,
                            constraint_name=constraint_name,
                            definition=definition,
                        )
                    )
                )

            cursor.execute(
                "SELECT n.nspname, t.relname, i.relname, pg_get_indexdef(i.oid) "
                "FROM pg_index x "
                "JOIN pg_class i ON i.oid = x.indexrelid "
                "JOIN pg_class t ON t.oid = x.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2, 3"
            )
            indexes = [
                f"{schema}:{table}:{name}:{_schema_definition_sha256(definition)}"
                for schema, table, name, definition in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, c.relname, c.relkind, pg_get_viewdef(c.oid, true) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('v', 'm') "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2"
            )
            views = [
                f"{schema}:{name}:{kind}:{_schema_definition_sha256(definition)}"
                for schema, name, kind, definition in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), "
                "pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2, 3"
            )
            functions = [
                f"{schema}:{name}({arguments}):{_schema_definition_sha256(definition)}"
                for schema, name, arguments, definition in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid, true) "
                "FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE NOT t.tgisinternal "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2, 3"
            )
            triggers = [
                f"{schema}:{table}:{name}:{_schema_definition_sha256(definition)}"
                for schema, table, name, definition in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, c.relname, format_type(s.seqtypid, NULL), "
                "s.seqstart, s.seqmin, s.seqmax, s.seqincrement, s.seqcycle, s.seqcache "
                "FROM pg_sequence s "
                "JOIN pg_class c ON c.oid = s.seqrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2"
            )
            sequences = [
                ":".join(str(value) for value in row) for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT n.nspname, t.typname, t.typtype, "
                "CASE WHEN t.typbasetype = 0 THEN '' "
                "ELSE format_type(t.typbasetype, t.typtypmod) END, "
                "t.typnotnull, COALESCE(t.typdefault, ''), "
                "COALESCE((SELECT string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) "
                "FROM pg_enum e WHERE e.enumtypid = t.oid), '') "
                "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE t.typtype IN ('d', 'e') "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1, 2"
            )
            types = [
                ":".join(str(value) for value in row) for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT schemaname, tablename, policyname, permissive, roles::text, "
                "cmd, COALESCE(qual, ''), COALESCE(with_check, '') "
                "FROM pg_policies "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "AND schemaname NOT LIKE 'pg_toast%' ORDER BY 1, 2, 3"
            )
            policies = [
                ":".join(str(value) for value in row) for row in cursor.fetchall()
            ]
    except Exception as exc:
        raise DatabaseTransferError(
            "PostgreSQLクローンのschema定義を確認できません。"
        ) from exc
    return {
        "schemas": schemas,
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "views": views,
        "functions": functions,
        "triggers": triggers,
        "sequences": sequences,
        "types": types,
        "policies": policies,
    }


def _schema_definition_sha256(definition: object) -> str:
    return hashlib.sha256(str(definition).encode("utf-8")).hexdigest()


def _normalize_constraint_definition(
    *,
    schema_name: str,
    table_name: str,
    constraint_name: str,
    definition: object,
) -> str:
    value = str(definition).strip()
    key = (schema_name, table_name, constraint_name)
    if key != (
        "public",
        "core_databasebackuprun",
        "core_backup_run_engine_valid",
    ):
        return value
    known_equivalent_definitions = {
        "CHECK (database_engine::text = ANY (ARRAY['postgresql'::character varying, "
        "'sqlite'::character varying]::text[]))",
        "CHECK (database_engine::text = ANY "
        "(ARRAY['postgresql'::character varying::text, "
        "'sqlite'::character varying::text]))",
    }
    if value in known_equivalent_definitions:
        return "CHECK database_engine IN (postgresql, sqlite)"
    return value


def _schema_inventory_difference(
    expected: dict[str, list[str]],
    actual: dict[str, list[str]],
) -> str:
    details: list[str] = []
    for category in sorted(set(expected) | set(actual)):
        expected_values = set(expected.get(category, []))
        actual_values = set(actual.get(category, []))
        missing = sorted(expected_values - actual_values)
        unexpected = sorted(actual_values - expected_values)
        if not missing and not unexpected:
            continue
        fragments = [
            f"{category} missing={len(missing)} unexpected={len(unexpected)}"
        ]
        if missing:
            fragments.append(f"missing_sample={missing[0]}")
        if unexpected:
            fragments.append(f"unexpected_sample={unexpected[0]}")
        details.append(" ".join(fragments))
    return "; ".join(details) or "ordered inventory mismatch"


def _count_broken_postgresql_generic_relations(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> int:
    broken = 0
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, app_label, model FROM django_content_type")
                content_types = {
                    int(content_type_id): (str(app_label), str(model_name))
                    for content_type_id, app_label, model_name in cursor.fetchall()
                }
                for spec in shared.generic_foreign_key_validation_specs():
                    cursor.execute(
                        sql.SQL("SELECT {}, {} FROM {}").format(
                            sql.Identifier(spec.content_type_column),
                            sql.Identifier(spec.object_id_column),
                            sql.Identifier(spec.table_name),
                        )
                    )
                    for content_type_id, object_id in cursor.fetchall():
                        natural_key = content_types.get(int(content_type_id))
                        model = apps.get_model(*natural_key) if natural_key else None
                        if model is None or not model._meta.managed:
                            broken += 1
                            continue
                        cursor.execute(
                            sql.SQL("SELECT 1 FROM {} WHERE {} = %s LIMIT 1").format(
                                sql.Identifier(model._meta.db_table),
                                sql.Identifier(model._meta.pk.column),
                            ),
                            (object_id,),
                        )
                        if cursor.fetchone() is None:
                            broken += 1
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQL GenericForeignKeyを検証できません。") from exc
    return broken


def _validate_postgresql_sequences(
    runtime_config: backup.PostgresConnectionConfig,
    database_name: str,
) -> list[dict[str, object]]:
    try:
        with psycopg.connect(**_connection_kwargs(runtime_config, database_name)) as connection:
            return _validate_postgresql_sequences_on_connection(connection)
    except DatabaseTransferError:
        raise
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQL sequenceを検証できません。") from exc


def _validate_postgresql_sequences_on_connection(connection) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    seen_tables: set[tuple[str, str]] = set()
    auto_field_types = (models.AutoField, models.BigAutoField, models.SmallAutoField)
    try:
        with connection.cursor() as cursor:
            for model in apps.get_models(include_auto_created=True):
                if not model._meta.managed or model._meta.proxy:
                    continue
                primary_key = model._meta.pk
                if not isinstance(primary_key, auto_field_types):
                    continue
                table_key = (model._meta.db_table, primary_key.column)
                if table_key in seen_tables:
                    continue
                seen_tables.add(table_key)
                cursor.execute(
                    sql.SQL("SELECT MAX({}) FROM {}").format(
                        sql.Identifier(primary_key.column),
                        sql.Identifier(model._meta.db_table),
                    )
                )
                raw_maximum = cursor.fetchone()[0]
                maximum = int(raw_maximum) if raw_maximum is not None else None
                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)",
                    (model._meta.db_table, primary_key.column),
                )
                sequence_name = cursor.fetchone()[0]
                if not sequence_name:
                    raise DatabaseTransferError(
                        f"AutoField sequenceがありません: {model._meta.label_lower}"
                    )
                cursor.execute(
                    "SELECT n.nspname, c.relname, s.seqincrement "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_sequence s ON s.seqrelid = c.oid "
                    "WHERE c.oid = %s::regclass",
                    (sequence_name,),
                )
                sequence_row = cursor.fetchone()
                if sequence_row is None:
                    raise DatabaseTransferError(
                        f"AutoField sequence定義を読めません: {model._meta.label_lower}"
                    )
                sequence_schema, sequence_relation, raw_increment = sequence_row
                increment = int(raw_increment)
                if increment <= 0:
                    raise DatabaseTransferError(
                        f"AutoField sequenceの増分が正ではありません: {model._meta.label_lower}"
                    )
                cursor.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}.{}").format(
                        sql.Identifier(str(sequence_schema)),
                        sql.Identifier(str(sequence_relation)),
                    )
                )
                last_value, is_called = cursor.fetchone()
                next_value = int(last_value) + increment if is_called else int(last_value)
                if maximum is not None and next_value <= maximum:
                    raise DatabaseTransferError(
                        f"AutoField sequenceが既存PKより進んでいません: {model._meta.label_lower}"
                    )
                checks.append(
                    {
                        "model": model._meta.label_lower,
                        "table": model._meta.db_table,
                        "column": primary_key.column,
                        "sequence": str(sequence_name),
                        "maximum_primary_key": maximum,
                        "next_value": next_value,
                    }
                )
    except DatabaseTransferError:
        raise
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQL sequenceを検証できません。") from exc
    return checks


def _migration_summary(migrations: set[tuple[str, str]]) -> dict[str, object]:
    lines = [f"{app}.{name}" for app, name in sorted(migrations)]
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    return {"count": len(lines), "sha256": digest}


def _read_target_cluster_information(admin_connection) -> dict[str, object]:
    try:
        with admin_connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            server_version = str(cursor.fetchone()[0])
            cursor.execute("SHOW server_version_num")
            server_version_number = int(cursor.fetchone()[0])
            cursor.execute("SELECT current_database()")
            admin_database = str(cursor.fetchone()[0])
    except Exception as exc:
        raise DatabaseTransferError("target PostgreSQL cluster情報を確認できません。") from exc
    return {
        "server_version": server_version,
        "server_version_number": server_version_number,
        "admin_database": admin_database,
    }


def _build_postgresql_transfer_manifest(
    *,
    backup_run: DatabaseBackupRun,
    verification_run: DatabaseBackupVerificationRun,
    target_database_name: str,
    completion_marker_path: Path,
    primary_database: _OwnedDatabase,
    source_snapshot: shared.PrivateFileSnapshot,
    source_identity: shared.RuntimeIdentitySnapshot,
    source_migrations: set[tuple[str, str]],
    source_fingerprints: dict[str, dict[str, object]],
    expected_target_fingerprints: dict[str, dict[str, object]],
    source_metadata_fingerprints: dict[str, dict[str, object]],
    safety_changes: list[dict[str, object]],
    source_checks: dict[str, object],
    primary_validation: dict[str, object],
    verification_validation: dict[str, object],
    final_primary_sequence_checks: list[dict[str, object]],
    final_primary_schema_inventory: dict[str, list[str]],
    target_dump_snapshot: shared.PrivateFileSnapshot,
    target: PostgreSQLCloneTarget,
    cluster_information: dict[str, object],
    transferred_object_count: int,
) -> dict[str, object]:
    return {
        "transfer_format_version": POSTGRESQL_TRANSFER_FORMAT_VERSION,
        "created_at": timezone.localtime(timezone.now()).isoformat(),
        "source_engine": "sqlite",
        "target_engine": "postgresql",
        "source_backup_run_id": backup_run.id,
        "source_backup_file_name": backup_run.backup_file_name,
        "source_backup_file_size": source_snapshot.size,
        "source_backup_sha256": source_snapshot.sha256,
        "source_verification_run_id": verification_run.id,
        "source_verification_finished_at": (
            verification_run.finished_at.isoformat() if verification_run.finished_at else ""
        ),
        "target_database_name": target_database_name,
        "completion_marker_file_name": completion_marker_path.name,
        "publication_protocol": "manifest-plus-completion-marker-v1",
        "target_database_oid": primary_database.oid,
        "target_database_owner": target.runtime.database_user,
        "target_database_encoding": "UTF8",
        "target_database_comment_token": primary_database.token,
        "target_connections_allowed": False,
        "target_public_connect_allowed": False,
        "target_public_temporary_allowed": False,
        "target_host": target.runtime.database_host,
        "target_port": target.runtime.database_port,
        "target_cluster": cluster_information,
        "transferred_object_count": transferred_object_count,
        "runtime_identity": {
            "installation_id": source_identity.installation_id,
            "runtime_kind": source_identity.runtime_kind,
            "created_at": source_identity.created_at.isoformat(),
            "updated_at": source_identity.updated_at.isoformat(),
            "preserved_from_source": True,
        },
        "excluded_models": shared.EXCLUDED_MODEL_REASONS,
        "source_excluded_session_count": source_checks["session_count"],
        "regenerated_models": sorted(shared.REGENERATED_MODEL_LABELS),
        "migration": _migration_summary(source_migrations),
        "source_model_fingerprints": source_fingerprints,
        "expected_target_model_fingerprints": expected_target_fingerprints,
        "source_regenerated_metadata_fingerprints": source_metadata_fingerprints,
        "staged_clone_safety_changes": safety_changes,
        "source_sqlite_checks": source_checks,
        "primary_postgresql_checks": primary_validation,
        "restored_postgresql_checks": verification_validation,
        "final_primary_sequence_checks": final_primary_sequence_checks,
        "final_primary_schema_inventory": final_primary_schema_inventory,
        "primary_write_guard": {
            "all_non_system_tables_locked_in_share_mode": True,
            "unexpected_connections_terminated_before_freeze": True,
            "frozen_before_write_guard_release": True,
        },
        "target_self_backup": {
            "format": "pg_dump-custom",
            "size": target_dump_snapshot.size,
            "sha256": target_dump_snapshot.sha256,
            "restored_into_second_temporary_database": True,
        },
        "primary_keys_preserved": True,
        "activation_required": True,
        "production_configuration_changed": False,
    }


def _assert_frozen_database(
    admin_connection,
    *,
    database: _OwnedDatabase,
    expected_owner: str,
) -> None:
    state = _read_database_state(admin_connection, database.name)
    if (
        state is None
        or state.oid != database.oid
        or state.comment != database.token
        or state.owner != expected_owner
        or state.encoding != "UTF8"
        or state.connections_allowed
        or state.public_connect_allowed
        or state.public_temporary_allowed
    ):
        raise DatabaseTransferError(
            "公開済みPostgreSQLクローンが期待した凍結状態ではありません。"
        )


def _publish_postgresql_manifest(
    admin_connection,
    *,
    database: _OwnedDatabase,
    expected_owner: str,
    temp_manifest_path: Path,
    manifest_snapshot: shared.PrivateFileSnapshot,
    manifest_path: Path,
    completion_marker_path: Path,
) -> None:
    temp_completion_marker_path = completion_marker_path.with_name(
        f".{completion_marker_path.name}.{uuid.uuid4().hex}.part"
    )
    published = False
    try:
        completion_payload = {
            "completion_marker_version": POSTGRESQL_COMPLETION_MARKER_VERSION,
            "database_name": database.name,
            "database_oid": database.oid,
            "database_comment_token": database.token,
            "manifest_file_name": manifest_path.name,
            "manifest_size": manifest_snapshot.size,
            "manifest_sha256": manifest_snapshot.sha256,
            "connections_allowed": False,
            "public_connect_allowed": False,
            "public_temporary_allowed": False,
        }
        shared._write_private_json_file(
            temp_completion_marker_path,
            completion_payload,
        )
        completion_snapshot = shared._capture_private_file_snapshot(
            temp_completion_marker_path
        )
        _assert_frozen_database(
            admin_connection,
            database=database,
            expected_owner=expected_owner,
        )
        shared._assert_private_file_matches_snapshot(
            temp_manifest_path,
            manifest_snapshot,
        )
        if any(
            path.exists() or path.is_symlink()
            for path in (manifest_path, completion_marker_path)
        ):
            raise DatabaseTransferError(
                "manifest公開直前に同名fileまたは完了印が作成されたため、"
                "上書きせず停止しました。"
            )
        os.link(temp_manifest_path, manifest_path)
        shared._assert_private_file_matches_snapshot(manifest_path, manifest_snapshot)
        shared._remove_owned_file(temp_manifest_path)
        shared._fsync_directory(manifest_path.parent)
        shared._assert_private_file_matches_snapshot(manifest_path, manifest_snapshot)
        _assert_frozen_database(
            admin_connection,
            database=database,
            expected_owner=expected_owner,
        )
        shared._assert_private_file_matches_snapshot(
            temp_completion_marker_path,
            completion_snapshot,
        )
        if completion_marker_path.exists() or completion_marker_path.is_symlink():
            raise DatabaseTransferError(
                "完了印の公開直前に同名fileが作成されたため、上書きせず停止しました。"
            )
        # This hard link is the final completion action. There are deliberately
        # no required fallible checks after it: a visible, valid marker means
        # the frozen DB and manifest were both revalidated immediately before.
        os.link(temp_completion_marker_path, completion_marker_path)
        published = True
        shared._best_effort_remove_owned_file(temp_completion_marker_path)
        try:
            shared._fsync_directory(completion_marker_path.parent)
        except OSError:
            pass
    except FileExistsError as exc:
        raise DatabaseTransferError(
            "manifestまたは完了印の公開直前に同名fileが作成されたため、"
            "上書きせず停止しました。"
        ) from exc
    except OSError as exc:
        raise DatabaseTransferError(
            "PostgreSQL移送manifestを原子的に公開できませんでした。"
        ) from exc
    finally:
        if not published:
            shared._best_effort_remove_owned_file(temp_manifest_path)
            shared._best_effort_remove_owned_file(temp_completion_marker_path)
    if not published:
        raise DatabaseTransferError("PostgreSQL移送manifestの公開を完了できませんでした。")
