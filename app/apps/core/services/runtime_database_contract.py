from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.core.models import (
    DatabaseBackupRun,
    DatabaseBackupVerificationRun,
    DatabaseRuntimeIdentity,
)

from . import backup, backup_migration_archive, backup_restore_contract

DATABASE_CONTRACT_SCHEMA_VERSION = 1
CONNECTION_TARGET_FINGERPRINT_VERSION = 2
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class RuntimeDatabaseContractError(RuntimeError):
    """Raised when the current product database is unsafe to bind to an instance."""


def capture_product_database_contract(
    *,
    backup_run_id: int,
    expected_postgresql_major: int,
    database_connection=None,
) -> dict[str, object]:
    """Return an aggregate-only activation contract for the current product DB.

    The database portion is inspected inside a PostgreSQL repeatable-read, read-only
    transaction. The returned mapping deliberately excludes database names, hosts,
    users, paths, filenames, credentials, error messages, and application row counts.
    """

    if isinstance(backup_run_id, bool) or not isinstance(backup_run_id, int):
        raise RuntimeDatabaseContractError("backup run IDは正の整数で指定してください。")
    if backup_run_id <= 0:
        raise RuntimeDatabaseContractError("backup run IDは正の整数で指定してください。")
    if (
        isinstance(expected_postgresql_major, bool)
        or not isinstance(expected_postgresql_major, int)
        or not 10 <= expected_postgresql_major <= 99
    ):
        raise RuntimeDatabaseContractError(
            "期待するPostgreSQL majorは10から99の整数で指定してください。"
        )

    database_connection = database_connection or connection
    _assert_postgresql_runtime(database_connection)
    if database_connection.in_atomic_block:
        raise RuntimeDatabaseContractError(
            "DB契約検証は既存transactionの外側で実行してください。"
        )

    try:
        with transaction.atomic(using=database_connection.alias):
            _enforce_read_only_transaction(database_connection)
            _assert_no_other_database_client_sessions(database_connection)
            return _capture_contract_in_transaction(
                database_connection=database_connection,
                backup_run_id=backup_run_id,
                expected_postgresql_major=expected_postgresql_major,
            )
    except RuntimeDatabaseContractError:
        raise
    except DatabaseError as exc:
        raise RuntimeDatabaseContractError(
            "製品DB契約を読み取り専用で確認できません。"
        ) from exc


