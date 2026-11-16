from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from apps.core.models import (
    DatabaseBackupRun,
    DatabaseBackupVerificationRun,
    DatabaseRuntimeIdentity,
)
from config.runtime_paths import BASE_DIR

from . import backup, backup_execution

TRANSFER_FORMAT_VERSION = 1
TRANSFER_DATABASE_PREFIX = "templedb_transfer_"
MAX_MANIFEST_BYTES = 1024 * 1024

# Every managed model must remain explicitly classified. This prevents a future model from
# silently disappearing from an engine transfer or being copied without a design decision.
TRANSFERRED_MODEL_LABELS = frozenset(
    {
        "admin.logentry",
        "auth.group",
        "auth.user",
        "core.databasebackuprun",
        "core.databasebackupsetting",
        "core.databasebackupverificationrun",
        "core.googlecalendarsyncsetting",
        "core.templeidentitysetting",
        "imports.annualmembershipfeechecksheetscan",
        "imports.annualmembershipfeepayment",
        "imports.annualmembershipfeepostalscan",
        "imports.annualmembershipfeesetting",
        "imports.deceasedprofile",
        "imports.district",
        "imports.districtmembersheetstate",
        "imports.exportsnapshot",
        "imports.googlecalendarsyncbinding",
        "imports.handdeliveryreviewresolution",
        "imports.household",
        "imports.householdprofile",
        "imports.importbatch",
        "imports.importissue",
        "imports.legacysource",
        "imports.memorialnoticetemplate",
        "imports.memotag",
        "imports.memotagassignment",
        "imports.offeringpayment",
        "imports.person",
        "imports.postalreviewresolution",
        "imports.recordeditlog",
        "imports.recordfieldchange",
        "imports.serviceschedule",
        "imports.sourceoperationlog",
        "imports.visitnote",
    }
)
REGENERATED_MODEL_LABELS = frozenset(
    {
        "auth.permission",
        "contenttypes.contenttype",
    }
)
SEPARATELY_TRANSFERRED_MODEL_LABELS = frozenset({"core.databaseruntimeidentity"})
EXCLUDED_MODEL_REASONS = {
    "sessions.session": "Active login sessions are intentionally invalidated after an engine transfer.",
}
GENERIC_FOREIGN_KEY_CONTRACTS = frozenset(
    {("imports.memotagassignment", "content_type", "object_id")}
)


class DatabaseTransferError(backup.BackupServiceError):
    pass


@dataclass(frozen=True)
class RuntimeIdentitySnapshot:
    installation_id: str
    runtime_kind: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PrivateFileSnapshot:
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class GenericForeignKeyValidationSpec:
    model_label: str
    table_name: str
    content_type_column: str
    object_id_column: str


@dataclass(frozen=True)
class DatabaseTransferResult:
    sqlite_path: Path
    manifest_path: Path
    sqlite_sha256: str
    sqlite_size: int
    transferred_object_count: int
    source_backup_run_id: int
    source_verification_run_id: int


def create_product_sqlite_clone_from_postgresql_backup(
    *,
    backup_run: DatabaseBackupRun,
    output_path: str | Path,
) -> DatabaseTransferResult:
    """Create and fully verify a product SQLite clone without changing the live runtime."""

    if backup.current_database_engine() != "postgresql" or not backup.is_postgresql_configured():
        raise DatabaseTransferError(
            "PostgreSQL製品DBから実行した場合だけSQLiteクローンを作成できます。"
        )
    if backup_run.database_engine != "postgresql":
        raise DatabaseTransferError("PostgreSQLバックアップを指定してください。")
    if backup_run.status != "succeeded":
        raise DatabaseTransferError("成功したバックアップだけをSQLiteへ移送できます。")

    verification_run = _require_latest_successful_verification(backup_run)

    target_path, manifest_path = validate_sqlite_clone_output_path(output_path)
    assert_database_transfer_model_classification()
    live_identity = _read_live_runtime_identity()

    lock_token = None
    try:
        lock_token = backup_execution._acquire_database_maintenance_lock(
            operation_kind="database_transfer",
            record_id=backup_run.id,
        )
        backup_run.refresh_from_db()
        if backup_run.database_engine != "postgresql" or backup_run.status != "succeeded":
            raise DatabaseTransferError("lock取得後にバックアップ状態が変更されました。")
        verification_run = _require_latest_successful_verification(backup_run)
        backup_file_path = backup.validate_backup_artifact(backup_run)
        _validate_postgresql_backup_manifest(backup_run, backup_file_path)
        return _create_clone_under_maintenance_lock(
            backup_run=backup_run,
            verification_run=verification_run,
            backup_file_path=backup_file_path,
            target_path=target_path,
            manifest_path=manifest_path,
            live_identity=live_identity,
        )
    finally:
        backup_execution._release_backup_lock(lock_token)


def _require_latest_successful_verification(
    backup_run: DatabaseBackupRun,
) -> DatabaseBackupVerificationRun:
    verification_run = backup.latest_verification_for_backup_run(backup_run)
    if (
        verification_run is None
        or verification_run.status != "succeeded"
        or verification_run.finished_at is None
    ):
        raise DatabaseTransferError(
            "同じバックアップに対する最新のテスト復元が成功している必要があります。"
        )
    return verification_run


def validate_sqlite_clone_output_path(output_path: str | Path) -> tuple[Path, Path]:
    raw_path = Path(output_path).expanduser()
    if not raw_path.is_absolute():
        raise DatabaseTransferError("SQLite出力先は絶対パスで指定してください。")
    if raw_path.suffix.lower() != ".sqlite3":
        raise DatabaseTransferError("SQLite出力ファイル名は .sqlite3 で終わる必要があります。")
    if raw_path.name in {"", ".", ".."}:
        raise DatabaseTransferError("SQLite出力ファイル名が不正です。")

    parent = raw_path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise DatabaseTransferError("SQLite出力先の親ディレクトリが利用できません。")
    resolved_parent = parent.resolve(strict=True)
    if parent != resolved_parent:
        raise DatabaseTransferError(
            "SQLite出力先の親ディレクトリにシンボリックリンクは使用できません。"
        )
    target_path = resolved_parent / raw_path.name
    manifest_path = target_path.with_name(f"{target_path.name}.transfer.json")

    protected_paths = [
        target_path,
        manifest_path,
        Path(f"{target_path}-wal"),
        Path(f"{target_path}-shm"),
        Path(f"{target_path}-journal"),
    ]
    if any(path.exists() or path.is_symlink() for path in protected_paths):
        raise DatabaseTransferError(
            "SQLite出力先または付随ファイルがすでに存在します。上書きは行いません。"
        )
    orphan_patterns = (
        f".{target_path.name}.*.part",
        f".{manifest_path.name}.*.part",
    )
    if any(next(resolved_parent.glob(pattern), None) for pattern in orphan_patterns):
        raise DatabaseTransferError(
            "同じ出力先に前回未完了の一時ファイルがあります。自動削除せず停止します。"
        )
    if not os.access(resolved_parent, os.W_OK):
        raise DatabaseTransferError("SQLite出力先へ書き込めません。")
    return target_path, manifest_path


