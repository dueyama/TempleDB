from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from django.conf import settings

from apps.core.models import (
    DatabaseBackupRun,
    DatabaseBackupVerificationRun,
    DatabaseRuntimeIdentity,
)
from config.runtime_paths import runtime_root

from . import backup_execution, backup_restore_contract

SQLITE_BACKUP_ENGINE = "sqlite"
SQLITE_MANIFEST_VERSION = 2
SQLITE_VERIFICATION_ROOT = runtime_root() / "backup_verification"
SQLITE_SUMMARY_TABLES = (
    "django_migrations",
    "auth_user",
    "imports_household",
    "imports_person",
    "imports_deceasedprofile",
)
_VERIFICATION_FILE_PATTERN = re.compile(r"templedb_verify_[0-9a-f]{12}_\d{8}_\d{6}_\d+\.sqlite3")


def _backup_module():
    # backup.py is the compatibility surface and imports this module from the
    # dispatcher.  Keep the import local so both modules can initialize safely.
    from . import backup

    return backup


def perform_sqlite_database_backup(
    *,
    trigger_kind: str,
    requested_by_label: str = "",
    now=None,
):
    runtime = _backup_module()
    _require_product_sqlite_runtime(runtime)
    if trigger_kind not in {"manual", "scheduled"}:
        raise runtime.BackupServiceError("バックアップの実行種別が不正です。")

    setting = runtime.get_or_create_backup_setting()
    configured_destination_path = runtime.effective_backup_destination_path(setting)
    if not configured_destination_path:
        raise runtime.BackupServiceError("バックアップ保存先がまだ設定されていません。")

    source_path = _product_sqlite_source_path(runtime)
    source_identity = _current_product_identity(runtime)
    started_at = now or runtime.timezone.now()
    run = DatabaseBackupRun.objects.create(
        setting=setting,
        database_engine=SQLITE_BACKUP_ENGINE,
        trigger_kind=trigger_kind,
        status="running",
        requested_by_label=(requested_by_label or "").strip(),
        database_name=source_path.name[:255],
        database_host="",
        destination_path=configured_destination_path,
        started_at=started_at,
    )

    lock_token = None
    temp_backup_path: Path | None = None
    temp_manifest_path: Path | None = None
    incomplete_artifact_path: Path | None = None
    artifacts_complete = False
    try:
        lock_token = runtime._acquire_backup_lock(run)
        destination_path = _validated_destination_path(configured_destination_path, runtime)
        timestamp_label = runtime.timezone.localtime(started_at).strftime("%Y%m%d_%H%M%S")
        installation_label = source_identity["installation_id"].replace("-", "")[:12]
        backup_file_name = f"templedb_{installation_label}_{timestamp_label}_run{run.id}.sqlite3"
        backup_file_path = destination_path / backup_file_name
        temp_backup_path = destination_path / f"{backup_file_name}.part"
        manifest_path = backup_file_path.with_suffix(".json")
        temp_manifest_path = destination_path / f"{manifest_path.name}.part"

        _validate_new_artifact_paths(
            source_path=source_path,
            artifact_path=backup_file_path,
            temp_artifact_path=temp_backup_path,
            manifest_path=manifest_path,
            temp_manifest_path=temp_manifest_path,
            runtime=runtime,
        )
        _create_secure_empty_file(temp_backup_path, runtime)
        _backup_live_sqlite_database(source_path, temp_backup_path, runtime)
        _exclude_in_progress_run_from_snapshot(temp_backup_path, run_id=run.id, runtime=runtime)
        _remove_transient_sqlite_sidecars(temp_backup_path, runtime)
        snapshot = _inspect_sqlite_database(temp_backup_path, runtime)
        if snapshot["identity"] != source_identity:
            raise runtime.BackupServiceError(
                "作成したSQLiteバックアップのDB識別情報が現在のDBと一致しません。"
            )

        _fsync_file(temp_backup_path)
        backup_file_size = temp_backup_path.stat().st_size
        backup_sha256 = _calculate_sha256(temp_backup_path)
        manifest = {
            "manifest_version": SQLITE_MANIFEST_VERSION,
            "backup_run_id": run.id,
            "created_at": runtime.timezone.localtime(started_at).isoformat(),
            "trigger_kind": trigger_kind,
            "database_engine": SQLITE_BACKUP_ENGINE,
            "database_name": str(source_path),
            "database_host": "",
            "backup_file_name": backup_file_name,
            "backup_file_path": str(backup_file_path),
            "backup_file_size": backup_file_size,
            "backup_sha256": backup_sha256,
            "database_identity": snapshot["identity"],
            "snapshot_excluded_backup_run_id": run.id,
            "verification_expectations": {
                "quick_check": "ok",
                "foreign_key_violation_count": 0,
                "table_counts": snapshot["table_counts"],
            },
        }
        _atomic_write_json(
            temp_path=temp_manifest_path,
            final_path=manifest_path,
            payload=manifest,
            runtime=runtime,
            defer_final_replace=True,
        )

        os.replace(temp_backup_path, backup_file_path)
        temp_backup_path = None
        incomplete_artifact_path = backup_file_path
        _fsync_directory(destination_path)
        os.replace(temp_manifest_path, manifest_path)
        temp_manifest_path = None
        _fsync_directory(destination_path)
        artifacts_complete = True
        incomplete_artifact_path = None

        run.status = "succeeded"
        run.backup_file_name = backup_file_name
        run.backup_file_path = str(backup_file_path)
        run.manifest_file_path = str(manifest_path)
        run.backup_file_size = backup_file_size
        run.backup_sha256 = backup_sha256
        run.error_message = ""
        run.finished_at = runtime.timezone.now()
        run.save(
            update_fields=[
                "status",
                "backup_file_name",
                "backup_file_path",
                "manifest_file_path",
                "backup_file_size",
                "backup_sha256",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        _update_setting_after_backup(setting, run, success=True, runtime=runtime)
    except Exception as exc:
        cleanup_errors = _cleanup_partial_files(
            (temp_backup_path, temp_manifest_path),
            protected_paths=(source_path,),
        )
        if not artifacts_complete and incomplete_artifact_path is not None:
            cleanup_errors.extend(
                _cleanup_incomplete_artifact(
                    incomplete_artifact_path,
                    destination_path=Path(configured_destination_path),
                    protected_paths=(source_path,),
                )
            )
        error_message = str(exc)
        if cleanup_errors:
            error_message = f"{error_message} / 未完了ファイルを削除できませんでした: " + "; ".join(
                cleanup_errors
            )
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = runtime.timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        _update_setting_after_backup(setting, run, success=False, runtime=runtime)
        if cleanup_errors:
            raise runtime.BackupServiceError(error_message) from exc
        raise
    else:
        backup_execution._run_backup_retention(
            setting,
            run,
            prune=lambda: _prune_old_sqlite_backup_artifacts(
                setting,
                destination_path=configured_destination_path,
                protected_source=source_path,
                runtime=runtime,
            ),
        )
        return run
    finally:
        runtime._release_backup_lock(lock_token)


def perform_sqlite_backup_verification(
    backup_run,
    *,
    requested_by_label: str = "",
    trigger_kind: str = "manual",
    verification_run=None,
    now=None,
):
    runtime = _backup_module()
    _require_product_sqlite_runtime(runtime)
    if getattr(backup_run, "database_engine", "") != SQLITE_BACKUP_ENGINE:
        raise runtime.BackupServiceError(
            "SQLiteで作成したバックアップだけをSQLiteへテスト復元できます。"
        )
    if trigger_kind not in {"manual", "scheduled"}:
        raise runtime.BackupServiceError("テスト復元の実行種別が不正です。")

    source_path = _product_sqlite_source_path(runtime)
    current_identity = _current_product_identity(runtime)
    verification_root = _validated_verification_root(runtime)

    requested_by = (requested_by_label or "").strip()
    if verification_run is None:
        started_at = now or runtime.timezone.now()
        verification = DatabaseBackupVerificationRun.objects.create(
            backup_run=backup_run,
            trigger_kind=trigger_kind,
            status="running",
            requested_by_label=requested_by,
            started_at=started_at,
        )
    else:
        verification = verification_run
        if verification.backup_run_id != backup_run.id:
            raise runtime.BackupServiceError("予約済みテスト復元と対象バックアップが一致しません。")
        if verification.status != "running":
            raise runtime.BackupServiceError("予約済みテスト復元は実行待ち状態ではありません。")
        started_at = verification.started_at
        trigger_kind = verification.trigger_kind
        if requested_by:
            verification.requested_by_label = requested_by

    installation_label = current_identity["installation_id"].replace("-", "")[:12]
    verification_file_name = runtime.timezone.localtime(started_at).strftime(
        f"templedb_verify_{installation_label}_%Y%m%d_%H%M%S"
    )
    verification_file_name = f"{verification_file_name}_{verification.id}.sqlite3"
    verification.verification_database_name = verification_file_name
    verification.save(
        update_fields=["requested_by_label", "verification_database_name", "updated_at"]
    )

    verification_path = verification_root / verification_file_name
    lock_token = None
    created_temp_file = False
    verification_summary: dict[str, object] = {}
    operation_error: Exception | None = None
    cleanup_error: Exception | None = None
    backup_file_path: Path | None = None
    try:
        lock_token = runtime._acquire_verification_lock(verification)
        _recover_stale_sqlite_verifications(verification, runtime)
        backup_file_path, manifest = _validated_sqlite_backup_artifact(
            backup_run,
            current_identity=current_identity,
            source_path=source_path,
            runtime=runtime,
        )
        _validate_verification_path(
            verification_path,
            verification_root=verification_root,
            protected_paths=(source_path, backup_file_path),
            runtime=runtime,
        )
        _create_secure_empty_file(verification_path, runtime)
        created_temp_file = True
        _copy_sqlite_database(backup_file_path, verification_path, runtime)
        restored = _inspect_sqlite_database(verification_path, runtime)
        _validate_restored_snapshot(
            restored,
            manifest=manifest,
            current_identity=current_identity,
            runtime=runtime,
        )
        verification_summary = {
            **restored["table_counts"],
            "quick_check": restored["quick_check"],
            "foreign_key_violation_count": restored["foreign_key_violation_count"],
            backup_restore_contract.RESTORE_CONTRACT_KEY: (
                backup_restore_contract.build_restore_contract(
                    database_engine=SQLITE_BACKUP_ENGINE,
                    database_version=sqlite3.sqlite_version,
                    database_version_scope="library",
                    installation_id=restored["identity"]["installation_id"],
                    runtime_kind=restored["identity"]["runtime_kind"],
                    migration_rows=restored["migration_rows"],
                )
            ),
        }
    except Exception as exc:
        operation_error = exc
    finally:
        if created_temp_file:
            try:
                _remove_verification_files(
                    verification_path,
                    verification_root=verification_root,
                    protected_paths=tuple(
                        path for path in (source_path, backup_file_path) if path is not None
                    ),
                    runtime=runtime,
                )
            except Exception as exc:
                cleanup_error = exc
        runtime._release_backup_lock(lock_token)

    if operation_error is not None or cleanup_error is not None:
        error_parts = []
        if operation_error is not None:
            error_parts.append(str(operation_error))
        if cleanup_error is not None:
            error_parts.append(
                f"一時検証SQLite {verification_file_name} を削除できませんでした: {cleanup_error}"
            )
        error_message = " / ".join(part for part in error_parts if part)
        verification.status = "failed"
        verification.verification_summary = {}
        verification.error_message = error_message
        verification.finished_at = runtime.timezone.now()
        verification.save(
            update_fields=[
                "status",
                "verification_summary",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        if cleanup_error is None and operation_error is not None:
            raise operation_error
        raise runtime.BackupServiceError(error_message) from (operation_error or cleanup_error)

    verification.status = "succeeded"
    verification.verification_summary = verification_summary
    verification.error_message = ""
    verification.finished_at = runtime.timezone.now()
    verification.save(
        update_fields=[
            "status",
            "verification_summary",
            "error_message",
            "finished_at",
            "updated_at",
        ]
    )
    return verification


def validate_sqlite_backup_artifact(backup_run) -> Path:
    """Fully revalidate a SQLite artifact without modifying any file or row."""

    runtime = _backup_module()
    _require_product_sqlite_runtime(runtime)
    if getattr(backup_run, "database_engine", "") != SQLITE_BACKUP_ENGINE:
        raise runtime.BackupServiceError("SQLiteで作成したバックアップではありません。")
    source_path = _product_sqlite_source_path(runtime)
    current_identity = _current_product_identity(runtime)
    backup_file_path, manifest = _validated_sqlite_backup_artifact(
        backup_run,
        current_identity=current_identity,
        source_path=source_path,
        runtime=runtime,
    )
    snapshot = _inspect_sqlite_database(backup_file_path, runtime)
    _validate_restored_snapshot(
        snapshot,
        manifest=manifest,
        current_identity=current_identity,
        runtime=runtime,
    )
    return backup_file_path


def _require_product_sqlite_runtime(runtime) -> None:
    engine = settings.DATABASES["default"]["ENGINE"]
    if engine != "django.db.backends.sqlite3" or not getattr(
        settings, "TEMPLEDB_PRODUCT_SQLITE_MODE", False
    ):
        raise runtime.BackupServiceError("本運用SQLite接続時のみSQLiteバックアップを利用できます。")
    if getattr(settings, "TEMPLEDB_DEMO_MODE", False):
        raise runtime.BackupServiceError("デモDBは本運用バックアップの対象にできません。")


def _product_sqlite_source_path(runtime) -> Path:
    raw_name = settings.DATABASES["default"].get("NAME")
    if not raw_name or str(raw_name) == ":memory:":
        raise runtime.BackupServiceError("本運用SQLiteのDBファイルが設定されていません。")
    source_path = Path(str(raw_name)).expanduser()
    if not source_path.is_absolute():
        raise runtime.BackupServiceError("本運用SQLiteのDBファイルは絶対パスが必要です。")
    if source_path.is_symlink():
        raise runtime.BackupServiceError(
            "本運用SQLiteのDBファイルにシンボリックリンクは使えません。"
        )
    if not source_path.is_file():
        raise runtime.BackupServiceError("本運用SQLiteのDBファイルが見つかりません。")
    return source_path


def _current_product_identity(runtime) -> dict[str, str]:
    try:
        identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
    except DatabaseRuntimeIdentity.DoesNotExist as exc:
        raise runtime.BackupServiceError("現在のDBにDB識別情報がありません。") from exc
    installation_id = _canonical_installation_id(identity.installation_id, runtime)
    if identity.runtime_kind != "product":
        raise runtime.BackupServiceError(
            f"現在のDBは製品DBではありません: runtime_kind={identity.runtime_kind!r}"
        )
    return {"installation_id": installation_id, "runtime_kind": "product"}


def _validated_destination_path(raw_path: str, runtime) -> Path:
    destination_path = Path((raw_path or "").strip()).expanduser()
    if not destination_path.exists() or not destination_path.is_dir():
        raise runtime.BackupServiceError(f"保存先が利用できません: {destination_path}")
    if destination_path.is_symlink():
        raise runtime.BackupServiceError(
            f"保存先にシンボリックリンクは使えません: {destination_path}"
        )
    if not os.access(destination_path, os.W_OK):
        raise runtime.BackupServiceError(f"保存先へ書き込めません: {destination_path}")
    return destination_path


def _validate_new_artifact_paths(
    *,
    source_path: Path,
    artifact_path: Path,
    temp_artifact_path: Path,
    manifest_path: Path,
    temp_manifest_path: Path,
    runtime,
) -> None:
    source_resolved = source_path.resolve()
    for path in (artifact_path, temp_artifact_path, manifest_path, temp_manifest_path):
        if path.resolve() == source_resolved:
            raise runtime.BackupServiceError(
                "バックアップ出力先を現在のSQLite DBファイルと同じ場所にはできません。"
            )
        if path.exists() or path.is_symlink():
            raise runtime.BackupServiceError(f"同名のバックアップ成果物が既にあります: {path}")


def _create_secure_empty_file(path: Path, runtime) -> None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    except OSError as exc:
        raise runtime.BackupServiceError(f"一時SQLiteファイルを作成できません: {path}") from exc
    else:
        os.close(descriptor)


def _backup_live_sqlite_database(
    source_path: Path,
    destination_path: Path,
    runtime,
) -> None:
    try:
        # Use a separate read-only connection so an unexpected caller-side
        # transaction cannot be copied halfway or deadlock its own connection.
        # SQLite's backup API still includes committed WAL content.
        with _connect_read_only(source_path) as source:
            with sqlite3.connect(destination_path, timeout=30) as destination:
                source.backup(destination)
                destination.commit()
                _make_sqlite_artifact_standalone(destination, runtime)
    except sqlite3.Error as exc:
        raise runtime.BackupServiceError("SQLiteバックアップの作成に失敗しました。") from exc


def _copy_sqlite_database(source_path: Path, destination_path: Path, runtime) -> None:
    try:
        with _connect_read_only(source_path) as source:
            with sqlite3.connect(destination_path, timeout=30) as destination:
                source.backup(destination)
                destination.commit()
                _make_sqlite_artifact_standalone(destination, runtime)
    except sqlite3.Error as exc:
        raise runtime.BackupServiceError("SQLiteバックアップの一時復元に失敗しました。") from exc


def _connect_read_only(path: Path) -> sqlite3.Connection:
    quoted_path = quote(str(path), safe="/")
    return sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True, timeout=30)


def _make_sqlite_artifact_standalone(connection: sqlite3.Connection, runtime) -> None:
    # The backup API copies the source header, including WAL journal mode.  A
    # portable backup must be readable without adjacent -wal/-shm sidecars.
    try:
        row = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
    except sqlite3.Error as exc:
        raise runtime.BackupServiceError(
            "SQLiteバックアップを単独ファイルとして確定できません。"
        ) from exc
    journal_mode = str(row[0]).lower() if row else ""
    if journal_mode != "delete":
        raise runtime.BackupServiceError(
            "SQLiteバックアップのjournal modeをDELETEへ確定できません。"
        )


def _exclude_in_progress_run_from_snapshot(path: Path, *, run_id: int, runtime) -> None:
    """Make the artifact represent the database just before this backup run.

    The live run remains ``running`` until every artifact has been finalized and
    becomes ``failed`` on any exception.  Its temporary control row must not be
    restored later as a permanently running backup that blocks the scheduler.
    """

    try:
        with sqlite3.connect(path, timeout=30) as connection:
            cursor = connection.execute(
                "DELETE FROM core_databasebackuprun "
                "WHERE id = ? AND database_engine = ? AND status = ?",
                (run_id, SQLITE_BACKUP_ENGINE, "running"),
            )
            if cursor.rowcount != 1:
                raise runtime.BackupServiceError(
                    "SQLiteスナップショットから作成中runを安全に除外できません。"
                )
            connection.commit()
            remaining = connection.execute(
                "SELECT COUNT(*) FROM core_databasebackuprun WHERE id = ?",
                (run_id,),
            ).fetchone()
            if remaining is None or int(remaining[0]) != 0:
                raise runtime.BackupServiceError(
                    "SQLiteスナップショットに作成中runが残っています。"
                )
    except runtime.BackupServiceError:
        raise
    except sqlite3.Error as exc:
        raise runtime.BackupServiceError(
            "SQLiteスナップショットの作成中runを確認できません。"
        ) from exc


def _remove_transient_sqlite_sidecars(path: Path, runtime) -> None:
    cleanup_errors: list[str] = []
    for sidecar in (
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    ):
        if not sidecar.exists() and not sidecar.is_symlink():
            continue
        if sidecar.is_symlink():
            cleanup_errors.append(f"シンボリックリンクのため削除しません: {sidecar}")
            continue
        try:
            sidecar.unlink()
        except OSError as exc:
            cleanup_errors.append(f"{sidecar.name}: {exc}")
    if cleanup_errors:
        raise runtime.BackupServiceError(
            "SQLiteバックアップの一時sidecarを削除できません: " + "; ".join(cleanup_errors)
        )


def _inspect_sqlite_database(path: Path, runtime) -> dict[str, object]:
    try:
        with _connect_read_only(path) as connection:
            quick_check_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
            if quick_check_rows != ["ok"]:
                raise runtime.BackupServiceError(
                    "SQLiteバックアップの整合性確認（quick_check）に失敗しました。"
                )
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_rows:
                raise runtime.BackupServiceError(
                    f"SQLiteバックアップに外部キー不整合があります: {len(foreign_key_rows)}件"
                )
            identity_row = connection.execute(
                "SELECT installation_id, runtime_kind "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            ).fetchone()
            if identity_row is None:
                raise runtime.BackupServiceError("SQLiteバックアップにDB識別情報がありません。")
            identity = {
                "installation_id": _canonical_installation_id(identity_row[0], runtime),
                "runtime_kind": str(identity_row[1]),
            }
            if identity["runtime_kind"] != "product":
                raise runtime.BackupServiceError(
                    "SQLiteバックアップは製品DBではありません: "
                    f"runtime_kind={identity['runtime_kind']!r}"
                )
            table_counts: dict[str, int] = {}
            for table_name in SQLITE_SUMMARY_TABLES:
                row = connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                if row is None:
                    raise runtime.BackupServiceError(
                        f"SQLiteバックアップの表 {table_name} を確認できません。"
                    )
                table_counts[table_name] = int(row[0])
            migration_rows = connection.execute(
                "SELECT app, name FROM django_migrations ORDER BY app, name"
            ).fetchall()
    except runtime.BackupServiceError:
        raise
    except sqlite3.Error as exc:
        raise runtime.BackupServiceError(
            "SQLiteバックアップの検証に必要な表を読み取れません。"
        ) from exc
    return {
        "identity": identity,
        "migration_rows": migration_rows,
        "table_counts": table_counts,
        "quick_check": "ok",
        "foreign_key_violation_count": 0,
    }


def _canonical_installation_id(raw_value, runtime) -> str:
    try:
        parsed = uuid.UUID(str(raw_value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise runtime.BackupServiceError("DB識別情報のinstallation_idが不正です。") from exc
    if parsed.int == 0:
        raise runtime.BackupServiceError("DB識別情報のinstallation_idが不正です。")
    return str(parsed)


def _calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(
    *,
    temp_path: Path,
    final_path: Path,
    payload: dict[str, object],
    runtime,
    defer_final_replace: bool = False,
) -> None:
    try:
        descriptor = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not defer_final_replace:
            os.replace(temp_path, final_path)
            _fsync_directory(final_path.parent)
    except (OSError, TypeError, ValueError) as exc:
        raise runtime.BackupServiceError(
            "SQLiteバックアップmanifestの保存に失敗しました。"
        ) from exc


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some mounted filesystems do not support directory fsync.  The files
        # themselves have already been fsynced, so this remains best-effort.
        pass
    finally:
        os.close(descriptor)


def _validated_sqlite_backup_artifact(
    backup_run,
    *,
    current_identity: dict[str, str],
    source_path: Path,
    runtime,
) -> tuple[Path, dict[str, object]]:
    if backup_run.status != "succeeded":
        raise runtime.BackupServiceError("成功したバックアップだけをテスト復元できます。")
    backup_file_path = Path((backup_run.backup_file_path or "").strip())
    if backup_file_path.is_symlink() or not backup_file_path.is_file():
        raise runtime.BackupServiceError("対象SQLiteバックアップファイルが見つかりません。")
    if backup_file_path.resolve() == source_path.resolve():
        raise runtime.BackupServiceError(
            "現在のSQLite DBファイルそのものはテスト復元の対象にできません。"
        )
    if backup_file_path.suffix != ".sqlite3":
        raise runtime.BackupServiceError("対象ファイルはSQLiteバックアップではありません。")

    actual_size = backup_file_path.stat().st_size
    if actual_size <= 0:
        raise runtime.BackupServiceError("対象SQLiteバックアップファイルが空です。")
    if backup_run.backup_file_size != actual_size:
        raise runtime.BackupServiceError(
            "対象SQLiteバックアップファイルのサイズが記録と一致しません。"
        )
    actual_sha256 = _calculate_sha256(backup_file_path).lower()
    expected_sha256 = (backup_run.backup_sha256 or "").strip().lower()
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise runtime.BackupServiceError(
            "対象SQLiteバックアップファイルのSHA256が記録と一致しません。"
        )

    manifest_path = Path((backup_run.manifest_file_path or "").strip())
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise runtime.BackupServiceError("対象SQLiteバックアップのmanifestが見つかりません。")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise runtime.BackupServiceError(
            "対象SQLiteバックアップのmanifestを読み取れません。"
        ) from exc
    _validate_sqlite_manifest(
        manifest,
        backup_run=backup_run,
        backup_file_path=backup_file_path,
        actual_size=actual_size,
        actual_sha256=actual_sha256,
        current_identity=current_identity,
        runtime=runtime,
    )
    return backup_file_path, manifest


def _validate_sqlite_manifest(
    manifest,
    *,
    backup_run,
    backup_file_path: Path,
    actual_size: int,
    actual_sha256: str,
    current_identity: dict[str, str],
    runtime,
) -> None:
    if not isinstance(manifest, dict):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの形式が不正です。")
    if manifest.get("manifest_version") != SQLITE_MANIFEST_VERSION:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの版が未対応です。")
    if manifest.get("database_engine") != SQLITE_BACKUP_ENGINE:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestのDB種別が不正です。")
    if manifest.get("backup_run_id") != backup_run.id:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestのrun IDが一致しません。")
    if manifest.get("snapshot_excluded_backup_run_id") != backup_run.id:
        raise runtime.BackupServiceError(
            "SQLiteバックアップmanifestのsnapshot除外run IDが一致しません。"
        )
    if manifest.get("trigger_kind") != backup_run.trigger_kind:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの実行種別が一致しません。")
    if backup_run.backup_file_name != backup_file_path.name:
        raise runtime.BackupServiceError("SQLiteバックアップrunのファイル名が一致しません。")
    if manifest.get("backup_file_name") != backup_file_path.name:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestのファイル名が一致しません。")
    if manifest.get("backup_file_path") != str(backup_file_path):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの保存先が一致しません。")
    if manifest.get("backup_file_size") != actual_size:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestのサイズが一致しません。")
    manifest_sha256 = str(manifest.get("backup_sha256") or "").lower()
    if manifest_sha256 != actual_sha256:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestのSHA256が一致しません。")

    raw_identity = manifest.get("database_identity")
    if not isinstance(raw_identity, dict):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestにDB識別情報がありません。")
    manifest_identity = {
        "installation_id": _canonical_installation_id(raw_identity.get("installation_id"), runtime),
        "runtime_kind": str(raw_identity.get("runtime_kind") or ""),
    }
    if manifest_identity != current_identity:
        raise runtime.BackupServiceError(
            "SQLiteバックアップmanifestのDB識別情報が現在のDBと一致しません。"
        )
    expectations = manifest.get("verification_expectations")
    if not isinstance(expectations, dict):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestに検証条件がありません。")
    if expectations.get("quick_check") != "ok":
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの整合性条件が不正です。")
    if expectations.get("foreign_key_violation_count") != 0:
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの外部キー条件が不正です。")
    counts = expectations.get("table_counts")
    if not isinstance(counts, dict) or set(counts) != set(SQLITE_SUMMARY_TABLES):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの件数条件が不正です。")
    if any(type(counts[table_name]) is not int or counts[table_name] < 0 for table_name in counts):
        raise runtime.BackupServiceError("SQLiteバックアップmanifestの件数条件が不正です。")


def _validate_restored_snapshot(
    restored: dict[str, object],
    *,
    manifest: dict[str, object],
    current_identity: dict[str, str],
    runtime,
) -> None:
    if restored["identity"] != current_identity:
        raise runtime.BackupServiceError("復元したSQLiteのDB識別情報が現在のDBと一致しません。")
    expectations = manifest["verification_expectations"]
    if restored["quick_check"] != expectations["quick_check"]:
        raise runtime.BackupServiceError("復元したSQLiteの整合性結果がmanifestと一致しません。")
    if restored["foreign_key_violation_count"] != expectations["foreign_key_violation_count"]:
        raise runtime.BackupServiceError(
            "復元したSQLiteの外部キー検証結果がmanifestと一致しません。"
        )
    if restored["table_counts"] != expectations["table_counts"]:
        raise runtime.BackupServiceError("復元したSQLiteの主要表件数がmanifestと一致しません。")


def _validated_verification_root(runtime) -> Path:
    root = SQLITE_VERIFICATION_ROOT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise runtime.BackupServiceError("SQLiteテスト復元用ディレクトリが安全ではありません。")
    return root


def _validate_verification_path(
    path: Path,
    *,
    verification_root: Path,
    protected_paths: tuple[Path, ...],
    runtime,
) -> None:
    if not _VERIFICATION_FILE_PATTERN.fullmatch(path.name):
        raise runtime.BackupServiceError("SQLiteテスト復元用ファイル名が不正です。")
    if path.parent.resolve() != verification_root.resolve():
        raise runtime.BackupServiceError("SQLiteテスト復元用ファイルの保存先が不正です。")
    protected = {protected_path.resolve() for protected_path in protected_paths}
    if path.resolve() in protected:
        raise runtime.BackupServiceError("SQLiteテスト復元用ファイルが保護対象DBと重複しています。")
    if path.exists() or path.is_symlink():
        raise runtime.BackupServiceError(
            f"同名のSQLiteテスト復元用ファイルが既にあります: {path.name}"
        )


def _remove_verification_files(
    path: Path,
    *,
    verification_root: Path,
    protected_paths: tuple[Path, ...],
    runtime,
) -> None:
    protected = {protected_path.resolve() for protected_path in protected_paths}
    cleanup_errors: list[str] = []
    for candidate in (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    ):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.parent.resolve() != verification_root.resolve():
            cleanup_errors.append(f"保存先が不正です: {candidate}")
            continue
        if candidate.resolve() in protected:
            cleanup_errors.append(f"保護対象のため削除しません: {candidate}")
            continue
        if candidate.is_symlink():
            cleanup_errors.append(f"シンボリックリンクのため削除しません: {candidate}")
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            cleanup_errors.append(f"{candidate.name}: {exc}")
    if cleanup_errors:
        raise runtime.BackupServiceError("; ".join(cleanup_errors))


def _recover_stale_sqlite_verifications(current_verification, runtime) -> None:
    stale_before = runtime.timezone.now() - timedelta(
        seconds=runtime.MAINTENANCE_RESERVATION_GRACE_SECONDS
    )
    stale_runs = (
        DatabaseBackupVerificationRun.objects.filter(
            backup_run__database_engine=SQLITE_BACKUP_ENGINE,
            status="running",
            started_at__lt=stale_before,
        )
        .exclude(pk=current_verification.pk)
        .select_related("backup_run")
    )
    verification_root = _validated_verification_root(runtime)
    source_path = _product_sqlite_source_path(runtime)
    for stale_run in stale_runs:
        file_name = (stale_run.verification_database_name or "").strip()
        error_message = "前回のSQLiteテスト復元が中断されたため、失敗として回収しました。"
        if file_name:
            stale_path = verification_root / file_name
            if _VERIFICATION_FILE_PATTERN.fullmatch(file_name):
                try:
                    protected = [source_path]
                    backup_path_text = (stale_run.backup_run.backup_file_path or "").strip()
                    if backup_path_text:
                        protected.append(Path(backup_path_text))
                    _remove_verification_files(
                        stale_path,
                        verification_root=verification_root,
                        protected_paths=tuple(protected),
                        runtime=runtime,
                    )
                except Exception as exc:
                    error_message += f" 一時SQLiteを自動削除できませんでした: {exc}"
                else:
                    error_message += " 一時SQLiteは削除しました。"
            else:
                error_message += " 安全なファイル名ではないため自動削除していません。"
        stale_run.status = "failed"
        stale_run.verification_summary = {}
        stale_run.error_message = error_message
        stale_run.finished_at = runtime.timezone.now()
        stale_run.save(
            update_fields=[
                "status",
                "verification_summary",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )


def _update_setting_after_backup(setting, run, *, success: bool, runtime) -> None:
    setting.last_status = run.status
    setting.last_status_message = (
        run.error_message if not success else "バックアップが完了しました。"
    )
    setting.last_completed_at = run.finished_at
    update_fields = [
        "last_status",
        "last_status_message",
        "last_completed_at",
        "updated_at",
    ]
    if run.trigger_kind == "scheduled":
        setting.last_scheduled_attempt_on = runtime.timezone.localdate(run.started_at)
        setting.last_scheduled_attempt_engine = SQLITE_BACKUP_ENGINE
        update_fields.extend(["last_scheduled_attempt_on", "last_scheduled_attempt_engine"])
    setting.save(update_fields=update_fields)


def _prune_old_sqlite_backup_artifacts(
    setting,
    *,
    destination_path: str,
    protected_source: Path,
    runtime,
) -> None:
    runs = list(
        DatabaseBackupRun.objects.filter(
            database_engine=SQLITE_BACKUP_ENGINE,
            status="succeeded",
            destination_path=destination_path,
        )
        .exclude(backup_file_path="")
        .order_by("-started_at", "-id")
    )
    destination_root = Path(destination_path).resolve()
    protected_source_resolved = protected_source.resolve()
    for stale_run in runs[setting.retention_count :]:
        paths = [Path(stale_run.backup_file_path)]
        if stale_run.manifest_file_path:
            paths.append(Path(stale_run.manifest_file_path))
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            try:
                parent = path.parent.resolve()
                resolved = path.resolve()
            except OSError as exc:
                raise runtime.BackupServiceError(
                    f"古いSQLiteバックアップの保存先を確認できません: {path}"
                ) from exc
            if parent != destination_root or resolved == protected_source_resolved:
                continue
            if path.is_symlink():
                continue
            if path.suffix not in {".sqlite3", ".json"}:
                continue
            path.unlink()


def _cleanup_partial_files(
    paths: tuple[Path | None, ...],
    *,
    protected_paths: tuple[Path, ...],
) -> list[str]:
    protected = {path.resolve() for path in protected_paths}
    errors: list[str] = []
    for path in paths:
        if path is None:
            continue
        candidates = (
            path,
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
            Path(f"{path}-journal"),
        )
        for candidate in candidates:
            if not candidate.exists() and not candidate.is_symlink():
                continue
            if path.resolve() in protected or not path.name.endswith(".part"):
                errors.append(f"安全に削除できないパスです: {candidate}")
                continue
            if candidate.is_symlink():
                errors.append(f"シンボリックリンクのため削除しません: {candidate}")
                continue
            try:
                candidate.unlink()
            except OSError as exc:
                errors.append(f"{candidate.name}: {exc}")
    return errors


def _cleanup_incomplete_artifact(
    path: Path,
    *,
    destination_path: Path,
    protected_paths: tuple[Path, ...],
) -> list[str]:
    """Remove an output that never acquired its matching manifest.

    Successful artifacts are never passed here.  The path and suffix checks
    keep failure cleanup away from the live database and older backups.
    """

    if not path.exists() and not path.is_symlink():
        return []
    protected = {protected_path.resolve() for protected_path in protected_paths}
    try:
        destination_resolved = destination_path.resolve()
        path_resolved = path.resolve()
    except OSError as exc:
        return [f"未完了成果物の保存先を確認できません: {path}: {exc}"]
    if (
        path.parent.resolve() != destination_resolved
        or path_resolved in protected
        or path.suffix != ".sqlite3"
        or path.is_symlink()
    ):
        return [f"未完了成果物を安全に削除できません: {path}"]
    try:
        path.unlink()
    except OSError as exc:
        return [f"{path.name}: {exc}"]
    return []