def _capture_contract_in_transaction(
    *,
    database_connection,
    backup_run_id: int,
    expected_postgresql_major: int,
) -> dict[str, object]:
    identity = _read_product_identity(database_connection)
    postgresql_major = _read_postgresql_major(database_connection)
    if postgresql_major != expected_postgresql_major:
        raise RuntimeDatabaseContractError(
            "PostgreSQL majorが期待値と一致しません: "
            f"expected={expected_postgresql_major}, actual={postgresql_major}."
        )
    # Seal the concrete database object and server endpoint separately from the
    # logical restore contract. Logical restores and clones retain the installation
    # ID and contract, so both values are required for an activation identity.
    connection_target_sha256 = connection_target_fingerprint_sha256(
        database_connection
    )

    migration_rows = _read_applied_migrations(database_connection)
    pending_migration_count = _pending_migration_count(database_connection)
    if pending_migration_count:
        raise RuntimeDatabaseContractError(
            "未適用migrationがあるためDB契約を確定できません: "
            f"count={pending_migration_count}."
        )

    try:
        current_contract = backup_restore_contract.build_restore_contract(
            database_engine="postgresql",
            database_version=str(postgresql_major),
            database_version_scope="server_major",
            installation_id=identity["installation_id"],
            runtime_kind=identity["runtime_kind"],
            migration_rows=migration_rows,
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise RuntimeDatabaseContractError("現在の製品DB契約が不正です。") from exc

    backup_run = _read_backup_run(
        backup_run_id,
        using=database_connection.alias,
    )
    _assert_latest_successful_postgresql_backup(
        backup_run,
        using=database_connection.alias,
    )
    backup_sha256 = _validated_backup_metadata(backup_run)
    verification = _read_latest_verification(
        backup_run,
        using=database_connection.alias,
    )
    restored_contract = _validated_restore_contract(verification)
    if restored_contract != current_contract:
        raise RuntimeDatabaseContractError(
            "現在のDBとテスト復元済みbackupのDB契約が一致しません。"
        )
    database_contract_sha256 = backup_restore_contract.canonical_json_sha256(
        current_contract
    )

    artifact_size, manifest_sha256 = _validate_backup_files(backup_run)
    migration_inventory = current_contract["applied_migrations"]
    return {
        "schema_version": DATABASE_CONTRACT_SCHEMA_VERSION,
        "read_only": True,
        "database": {
            "engine": "postgresql",
            "postgresql_major": postgresql_major,
        },
        "runtime_identity": identity,
        "migrations": {
            "count": migration_inventory["count"],
            "sha256": migration_inventory["sha256"],
            "pending_count": 0,
        },
        "database_contract_sha256": database_contract_sha256,
        "connection_target_sha256": connection_target_sha256,
        "backup": {
            "run_id": backup_run.pk,
            "finished_at": backup_run.finished_at.isoformat(),
            "artifact_size": artifact_size,
            "artifact_sha256": backup_sha256,
            "manifest_sha256": manifest_sha256,
        },
        "verification": {
            "run_id": verification.pk,
            "finished_at": verification.finished_at.isoformat(),
            "summary_sha256": backup_restore_contract.canonical_json_sha256(
                verification.verification_summary
            ),
        },
    }


def _assert_postgresql_runtime(database_connection) -> None:
    configured_engine = getattr(settings, "TEMPLEDB_DATABASE_ENGINE", "")
    if configured_engine != "postgresql" or database_connection.vendor != "postgresql":
        raise RuntimeDatabaseContractError(
            "DB契約検証は現在接続中のPostgreSQL製品DBだけで実行できます。"
        )


def _enforce_read_only_transaction(database_connection) -> None:
    try:
        with database_connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
    except DatabaseError as exc:
        raise RuntimeDatabaseContractError(
            "PostgreSQLの読み取り専用transactionを開始できません。"
        ) from exc


def _assert_no_other_database_client_sessions(database_connection) -> None:
    try:
        with database_connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() "
                "AND backend_type = 'client backend'"
            )
            row = cursor.fetchone()
        other_session_count = int(row[0]) if row else -1
    except (DatabaseError, TypeError, ValueError, IndexError) as exc:
        raise RuntimeDatabaseContractError(
            "同一DBのclient session数を読み取り専用で確認できません。"
        ) from exc
    if other_session_count < 0:
        raise RuntimeDatabaseContractError(
            "同一DBのclient session数を読み取り専用で確認できません。"
        )
    if other_session_count:
        raise RuntimeDatabaseContractError(
            "同一DBに自分以外のclient sessionがあるためDB契約を確定できません: "
            f"count={other_session_count}."
        )