def assert_database_transfer_model_classification() -> None:
    managed_models = {
        model._meta.label_lower
        for model in apps.get_models(include_auto_created=False)
        if model._meta.managed and not model._meta.proxy
    }
    classified_models = (
        TRANSFERRED_MODEL_LABELS
        | REGENERATED_MODEL_LABELS
        | SEPARATELY_TRANSFERRED_MODEL_LABELS
        | set(EXCLUDED_MODEL_REASONS)
    )
    missing = sorted(managed_models - classified_models)
    stale = sorted(classified_models - managed_models)
    if missing or stale:
        details = []
        if missing:
            details.append(f"未分類: {', '.join(missing)}")
        if stale:
            details.append(f"存在しない分類: {', '.join(stale)}")
        raise DatabaseTransferError("DB移送モデル分類が現行schemaと一致しません。" + " / ".join(details))

    generic_foreign_keys = {
        (model._meta.label_lower, field.ct_field, field.fk_field)
        for model in apps.get_models(include_auto_created=False)
        if model._meta.managed and not model._meta.proxy
        for field in model._meta.private_fields
        if isinstance(field, GenericForeignKey)
    }
    if generic_foreign_keys != GENERIC_FOREIGN_KEY_CONTRACTS:
        missing_contracts = sorted(generic_foreign_keys - GENERIC_FOREIGN_KEY_CONTRACTS)
        stale_contracts = sorted(GENERIC_FOREIGN_KEY_CONTRACTS - generic_foreign_keys)
        raise DatabaseTransferError(
            "DB移送GenericForeignKey分類が現行schemaと一致しません。"
            f" 未分類: {missing_contracts} / 存在しない分類: {stale_contracts}"
        )


def generic_foreign_key_validation_specs() -> tuple[GenericForeignKeyValidationSpec, ...]:
    specs = []
    for model_label, content_type_field, object_id_field in sorted(
        GENERIC_FOREIGN_KEY_CONTRACTS
    ):
        model = apps.get_model(model_label)
        if model is None or not model._meta.managed or model._meta.proxy:
            raise DatabaseTransferError(
                f"GenericForeignKey検査modelを解決できません: {model_label}"
            )
        specs.append(
            GenericForeignKeyValidationSpec(
                model_label=model_label,
                table_name=model._meta.db_table,
                content_type_column=model._meta.get_field(content_type_field).column,
                object_id_column=model._meta.get_field(object_id_field).column,
            )
        )
    return tuple(specs)


def fixture_fingerprints(
    fixture_path: Path,
    *,
    expected_model_labels: frozenset[str],
) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseTransferError("移送用fixtureを安全に読み取れませんでした。") from exc
    if not isinstance(payload, list):
        raise DatabaseTransferError("移送用fixtureの形式が不正です。")

    rows_by_model: dict[str, list[str]] = defaultdict(list)
    for raw_row in payload:
        if not isinstance(raw_row, dict):
            raise DatabaseTransferError("移送用fixtureに不正な行があります。")
        model_label = str(raw_row.get("model", "")).lower()
        if model_label not in expected_model_labels:
            raise DatabaseTransferError(
                f"移送用fixtureに未許可モデルが含まれています: {model_label or '<blank>'}"
            )
        model = apps.get_model(model_label)
        raw_fields = raw_row.get("fields")
        if model is None or not isinstance(raw_fields, dict):
            raise DatabaseTransferError("移送用fixtureのmodelまたはfieldsが不正です。")
        normalized_fields = {}
        for field_name, value in raw_fields.items():
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist as exc:
                raise DatabaseTransferError(
                    f"移送用fixtureに現行schema外のfieldがあります: {model_label}.{field_name}"
                ) from exc
            normalized_fields[field_name] = _normalize_fixture_value(field, value)
        normalized_row = {
            "model": model_label,
            "pk": raw_row.get("pk"),
            "fields": normalized_fields,
        }
        rows_by_model[model_label].append(
            json.dumps(
                normalized_row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    fingerprints = {}
    for model_label in sorted(expected_model_labels):
        row_lines = sorted(rows_by_model.get(model_label, []))
        digest = hashlib.sha256()
        for row_line in row_lines:
            digest.update(row_line.encode("utf-8"))
            digest.update(b"\n")
        fingerprints[model_label] = {
            "count": len(row_lines),
            "sha256": digest.hexdigest(),
        }
    return fingerprints


def _prepare_staged_clone_fixture(source_path: Path, output_path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseTransferError("移送元fixtureを安全なclone用に準備できませんでした。") from exc
    if not isinstance(payload, list):
        raise DatabaseTransferError("移送元fixtureの形式が不正です。")

    policies = {
        "core.databasebackupsetting": {
            "daily_enabled": "clone検証中の自動バックアップを停止するため",
            "weekly_verification_enabled": "clone検証中の自動テスト復元を停止するため",
        },
        "core.googlecalendarsyncsetting": {
            "enabled": "clone検証中の外部Google Calendar更新を停止するため",
        },
    }
    safety_changes: list[dict[str, object]] = []
    for model_label, field_reasons in policies.items():
        matching_rows = [row for row in payload if row.get("model") == model_label]
        if len(matching_rows) != 1:
            raise DatabaseTransferError(
                f"安全なclone化に必要なsingletonが一意ではありません: {model_label}"
            )
        fields = matching_rows[0].get("fields")
        if not isinstance(fields, dict):
            raise DatabaseTransferError(f"安全なclone化対象のfieldsが不正です: {model_label}")
        for field_name, reason in field_reasons.items():
            source_value = fields.get(field_name)
            if not isinstance(source_value, bool):
                raise DatabaseTransferError(
                    f"安全なclone化対象のboolean fieldが不正です: {model_label}.{field_name}"
                )
            fields[field_name] = False
            safety_changes.append(
                {
                    "model": model_label,
                    "field": field_name,
                    "source_value": source_value,
                    "target_value": False,
                    "changed": source_value is not False,
                    "reason": reason,
                }
            )
    _write_private_json_file(output_path, payload)
    return safety_changes


def _validate_regenerated_metadata(
    source_path: Path,
    target_path: Path,
) -> dict[str, object]:
    source_records = _regenerated_metadata_natural_records(source_path)
    target_records = _regenerated_metadata_natural_records(target_path)
    summary: dict[str, object] = {}
    for model_label in sorted(REGENERATED_MODEL_LABELS):
        source_model_records = source_records[model_label]
        target_model_records = target_records[model_label]
        missing_in_source = sorted(set(target_model_records) - set(source_model_records))
        source_only = set(source_model_records) - set(target_model_records)
        changed_shared = sorted(
            key
            for key in set(target_model_records) & set(source_model_records)
            if target_model_records[key] != source_model_records[key]
        )
        if missing_in_source or changed_shared:
            raise DatabaseTransferError(
                f"再生成metadataの現行自然キーを移送元で確認できません: {model_label}"
            )
        if model_label == "auth.permission":
            stale_content_types = set(
                source_records["contenttypes.contenttype"]
            ) - set(target_records["contenttypes.contenttype"])
            current_content_type_permissions = sorted(
                permission_key
                for permission_key in source_only
                if _permission_content_type_key(permission_key) not in stale_content_types
            )
            if current_content_type_permissions:
                raise DatabaseTransferError(
                    "現行content typeに属するsource-only permissionがあるため、"
                    "metadataを安全に再生成できません。"
                )
        summary[model_label] = {
            "source_count": len(source_model_records),
            "target_count": len(target_model_records),
            "source_only_stale_count": len(source_only),
            "target_natural_keys_verified": True,
        }
    return summary


def _permission_content_type_key(permission_key: str) -> str:
    try:
        content_type, _codename = json.loads(permission_key)
    except (TypeError, ValueError) as exc:
        raise DatabaseTransferError("permissionの自然キーが不正です。") from exc
    if (
        not isinstance(content_type, list)
        or len(content_type) != 2
        or not all(isinstance(value, str) and value for value in content_type)
    ):
        raise DatabaseTransferError("permissionのcontent type自然キーが不正です。")
    return json.dumps(
        content_type,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _regenerated_metadata_natural_records(
    fixture_path: Path,
) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseTransferError("再生成metadata fixtureを読めませんでした。") from exc
    if not isinstance(payload, list):
        raise DatabaseTransferError("再生成metadata fixtureの形式が不正です。")
    records: dict[str, dict[str, str]] = {
        model_label: {} for model_label in REGENERATED_MODEL_LABELS
    }
    for row in payload:
        if not isinstance(row, dict):
            raise DatabaseTransferError("再生成metadata fixtureに不正な行があります。")
        model_label = str(row.get("model", "")).lower()
        fields = row.get("fields")
        if model_label not in records or not isinstance(fields, dict):
            raise DatabaseTransferError("再生成metadata fixtureに未許可modelがあります。")
        if model_label == "contenttypes.contenttype":
            natural_key = json.dumps(
                [fields.get("app_label"), fields.get("model")],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            semantic_fields = {
                "app_label": fields.get("app_label"),
                "model": fields.get("model"),
            }
        elif model_label == "auth.permission":
            content_type = fields.get("content_type")
            natural_key = json.dumps(
                [content_type, fields.get("codename")],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            semantic_fields = {
                "content_type": content_type,
                "codename": fields.get("codename"),
                "name": fields.get("name"),
            }
        else:  # pragma: no cover - guarded by the explicit constant above
            raise DatabaseTransferError("再生成metadata modelの分類が不正です。")
        if natural_key in records[model_label]:
            raise DatabaseTransferError("再生成metadataの自然キーが重複しています。")
        records[model_label][natural_key] = json.dumps(
            semantic_fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return records


def _normalize_fixture_value(field: models.Field, value):
    if value is None:
        return None
    if isinstance(field, models.DateTimeField) and isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is None:
            raise DatabaseTransferError(f"DateTime値を解釈できません: {field.model._meta.label}.{field.name}")
        if timezone.is_naive(parsed):
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField):
        parsed_date = parse_date(value) if isinstance(value, str) else None
        if parsed_date is None:
            raise DatabaseTransferError(f"Date値を解釈できません: {field.model._meta.label}.{field.name}")
        return parsed_date.isoformat()
    if isinstance(field, models.TimeField) and isinstance(value, str):
        parsed_time = parse_time(value)
        if parsed_time is None:
            raise DatabaseTransferError(f"Time値を解釈できません: {field.model._meta.label}.{field.name}")
        return parsed_time.isoformat(timespec="microseconds")
    if field.many_to_many and isinstance(value, list):
        normalized_items = [_normalize_json_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return _normalize_json_value(value)


def _normalize_json_value(value):
    if isinstance(value, dict):
        return {key: _normalize_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    return value


def _create_clone_under_maintenance_lock(
    *,
    backup_run: DatabaseBackupRun,
    verification_run: DatabaseBackupVerificationRun,
    backup_file_path: Path,
    target_path: Path,
    manifest_path: Path,
    live_identity: RuntimeIdentitySnapshot,
) -> DatabaseTransferResult:
    admin_config = backup.get_postgres_admin_config()
    transfer_database_name = _build_transfer_database_name(backup_run.id)
    database_cleanup_armed = False
    operation_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    prepared_result: dict[str, object] | None = None

    with tempfile.TemporaryDirectory(prefix="templedb-db-transfer-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        os.chmod(temp_dir, 0o700)
        source_fixture = temp_dir / "source.json"
        staged_fixture = temp_dir / "staged-target.json"
        source_metadata_fixture = temp_dir / "source-metadata.json"
        target_fixture = temp_dir / "target.json"
        target_metadata_fixture = temp_dir / "target-metadata.json"
        part_path = target_path.with_name(
            f".{target_path.name}.{uuid.uuid4().hex}.part"
        )
        temp_manifest_path = manifest_path.with_name(
            f".{manifest_path.name}.{uuid.uuid4().hex}.part"
        )

        try:
            _ensure_no_existing_transfer_databases(admin_config)
            # createdb itself can be interrupted after the server creates the DB but
            # before subprocess.run returns.  Arm the idempotent dropdb --if-exists
            # cleanup first so that window cannot leave an unreported transfer DB.
            database_cleanup_armed = True
            backup._run_command(
                backup.build_createdb_command(admin_config, transfer_database_name),
                env=backup.build_postgres_env(admin_config),
            )
            backup._run_command(
                backup.build_pg_restore_command(
                    admin_config,
                    transfer_database_name,
                    backup_file_path,
                ),
                env=backup.build_postgres_env(admin_config),
            )
            _revalidate_backup_artifact_after_restore(backup_run, backup_file_path)

            source_env = _postgres_transfer_environment(admin_config, transfer_database_name)
            _run_manage_py(
                ["migrate", "--noinput", "--verbosity", "0"],
                env=source_env,
                stage="一時PostgreSQLのmigration",
            )
            _remove_embedded_running_backup_run(
                admin_config,
                transfer_database_name,
                backup_run.id,
            )
            source_identity = _read_postgresql_runtime_identity(
                admin_config,
                transfer_database_name,
            )
            _assert_source_identity_matches_live(source_identity, live_identity)
            source_migrations = _read_postgresql_migrations(
                admin_config,
                transfer_database_name,
            )
            source_session_count = _read_postgresql_table_count(
                admin_config,
                transfer_database_name,
                "django_session",
            )

            _dump_fixture(source_fixture, source_env, TRANSFERRED_MODEL_LABELS)
            safety_changes = _prepare_staged_clone_fixture(
                source_fixture,
                staged_fixture,
            )
            _dump_fixture(
                source_metadata_fixture,
                source_env,
                REGENERATED_MODEL_LABELS,
            )
            source_fingerprints = fixture_fingerprints(
                source_fixture,
                expected_model_labels=TRANSFERRED_MODEL_LABELS,
            )
            expected_target_fingerprints = fixture_fingerprints(
                staged_fixture,
                expected_model_labels=TRANSFERRED_MODEL_LABELS,
            )
            source_metadata_fingerprints = fixture_fingerprints(
                source_metadata_fixture,
                expected_model_labels=REGENERATED_MODEL_LABELS,
            )

            _create_private_empty_file(part_path)
            target_initialization_env = _sqlite_transfer_environment(
                part_path,
                initialization=True,
            )
            _run_manage_py(
                ["migrate", "--noinput", "--verbosity", "0"],
                env=target_initialization_env,
                stage="SQLiteの初期migration",
            )
            os.chmod(part_path, 0o600)
            target_env = _sqlite_transfer_environment(part_path, initialization=False)
            _run_manage_py(
                ["loaddata", str(staged_fixture), "--verbosity", "0"],
                env=target_env,
                stage="SQLiteへのデータ投入",
            )
            _write_sqlite_runtime_identity(part_path, source_identity)

            _dump_fixture(target_fixture, target_env, TRANSFERRED_MODEL_LABELS)
            _dump_fixture(
                target_metadata_fixture,
                target_env,
                REGENERATED_MODEL_LABELS,
            )
            target_fingerprints = fixture_fingerprints(
                target_fixture,
                expected_model_labels=TRANSFERRED_MODEL_LABELS,
            )
            target_metadata_fingerprints = fixture_fingerprints(
                target_metadata_fixture,
                expected_model_labels=REGENERATED_MODEL_LABELS,
            )
            _assert_fingerprints_match(
                expected_target_fingerprints,
                target_fingerprints,
                category="業務データ",
            )
            regenerated_metadata_summary = _validate_regenerated_metadata(
                source_metadata_fixture,
                target_metadata_fixture,
            )

            target_migrations = _read_sqlite_migrations(part_path)
            if source_migrations != target_migrations:
                raise DatabaseTransferError(
                    "PostgreSQLとSQLiteの適用migration集合が一致しません。"
                )
            sqlite_checks = _validate_sqlite_clone(
                part_path,
                expected_identity=source_identity,
            )
            if sqlite_checks["session_count"] != 0:
                raise DatabaseTransferError("SQLiteクローンにlogin sessionが残っています。")
            _run_manage_py(
                ["migrate", "--check", "--verbosity", "0"],
                env=target_env,
                stage="SQLiteのmigration確認",
            )
            _run_manage_py(
                ["check"],
                env=target_env,
                stage="SQLiteのDjango system check",
            )

            _fsync_file(part_path)
            part_snapshot = _capture_private_file_snapshot(part_path)
            sqlite_size = part_snapshot.size
            sqlite_sha256 = part_snapshot.sha256
            transferred_object_count = sum(
                int(item["count"]) for item in source_fingerprints.values()
            )
            manifest = _build_transfer_manifest(
                backup_run=backup_run,
                verification_run=verification_run,
                target_path=target_path,
                sqlite_size=sqlite_size,
                sqlite_sha256=sqlite_sha256,
                transferred_object_count=transferred_object_count,
                source_identity=source_identity,
                source_session_count=source_session_count,
                migrations=source_migrations,
                source_model_fingerprints=source_fingerprints,
                target_model_fingerprints=target_fingerprints,
                source_metadata_fingerprints=source_metadata_fingerprints,
                target_metadata_fingerprints=target_metadata_fingerprints,
                regenerated_metadata_summary=regenerated_metadata_summary,
                safety_changes=safety_changes,
                sqlite_checks=sqlite_checks,
            )
            _write_private_json_file(temp_manifest_path, manifest)
            manifest_snapshot = _capture_private_file_snapshot(temp_manifest_path)
            prepared_result = {
                "part_path": part_path,
                "part_snapshot": part_snapshot,
                "temp_manifest_path": temp_manifest_path,
                "manifest_snapshot": manifest_snapshot,
                "sqlite_size": sqlite_size,
                "sqlite_sha256": sqlite_sha256,
                "transferred_object_count": transferred_object_count,
            }
        except BaseException as exc:
            operation_error = exc
            _best_effort_remove_owned_sqlite_artifacts(part_path)
            _best_effort_remove_owned_file(temp_manifest_path)
        finally:
            if database_cleanup_armed:
                try:
                    backup._run_command(
                        backup.build_dropdb_command(admin_config, transfer_database_name),
                        env=backup.build_postgres_env(admin_config),
                    )
                except BaseException as exc:
                    cleanup_error = exc

        if operation_error is not None or cleanup_error is not None:
            _best_effort_remove_owned_sqlite_artifacts(part_path)
            _best_effort_remove_owned_file(temp_manifest_path)
            if cleanup_error is not None:
                message = (
                    f"一時PostgreSQL DB {transfer_database_name} を削除できなかったため、"
                    "SQLiteクローンを公開しませんでした。"
                )
                if operation_error is not None:
                    message += " 移送処理自体にも失敗があります。"
                raise DatabaseTransferError(message) from cleanup_error
            if isinstance(operation_error, DatabaseTransferError):
                raise operation_error
            if isinstance(operation_error, Exception):
                raise DatabaseTransferError(
                    "PostgreSQLからSQLiteへの移送に失敗しました。"
                ) from operation_error
            if operation_error is not None:
                raise operation_error
            raise DatabaseTransferError("PostgreSQLからSQLiteへの移送に失敗しました。")

        if prepared_result is None:
            raise DatabaseTransferError("SQLiteクローンの準備結果を確認できませんでした。")

        _publish_clone_without_overwrite(
            part_path=prepared_result["part_path"],
            part_snapshot=prepared_result["part_snapshot"],
            target_path=target_path,
            temp_manifest_path=prepared_result["temp_manifest_path"],
            manifest_snapshot=prepared_result["manifest_snapshot"],
            manifest_path=manifest_path,
        )
        return DatabaseTransferResult(
            sqlite_path=target_path,
            manifest_path=manifest_path,
            sqlite_sha256=str(prepared_result["sqlite_sha256"]),
            sqlite_size=int(prepared_result["sqlite_size"]),
            transferred_object_count=int(prepared_result["transferred_object_count"]),
            source_backup_run_id=backup_run.id,
            source_verification_run_id=verification_run.id,
        )


def _read_live_runtime_identity() -> RuntimeIdentitySnapshot:
    try:
        identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
    except DatabaseRuntimeIdentity.DoesNotExist as exc:
        raise DatabaseTransferError("現在の製品DBにDB identityがありません。") from exc
    if identity.runtime_kind != "product":
        raise DatabaseTransferError("製品DB identityではないため移送できません。")
    return RuntimeIdentitySnapshot(
        installation_id=str(identity.installation_id),
        runtime_kind=identity.runtime_kind,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )


def _assert_source_identity_matches_live(
    source_identity: RuntimeIdentitySnapshot,
    live_identity: RuntimeIdentitySnapshot,
) -> None:
    if source_identity.runtime_kind != "product":
        raise DatabaseTransferError("バックアップは製品DBのものではありません。")
    if source_identity.installation_id != live_identity.installation_id:
        raise DatabaseTransferError(
            "バックアップのinstallation identityが現在の製品DBと一致しません。"
        )


def _validate_postgresql_backup_manifest(
    backup_run: DatabaseBackupRun,
    backup_file_path: Path,
) -> None:
    expected_sha256 = (backup_run.backup_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise DatabaseTransferError("PostgreSQLバックアップのSHA256記録が不正です。")
    manifest_path = Path((backup_run.manifest_file_path or "").strip())
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise DatabaseTransferError("PostgreSQLバックアップのmanifestが見つかりません。")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise DatabaseTransferError("PostgreSQLバックアップのmanifestが大きすぎます。")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseTransferError("PostgreSQLバックアップのmanifestを読めません。") from exc
    expected = {
        "backup_run_id": backup_run.id,
        "backup_file_name": backup_file_path.name,
        "backup_file_size": backup_file_path.stat().st_size,
        "backup_sha256": expected_sha256,
    }
    if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in expected.items()):
        raise DatabaseTransferError("PostgreSQLバックアップのmanifestが記録と一致しません。")


def _revalidate_backup_artifact_after_restore(
    backup_run: DatabaseBackupRun,
    backup_file_path: Path,
) -> None:
    try:
        actual_size = backup_file_path.stat().st_size
    except OSError as exc:
        raise DatabaseTransferError("復元後にバックアップファイルを再確認できません。") from exc
    expected_sha256 = (backup_run.backup_sha256 or "").strip().lower()
    if actual_size != backup_run.backup_file_size:
        raise DatabaseTransferError("復元中にバックアップファイルのサイズが変化しました。")
    if backup.calculate_sha256(backup_file_path).lower() != expected_sha256:
        raise DatabaseTransferError("復元中にバックアップファイルのSHA256が変化しました。")


def _build_transfer_database_name(backup_run_id: int) -> str:
    timestamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    database_name = f"{TRANSFER_DATABASE_PREFIX}{timestamp}_{backup_run_id}_{uuid.uuid4().hex[:8]}"
    if len(database_name) > 63 or not _is_safe_transfer_database_name(database_name):
        raise DatabaseTransferError("安全な一時PostgreSQL DB名を作成できませんでした。")
    return database_name


def _is_safe_transfer_database_name(database_name: str) -> bool:
    return bool(
        re.fullmatch(r"templedb_transfer_\d{8}_\d{6}_\d+_[0-9a-f]{8}", database_name)
    )


def _ensure_no_existing_transfer_databases(admin_config) -> None:
    connection_kwargs = _postgres_connection_kwargs(admin_config, admin_config.database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT datname FROM pg_database "
                    "WHERE left(datname, %s) = %s ORDER BY datname",
                    (len(TRANSFER_DATABASE_PREFIX), TRANSFER_DATABASE_PREFIX),
                )
                database_names = [str(row[0]) for row in cursor.fetchall()]
    except Exception as exc:
        raise DatabaseTransferError("一時PostgreSQL DBの残存確認に失敗しました。") from exc
    if database_names:
        raise DatabaseTransferError(
            "前回または別processの一時PostgreSQL DBが残っているため処理を停止しました: "
            + ", ".join(database_names)
        )


def _remove_embedded_running_backup_run(admin_config, database_name: str, run_id: int) -> None:
    connection_kwargs = _postgres_connection_kwargs(admin_config, database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, database_engine, backup_file_path, backup_sha256 "
                    "FROM core_databasebackuprun WHERE id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise DatabaseTransferError(
                        "バックアップ内に作成中runの監査行がありません。"
                    )
                status, engine, file_path, sha256 = row
                if (
                    status != "running"
                    or engine != "postgresql"
                    or str(file_path or "")
                    or str(sha256 or "")
                ):
                    raise DatabaseTransferError(
                        "バックアップ内の作成中runが想定状態と一致しません。"
                    )
                cursor.execute(
                    "DELETE FROM core_databasebackuprun WHERE id = %s",
                    (run_id,),
                )
                if cursor.rowcount != 1:
                    raise DatabaseTransferError(
                        "バックアップ内の作成中runを一意に除外できませんでした。"
                    )
    except DatabaseTransferError:
        raise
    except Exception as exc:
        raise DatabaseTransferError("バックアップ内の作成中runを整理できませんでした。") from exc


def _read_postgresql_runtime_identity(admin_config, database_name: str) -> RuntimeIdentitySnapshot:
    connection_kwargs = _postgres_connection_kwargs(admin_config, database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT installation_id, runtime_kind, created_at, updated_at "
                    "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise DatabaseTransferError("復元PostgreSQLのDB identityを読めませんでした。") from exc
    if len(rows) != 1:
        raise DatabaseTransferError("復元PostgreSQLのDB identityが一意ではありません。")
    installation_id, runtime_kind, created_at, updated_at = rows[0]
    return RuntimeIdentitySnapshot(
        installation_id=str(installation_id),
        runtime_kind=str(runtime_kind),
        created_at=created_at,
        updated_at=updated_at,
    )


def _read_postgresql_migrations(admin_config, database_name: str) -> set[tuple[str, str]]:
    connection_kwargs = _postgres_connection_kwargs(admin_config, database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT app, name FROM django_migrations")
                return {(str(app), str(name)) for app, name in cursor.fetchall()}
    except Exception as exc:
        raise DatabaseTransferError("復元PostgreSQLのmigration記録を読めませんでした。") from exc


def _read_postgresql_table_count(admin_config, database_name: str, table_name: str) -> int:
    if table_name != "django_session":
        raise DatabaseTransferError("許可されていないPostgreSQL table countです。")
    connection_kwargs = _postgres_connection_kwargs(admin_config, database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM django_session")
                return int(cursor.fetchone()[0])
    except Exception as exc:
        raise DatabaseTransferError("復元PostgreSQLのsession件数を読めませんでした。") from exc


def _postgres_connection_kwargs(admin_config, database_name: str) -> dict[str, object]:
    values = {
        "dbname": database_name,
        "user": admin_config.database_user or None,
        "password": admin_config.database_password or None,
        "host": admin_config.database_host or None,
        "port": admin_config.database_port or None,
    }
    return {key: value for key, value in values.items() if value not in {None, ""}}


def _postgres_transfer_environment(admin_config, database_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "TEMPLEDB_DATABASE_ENGINE": "postgresql",
            "TEMPLEDB_DEMO_MODE": "0",
            "DATABASE_NAME": database_name,
            "DATABASE_USER": admin_config.database_user,
            "DATABASE_PASSWORD": admin_config.database_password,
            "DATABASE_PORT": admin_config.database_port,
            "DATABASE_HOST": _postgres_django_host(admin_config),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    env.pop("TEMPLEDB_SQLITE_DB_PATH", None)
    return env


def _postgres_django_host(admin_config) -> str:
    if admin_config.database_host:
        return admin_config.database_host
    connection_kwargs = _postgres_connection_kwargs(admin_config, admin_config.database_name)
    try:
        with psycopg.connect(**connection_kwargs) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SHOW unix_socket_directories")
                raw_directories = str(cursor.fetchone()[0])
    except Exception as exc:
        raise DatabaseTransferError("PostgreSQL socket directoryを確認できませんでした。") from exc
    for raw_directory in raw_directories.split(","):
        directory = raw_directory.strip()
        if directory.startswith("/"):
            return directory
    raise DatabaseTransferError("Djangoから使えるPostgreSQL socket directoryがありません。")


def _sqlite_transfer_environment(sqlite_path: Path, *, initialization: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": (
                "config.settings_product_sqlite_initialization"
                if initialization
                else "config.settings"
            ),
            "TEMPLEDB_DATABASE_ENGINE": "sqlite",
            "TEMPLEDB_DEMO_MODE": "0",
            "TEMPLEDB_SQLITE_DB_PATH": str(sqlite_path),
            "DATABASE_HOST": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    for key in (
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_PORT",
    ):
        env.pop(key, None)
    return env


def _dump_fixture(
    output_path: Path,
    env: dict[str, str],
    model_labels: frozenset[str],
) -> None:
    command = [
        "dumpdata",
        *sorted(model_labels),
        "--all",
        "--natural-foreign",
        "--verbosity",
        "0",
    ]
    _run_manage_py_to_private_file(
        command,
        env=env,
        output_path=output_path,
        stage="移送用fixture作成",
    )


def _run_manage_py(
    arguments: list[str],
    *,
    env: dict[str, str],
    stage: str,
) -> None:
    completed = subprocess.run(
        [_current_python_executable(), "manage.py", *arguments],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DatabaseTransferError(f"{stage}に失敗しました（終了code {completed.returncode}）。")


def _run_manage_py_to_private_file(
    arguments: list[str],
    *,
    env: dict[str, str],
    output_path: Path,
    stage: str,
) -> None:
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output_file:
            completed = subprocess.run(
                [_current_python_executable(), "manage.py", *arguments],
                cwd=BASE_DIR,
                env=env,
                stdout=output_file,
                stderr=subprocess.PIPE,
                check=False,
            )
            output_file.flush()
            os.fsync(output_file.fileno())
    except Exception:
        _remove_owned_file(output_path)
        raise
    if completed.returncode != 0:
        _remove_owned_file(output_path)
        raise DatabaseTransferError(f"{stage}に失敗しました（終了code {completed.returncode}）。")


def _current_python_executable() -> str:
    python_path = Path(sys.executable)
    if (
        not python_path.is_absolute()
        or not python_path.is_file()
        or not os.access(python_path, os.X_OK)
    ):
        raise DatabaseTransferError(
            "現在のTempleDB Python実行環境を再利用できません。"
        )
    return str(python_path)


def _create_private_empty_file(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def _write_sqlite_runtime_identity(
    sqlite_path: Path,
    identity: RuntimeIdentitySnapshot,
) -> None:
    try:
        with sqlite3.connect(sqlite_path) as connection:
            cursor = connection.execute(
                "UPDATE core_databaseruntimeidentity "
                "SET installation_id = ?, runtime_kind = ?, created_at = ?, updated_at = ? "
                "WHERE singleton_key = 1",
                (
                    identity.installation_id,
                    identity.runtime_kind,
                    identity.created_at.isoformat(),
                    identity.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise DatabaseTransferError("SQLiteのDB identityを一意に更新できませんでした。")
    except DatabaseTransferError:
        raise
    except sqlite3.Error as exc:
        raise DatabaseTransferError("SQLiteのDB identityを更新できませんでした。") from exc


def _read_sqlite_migrations(sqlite_path: Path) -> set[tuple[str, str]]:
    try:
        with sqlite3.connect(sqlite_path) as connection:
            rows = connection.execute("SELECT app, name FROM django_migrations").fetchall()
    except sqlite3.Error as exc:
        raise DatabaseTransferError("SQLiteのmigration記録を読めませんでした。") from exc
    return {(str(app), str(name)) for app, name in rows}


def _validate_sqlite_clone(
    sqlite_path: Path,
    *,
    expected_identity: RuntimeIdentitySnapshot,
) -> dict[str, object]:
    try:
        with sqlite3.connect(sqlite_path) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchall()
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            identity_rows = connection.execute(
                "SELECT installation_id, runtime_kind "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            ).fetchall()
            session_count = int(
                connection.execute("SELECT COUNT(*) FROM django_session").fetchone()[0]
            )
            broken_generic_relations = _count_broken_sqlite_generic_relations(connection)
    except sqlite3.Error as exc:
        raise DatabaseTransferError("完成SQLiteを検証できませんでした。") from exc
    if quick_check != [("ok",)]:
        raise DatabaseTransferError("完成SQLiteのintegrity checkに失敗しました。")
    if foreign_key_errors:
        raise DatabaseTransferError("完成SQLiteに外部キー不整合があります。")
    expected_identity_row = [(expected_identity.installation_id, expected_identity.runtime_kind)]
    if identity_rows != expected_identity_row:
        raise DatabaseTransferError("完成SQLiteのDB identityが移送元と一致しません。")
    if broken_generic_relations:
        raise DatabaseTransferError("完成SQLiteにGenericForeignKey不整合があります。")
    return {
        "quick_check": "ok",
        "foreign_key_error_count": 0,
        "broken_generic_relation_count": 0,
        "session_count": session_count,
    }


def _count_broken_sqlite_generic_relations(connection: sqlite3.Connection) -> int:
    content_types = {
        int(content_type_id): (str(app_label), str(model_name))
        for content_type_id, app_label, model_name in connection.execute(
            "SELECT id, app_label, model FROM django_content_type"
        ).fetchall()
    }
    broken = 0
    for spec in generic_foreign_key_validation_specs():
        source_table = _quote_sqlite_identifier(spec.table_name)
        content_type_column = _quote_sqlite_identifier(spec.content_type_column)
        object_id_column = _quote_sqlite_identifier(spec.object_id_column)
        rows = connection.execute(
            f"SELECT {content_type_column}, {object_id_column} FROM {source_table}"
        ).fetchall()
        for content_type_id, object_id in rows:
            natural_key = content_types.get(int(content_type_id))
            model = apps.get_model(*natural_key) if natural_key else None
            if model is None or not model._meta.managed:
                broken += 1
                continue
            table_name = _quote_sqlite_identifier(model._meta.db_table)
            primary_key_column = _quote_sqlite_identifier(model._meta.pk.column)
            found = connection.execute(
                f"SELECT 1 FROM {table_name} WHERE {primary_key_column} = ? LIMIT 1",
                (object_id,),
            ).fetchone()
            if found is None:
                broken += 1
    return broken


def _quote_sqlite_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _assert_fingerprints_match(
    source: dict[str, dict[str, object]],
    target: dict[str, dict[str, object]],
    *,
    category: str,
) -> None:
    if source == target:
        return
    mismatched_models = sorted(
        model_label
        for model_label in set(source) | set(target)
        if source.get(model_label) != target.get(model_label)
    )
    raise DatabaseTransferError(
        f"{category}の照合に失敗しました。対象model: {', '.join(mismatched_models)}"
    )


def _build_transfer_manifest(
    *,
    backup_run: DatabaseBackupRun,
    verification_run: DatabaseBackupVerificationRun,
    target_path: Path,
    sqlite_size: int,
    sqlite_sha256: str,
    transferred_object_count: int,
    source_identity: RuntimeIdentitySnapshot,
    source_session_count: int,
    migrations: set[tuple[str, str]],
    source_model_fingerprints: dict[str, dict[str, object]],
    target_model_fingerprints: dict[str, dict[str, object]],
    source_metadata_fingerprints: dict[str, dict[str, object]],
    target_metadata_fingerprints: dict[str, dict[str, object]],
    regenerated_metadata_summary: dict[str, object],
    safety_changes: list[dict[str, object]],
    sqlite_checks: dict[str, object],
) -> dict[str, object]:
    migration_lines = [f"{app}.{name}" for app, name in sorted(migrations)]
    migration_sha256 = hashlib.sha256(
        ("\n".join(migration_lines) + "\n").encode("utf-8")
    ).hexdigest()
    return {
        "transfer_format_version": TRANSFER_FORMAT_VERSION,
        "created_at": timezone.localtime(timezone.now()).isoformat(),
        "source_engine": "postgresql",
        "target_engine": "sqlite",
        "source_backup_run_id": backup_run.id,
        "source_backup_file_name": backup_run.backup_file_name,
        "source_backup_sha256": backup_run.backup_sha256,
        "source_verification_run_id": verification_run.id,
        "source_verification_finished_at": (
            verification_run.finished_at.isoformat() if verification_run.finished_at else ""
        ),
        "snapshot_excluded_backup_run_id": backup_run.id,
        "target_file_name": target_path.name,
        "target_file_size": sqlite_size,
        "target_sha256": sqlite_sha256,
        "transferred_object_count": transferred_object_count,
        "runtime_identity": {
            "installation_id": source_identity.installation_id,
            "runtime_kind": source_identity.runtime_kind,
            "preserved_from_source": True,
        },
        "excluded_models": EXCLUDED_MODEL_REASONS,
        "source_excluded_session_count": source_session_count,
        "regenerated_models": sorted(REGENERATED_MODEL_LABELS),
        "migration_count": len(migrations),
        "migration_sha256": migration_sha256,
        "source_model_fingerprints": source_model_fingerprints,
        "target_model_fingerprints": target_model_fingerprints,
        "source_regenerated_metadata_fingerprints": source_metadata_fingerprints,
        "target_regenerated_metadata_fingerprints": target_metadata_fingerprints,
        "regenerated_metadata_summary": regenerated_metadata_summary,
        "staged_clone_safety_changes": safety_changes,
        "primary_keys_preserved": True,
        "sqlite_checks": sqlite_checks,
        "activation_required": True,
        "production_configuration_changed": False,
    }


def _write_private_json_file(path: Path, payload: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2, sort_keys=True)
            output_file.write("\n")
            output_file.flush()
            os.fsync(output_file.fileno())
    except Exception:
        _remove_owned_file(path)
        raise


def _publish_clone_without_overwrite(
    *,
    part_path: Path,
    part_snapshot: PrivateFileSnapshot,
    target_path: Path,
    temp_manifest_path: Path,
    manifest_snapshot: PrivateFileSnapshot,
    manifest_path: Path,
) -> None:
    publish_completed = False
    try:
        _assert_private_file_matches_snapshot(part_path, part_snapshot)
        _assert_private_file_matches_snapshot(temp_manifest_path, manifest_snapshot)
        _ensure_final_output_paths_absent(target_path, manifest_path)
        os.link(part_path, target_path)
        _assert_private_file_matches_snapshot(target_path, part_snapshot)
        _ensure_no_sqlite_sidecars(target_path)
        _remove_owned_file(part_path)
        _fsync_directory(target_path.parent)
        _assert_private_file_matches_snapshot(target_path, part_snapshot)
        # The manifest is the completion marker.  Publish it only after the DB
        # file itself is durable and unchanged.
        os.link(temp_manifest_path, manifest_path)
        _assert_private_file_matches_snapshot(manifest_path, manifest_snapshot)
        _remove_owned_file(temp_manifest_path)
        _fsync_directory(target_path.parent)
        _assert_private_file_matches_snapshot(target_path, part_snapshot)
        _assert_private_file_matches_snapshot(manifest_path, manifest_snapshot)
        publish_completed = True
    except FileExistsError as exc:
        raise DatabaseTransferError(
            "公開直前に出力先が作成されたため、上書きせず停止しました。"
        ) from exc
    except OSError as exc:
        raise DatabaseTransferError(
            "SQLiteクローンを原子的に公開できませんでした。"
        ) from exc
    finally:
        if not publish_completed:
            # Never unlink a predictable final path here.  Another process can
            # replace it between an identity check and unlink.  A DB without the
            # final manifest is deliberately left as an incomplete publication.
            _remove_owned_sqlite_artifacts(part_path)
            _remove_owned_file(temp_manifest_path)
    if not publish_completed:
        raise DatabaseTransferError("SQLiteクローンの公開を完了できませんでした。")


def _ensure_final_output_paths_absent(target_path: Path, manifest_path: Path) -> None:
    protected_paths = (
        target_path,
        manifest_path,
        Path(f"{target_path}-wal"),
        Path(f"{target_path}-shm"),
        Path(f"{target_path}-journal"),
    )
    if any(path.exists() or path.is_symlink() for path in protected_paths):
        raise DatabaseTransferError(
            "公開直前に出力先または付随ファイルが作成されたため停止しました。"
        )


def _ensure_no_sqlite_sidecars(sqlite_path: Path) -> None:
    sidecars = (
        Path(f"{sqlite_path}-wal"),
        Path(f"{sqlite_path}-shm"),
        Path(f"{sqlite_path}-journal"),
    )
    if any(path.exists() or path.is_symlink() for path in sidecars):
        raise DatabaseTransferError("公開先に予期しないSQLite sidecarがあります。")


def _capture_private_file_snapshot(path: Path) -> PrivateFileSnapshot:
    stat_result = _private_regular_file_stat(path)
    snapshot = PrivateFileSnapshot(
        device=stat_result.st_dev,
        inode=stat_result.st_ino,
        size=stat_result.st_size,
        sha256=backup.calculate_sha256(path),
    )
    _assert_private_file_matches_snapshot(path, snapshot)
    return snapshot


def _assert_private_file_matches_snapshot(
    path: Path,
    expected: PrivateFileSnapshot,
) -> None:
    stat_result = _private_regular_file_stat(path)
    if (
        stat_result.st_dev != expected.device
        or stat_result.st_ino != expected.inode
        or stat_result.st_size != expected.size
    ):
        raise DatabaseTransferError("移送中に検証済みfileが別のfileへ差し替えられました。")
    if backup.calculate_sha256(path) != expected.sha256:
        raise DatabaseTransferError("移送中に検証済みfileの内容が変更されました。")


def _private_regular_file_stat(path: Path) -> os.stat_result:
    stat_result = path.lstat()
    if not stat.S_ISREG(stat_result.st_mode):
        raise DatabaseTransferError("移送fileが通常fileではありません。")
    if stat.S_IMODE(stat_result.st_mode) != 0o600:
        raise DatabaseTransferError("移送fileの権限が0600ではありません。")
    return stat_result


def _fsync_file(path: Path) -> None:
    with path.open("rb") as input_file:
        os.fsync(input_file.fileno())


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _remove_owned_sqlite_artifacts(sqlite_path: Path) -> None:
    for path in (
        sqlite_path,
        Path(f"{sqlite_path}-wal"),
        Path(f"{sqlite_path}-shm"),
        Path(f"{sqlite_path}-journal"),
    ):
        _remove_owned_file(path)


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _best_effort_remove_owned_sqlite_artifacts(sqlite_path: Path) -> None:
    try:
        _remove_owned_sqlite_artifacts(sqlite_path)
    except OSError:
        pass


def _best_effort_remove_owned_file(path: Path) -> None:
    try:
        _remove_owned_file(path)
    except OSError:
        pass