def _read_product_identity(database_connection) -> dict[str, str]:
    rows = list(
        DatabaseRuntimeIdentity.objects.using(database_connection.alias)
        .order_by("singleton_key")
        .values_list("singleton_key", "installation_id", "runtime_kind")[:2]
    )
    if len(rows) != 1 or rows[0][0] != 1:
        raise RuntimeDatabaseContractError(
            "製品DBのruntime identityが一意に存在しません。"
        )
    _singleton_key, raw_installation_id, runtime_kind = rows[0]
    try:
        installation_id = uuid.UUID(str(raw_installation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeDatabaseContractError(
            "製品DBのinstallation IDが不正です。"
        ) from exc
    if installation_id.int == 0 or runtime_kind != "product":
        raise RuntimeDatabaseContractError(
            "接続中DBは有効な製品DBではありません。"
        )
    return {
        "installation_id": str(installation_id),
        "runtime_kind": "product",
    }


def _read_postgresql_major(database_connection) -> int:
    try:
        with database_connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            row = cursor.fetchone()
        server_version_num = int(row[0]) if row else 0
    except (DatabaseError, TypeError, ValueError, IndexError) as exc:
        raise RuntimeDatabaseContractError(
            "PostgreSQL server versionを確認できません。"
        ) from exc
    major = server_version_num // 10_000
    if not 10 <= major <= 99:
        raise RuntimeDatabaseContractError(
            "PostgreSQL server versionの形式が不正です。"
        )
    return major


def connection_target_fingerprint_sha256(database_connection) -> str:
    """Hash the exact PostgreSQL database object and endpoint without exposing it."""

    try:
        with database_connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), database_oid.oid, "
                "COALESCE(inet_server_addr()::text, ''), "
                "COALESCE(inet_server_port()::text, ''), "
                "current_setting('port'), "
                "control.system_identifier::text "
                "FROM pg_database AS database_oid "
                "CROSS JOIN pg_control_system() AS control "
                "WHERE database_oid.datname = current_database()"
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        raise RuntimeDatabaseContractError(
            "PostgreSQL接続先fingerprintを読み取り専用で確認できません。"
        ) from exc
    if not isinstance(row, (tuple, list)) or len(row) != 6:
        raise RuntimeDatabaseContractError(
            "PostgreSQL接続先fingerprintを読み取り専用で確認できません。"
        )

    database_name = _private_fingerprint_text(
        row[0],
        allow_empty=False,
        max_length=256,
    )
    try:
        database_oid = int(row[1])
    except (TypeError, ValueError) as exc:
        raise RuntimeDatabaseContractError(
            "PostgreSQL接続先fingerprintを読み取り専用で確認できません。"
        ) from exc
    if database_oid <= 0:
        raise RuntimeDatabaseContractError(
            "PostgreSQL接続先fingerprintを読み取り専用で確認できません。"
        )

    settings_dict = getattr(database_connection, "settings_dict", {})
    if not isinstance(settings_dict, dict):
        settings_dict = {}
    driver_info = getattr(
        getattr(database_connection, "connection", None),
        "info",
        None,
    )
    fingerprint_material = {
        "fingerprint_version": CONNECTION_TARGET_FINGERPRINT_VERSION,
        "postgresql_cluster": {
            "system_identifier": _private_fingerprint_text(
                row[5],
                allow_empty=False,
                max_length=32,
            ),
        },
        "database": {
            "name": database_name,
            "oid": database_oid,
        },
        "server_endpoint": {
            "reported_address": _private_fingerprint_text(
                row[2],
                allow_empty=True,
                max_length=256,
            ),
            "reported_port": _private_fingerprint_text(
                row[3],
                allow_empty=True,
                max_length=32,
            ),
            "postgresql_port": _private_fingerprint_text(
                row[4],
                allow_empty=False,
                max_length=32,
            ),
            "driver_host": _private_fingerprint_text(
                getattr(driver_info, "host", None),
                allow_empty=True,
                max_length=4096,
            ),
            "driver_port": _private_fingerprint_text(
                getattr(driver_info, "port", None),
                allow_empty=True,
                max_length=32,
            ),
            "configured_host": _private_fingerprint_text(
                settings_dict.get("HOST"),
                allow_empty=True,
                max_length=4096,
            ),
            "configured_port": _private_fingerprint_text(
                settings_dict.get("PORT"),
                allow_empty=True,
                max_length=32,
            ),
        },
    }
    return backup_restore_contract.canonical_json_sha256(fingerprint_material)


def _private_fingerprint_text(
    raw_value: object,
    *,
    allow_empty: bool,
    max_length: int,
) -> str:
    normalized = "" if raw_value is None else str(raw_value).strip()
    if (not allow_empty and not normalized) or len(normalized) > max_length:
        raise RuntimeDatabaseContractError(
            "PostgreSQL接続先fingerprintを読み取り専用で確認できません。"
        )
    return normalized


def _read_applied_migrations(database_connection) -> list[tuple[str, str]]:
    try:
        rows: Iterable[tuple[str, str]] = MigrationRecorder(
            database_connection
        ).applied_migrations().keys()
        return list(rows)
    except (DatabaseError, TypeError, ValueError) as exc:
        raise RuntimeDatabaseContractError(
            "適用済みmigrationを確認できません。"
        ) from exc


def read_applied_migrations(database_connection) -> list[tuple[str, str]]:
    """Return applied migration rows for a caller's existing DB snapshot."""

    return _read_applied_migrations(database_connection)


def _pending_migration_count(database_connection) -> int:
    try:
        executor = MigrationExecutor(database_connection)
        executor.loader.check_consistent_history(database_connection)
        targets = executor.loader.graph.leaf_nodes()
        return len(executor.migration_plan(targets))
    except Exception as exc:
        raise RuntimeDatabaseContractError(
            "migration planを読み取り専用で確認できません。"
        ) from exc


def _read_backup_run(backup_run_id: int, *, using: str) -> DatabaseBackupRun:
    try:
        return DatabaseBackupRun.objects.using(using).get(pk=backup_run_id)
    except DatabaseBackupRun.DoesNotExist as exc:
        raise RuntimeDatabaseContractError(
            "指定したbackup runが見つかりません。"
        ) from exc


def _assert_latest_successful_postgresql_backup(
    backup_run: DatabaseBackupRun,
    *,
    using: str,
) -> None:
    latest_run_id = (
        DatabaseBackupRun.objects.using(using)
        .filter(database_engine="postgresql", status="succeeded")
        .order_by("-started_at", "-id")
        .values_list("id", flat=True)
        .first()
    )
    if latest_run_id is None:
        raise RuntimeDatabaseContractError(
            "成功済みPostgreSQL backup runがありません。"
        )
    if backup_run.pk != latest_run_id:
        raise RuntimeDatabaseContractError(
            "指定したbackup runは最新の成功済みPostgreSQL backupではありません。"
        )


def _validated_backup_metadata(backup_run: DatabaseBackupRun) -> str:
    backup_sha256 = str(backup_run.backup_sha256 or "").strip().lower()
    if (
        backup_run.database_engine != "postgresql"
        or backup_run.status != "succeeded"
        or backup_run.finished_at is None
        or isinstance(backup_run.backup_file_size, bool)
        or not isinstance(backup_run.backup_file_size, int)
        or backup_run.backup_file_size <= 0
        or not _SHA256_RE.fullmatch(backup_sha256)
    ):
        raise RuntimeDatabaseContractError(
            "指定したbackup runの完了情報、sizeまたはSHA256が不正です。"
        )
    return backup_sha256


def _read_latest_verification(
    backup_run: DatabaseBackupRun,
    *,
    using: str,
) -> DatabaseBackupVerificationRun:
    verification = (
        DatabaseBackupVerificationRun.objects.using(using)
        .filter(backup_run_id=backup_run.pk)
        .order_by("-started_at", "-id")
        .first()
    )
    if (
        verification is None
        or verification.status != "succeeded"
        or verification.finished_at is None
        or not isinstance(verification.verification_summary, dict)
        or not verification.verification_summary
    ):
        raise RuntimeDatabaseContractError(
            "指定したbackup runの最新テスト復元が成功・完了していません。"
        )
    return verification


def _validated_restore_contract(
    verification: DatabaseBackupVerificationRun,
) -> dict[str, object]:
    try:
        return backup_restore_contract.validated_restore_contract(
            verification.verification_summary,
            expected_database_engine="postgresql",
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise RuntimeDatabaseContractError(
            "最新テスト復元に有効な製品DB契約がありません。"
        ) from exc


def _validate_backup_files(backup_run: DatabaseBackupRun) -> tuple[int, str]:
    try:
        artifact_path = backup.validate_backup_artifact(backup_run)
        _manifest_path, manifest_sha256 = (
            backup_migration_archive._validate_backup_manifest_for_bundle(
                backup,
                backup_run,
                artifact_path,
            )
        )
        revalidated_path = backup.validate_backup_artifact(backup_run)
        if revalidated_path != artifact_path:
            raise RuntimeDatabaseContractError(
                "検証中にbackup artifactの参照先が変化しました。"
            )
        artifact_size = revalidated_path.stat().st_size
    except RuntimeDatabaseContractError:
        raise
    except (backup.BackupServiceError, OSError) as exc:
        raise RuntimeDatabaseContractError(
            "backup artifactまたはmanifestのsize・SHA256を検証できません。"
        ) from exc
    return artifact_size, manifest_sha256


__all__ = [
    "CONNECTION_TARGET_FINGERPRINT_VERSION",
    "DATABASE_CONTRACT_SCHEMA_VERSION",
    "RuntimeDatabaseContractError",
    "capture_product_database_contract",
    "connection_target_fingerprint_sha256",
    "read_applied_migrations",
]
