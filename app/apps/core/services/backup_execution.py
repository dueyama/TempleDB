from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from config import platform_process
from config.platform_file_lock import PlatformFileLockBusyError, lock_exclusive, unlock

from . import backup_restore_contract, runtime_role

_POSTGRESQL_HOMEBREW_FORMULAS = frozenset({"postgresql@16", "postgresql@17"})
_POSTGRESQL_TOOL_NAMES = frozenset(
    {"createdb", "dropdb", "pg_dump", "pg_restore", "psql"}
)
_HOMEBREW_DEFAULT_PREFIXES = (Path("/opt/homebrew"), Path("/usr/local"))
POSTGRES_CONNECT_TIMEOUT_SECONDS = 10
POSTGRES_LOCK_TIMEOUT_SECONDS = 30
POSTGRES_INSPECTION_TIMEOUT_SECONDS = 60
POSTGRES_COMMAND_TIMEOUT_SECONDS = {
    "pg_dump": 600,
    "pg_restore": 900,
    "createdb": 60,
    "dropdb": 60,
    "psql": 60,
}


def _backup_module():
    from . import backup

    return backup


def perform_database_backup(
    *,
    trigger_kind: str,
    requested_by_label: str = "",
    now=None,
):
    runtime = _backup_module()
    _assert_scheduled_maintenance_allowed(runtime, trigger_kind=trigger_kind)
    engine = runtime.current_database_engine()
    if engine == "postgresql":
        return _perform_postgresql_database_backup(
            trigger_kind=trigger_kind,
            requested_by_label=requested_by_label,
            now=now,
        )
    if engine == "sqlite" and runtime.is_product_sqlite_configured():
        from .backup_sqlite import perform_sqlite_database_backup

        return perform_sqlite_database_backup(
            trigger_kind=trigger_kind,
            requested_by_label=requested_by_label,
            now=now,
        )
    raise runtime.BackupServiceError(
        "バックアップは本運用DB（PostgreSQL / SQLite）でのみ実行できます。"
    )


def _assert_scheduled_maintenance_allowed(runtime, *, trigger_kind: str) -> None:
    if trigger_kind != "scheduled":
        return
    if runtime_role.scheduled_maintenance_allowed():
        return
    raise runtime.BackupServiceError(
        f"TEMPLEDB_RUNTIME_ROLE={runtime_role.current_runtime_role()} のため、"
        "自動バックアップと自動テスト復元を停止しています。"
    )


def validate_backup_artifact(backup_run) -> Path:
    runtime = _backup_module()
    engine = getattr(backup_run, "database_engine", "")
    if engine != runtime.current_database_engine():
        raise runtime.BackupServiceError("現在のDBエンジンとは異なるバックアップです。")
    if engine == "postgresql":
        return _validated_backup_file_path(backup_run)
    if engine == "sqlite" and runtime.is_product_sqlite_configured():
        from .backup_sqlite import validate_sqlite_backup_artifact

        return validate_sqlite_backup_artifact(backup_run)
    raise runtime.BackupServiceError("このDBエンジンのバックアップは検証できません。")


def _perform_postgresql_database_backup(
    *,
    trigger_kind: str,
    requested_by_label: str = "",
    now=None,
):
    runtime = _backup_module()
    if not runtime.is_postgresql_configured():
        raise runtime.BackupServiceError("PostgreSQL 接続時のみバックアップできます。")

    setting = runtime.get_or_create_backup_setting()
    configured_destination_path = runtime.effective_backup_destination_path(setting)
    if not configured_destination_path:
        raise runtime.BackupServiceError("バックアップ保存先がまだ設定されていません。")

    connection_config = runtime.get_postgres_connection_config()
    started_at = now or runtime.timezone.now()
    run = runtime.DatabaseBackupRun.objects.create(
        setting=setting,
        database_engine="postgresql",
        trigger_kind=trigger_kind,
        status="running",
        requested_by_label=(requested_by_label or "").strip(),
        database_name=connection_config.database_name,
        database_host=connection_config.database_host,
        destination_path=configured_destination_path,
        started_at=started_at,
    )

    lock_token = None
    try:
        lock_token = runtime._acquire_backup_lock(run)
        destination_path = Path(configured_destination_path)
        if not destination_path.exists() or not destination_path.is_dir():
            raise runtime.BackupServiceError(f"保存先が利用できません: {destination_path}")
        if not os.access(destination_path, os.W_OK):
            raise runtime.BackupServiceError(f"保存先へ書き込めません: {destination_path}")

        timestamp_label = runtime.timezone.localtime(started_at).strftime("%Y%m%d_%H%M%S")
        backup_file_name = (
            f"{connection_config.database_name}_{timestamp_label}_run{run.id}_{uuid.uuid4().hex}.dump"
        )
        backup_file_path = destination_path / backup_file_name
        temp_backup_path = backup_file_path.with_suffix(".dump.part")
        manifest_path = backup_file_path.with_suffix(".json")

        # Reserve this attempt's name; never truncate another attempt's partial.
        if os.path.lexists(backup_file_path) or os.path.lexists(manifest_path):
            raise runtime.BackupServiceError("バックアップ保存先に同名の成果物が存在します。")
        os.close(os.open(temp_backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))

        runtime._run_command(
            runtime.build_pg_dump_command(connection_config, output_path=temp_backup_path),
            env=runtime.build_postgres_env(connection_config),
        )
        _publish_backup_without_replace(temp_backup_path, backup_file_path)
        backup_sha256 = runtime.calculate_sha256(backup_file_path)
        backup_file_size = backup_file_path.stat().st_size
        manifest = {
            "backup_run_id": run.id,
            "created_at": runtime.timezone.localtime(started_at).isoformat(),
            "trigger_kind": trigger_kind,
            "database_name": connection_config.database_name,
            "database_host": connection_config.database_host,
            "backup_file_name": backup_file_name,
            "backup_file_path": str(backup_file_path),
            "backup_file_size": backup_file_size,
            "backup_sha256": backup_sha256,
        }
        manifest_fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(manifest_fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

        finished_at = runtime.timezone.now()
        run.status = "succeeded"
        run.backup_file_name = backup_file_name
        run.backup_file_path = str(backup_file_path)
        run.manifest_file_path = str(manifest_path)
        run.backup_file_size = backup_file_size
        run.backup_sha256 = backup_sha256
        run.finished_at = finished_at
        run.save(
            update_fields=[
                "status",
                "backup_file_name",
                "backup_file_path",
                "manifest_file_path",
                "backup_file_size",
                "backup_sha256",
                "finished_at",
                "updated_at",
            ]
        )
        runtime._update_setting_after_run(setting, run, success=True)
    except Exception as exc:
        finished_at = runtime.timezone.now()
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = finished_at
        run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        runtime._update_setting_after_run(setting, run, success=False)
        raise
    else:
        # Retention is housekeeping after a usable backup has been committed.
        # A cleanup error must not make that backup ineligible for restoration.
        _run_backup_retention(
            setting, run, prune=lambda: runtime.prune_old_backup_artifacts(setting)
        )
        return run
    finally:
        runtime._release_backup_lock(lock_token)


def _run_backup_retention(setting, run, *, prune: Callable[[], None]) -> None:
    runtime = _backup_module()
    try:
        prune()
    except Exception as exc:
        warning = f"バックアップは完了しました。古い世代の整理に失敗しました: {exc}"
        runtime.logger.warning("Backup %s retention failed: %s", run.pk, exc, exc_info=True)
        # Existing history/status views display these fields even for succeeded runs.
        run.error_message = warning
        run.save(update_fields=["error_message", "updated_at"])
        setting.last_status_message = warning
        setting.save(update_fields=["last_status_message", "updated_at"])


def _publish_backup_without_replace(source: Path, destination: Path) -> None:
    """Publish without replacement, including volumes that do not support hard links."""
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError as exc:
        unsupported = {errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOSYS,
                       errno.ENOTSUP, errno.EOPNOTSUPP}
        if exc.errno not in unsupported:
            raise
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
    source.unlink()


def perform_backup_verification(
    backup_run,
    *,
    requested_by_label: str = "",
    trigger_kind: str = "manual",
    verification_run=None,
    now=None,
):
    runtime = _backup_module()
    _assert_scheduled_maintenance_allowed(runtime, trigger_kind=trigger_kind)
    engine = runtime.current_database_engine()
    if backup_run.database_engine != engine:
        raise runtime.BackupServiceError(
            "現在のDBエンジンとは異なるバックアップをテスト復元できません。"
        )
    if engine == "postgresql":
        return _perform_postgresql_backup_verification(
            backup_run,
            requested_by_label=requested_by_label,
            trigger_kind=trigger_kind,
            verification_run=verification_run,
            now=now,
        )
    if engine == "sqlite" and runtime.is_product_sqlite_configured():
        from .backup_sqlite import perform_sqlite_backup_verification

        return perform_sqlite_backup_verification(
            backup_run,
            requested_by_label=requested_by_label,
            trigger_kind=trigger_kind,
            verification_run=verification_run,
            now=now,
        )
    raise runtime.BackupServiceError(
        "テスト復元は本運用DB（PostgreSQL / SQLite）でのみ実行できます。"
    )


def _perform_postgresql_backup_verification(
    backup_run,
    *,
    requested_by_label: str = "",
    trigger_kind: str = "manual",
    verification_run=None,
    now=None,
):
    runtime = _backup_module()
    if not runtime.is_postgresql_configured():
        raise runtime.BackupServiceError("PostgreSQL 接続時のみテスト復元できます。")
    if backup_run.database_engine != "postgresql":
        raise runtime.BackupServiceError("PostgreSQLバックアップではありません。")
    if trigger_kind not in {"manual", "scheduled"}:
        raise runtime.BackupServiceError("テスト復元の実行種別が不正です。")

    requested_by = (requested_by_label or "").strip()
    if verification_run is None:
        started_at = now or runtime.timezone.now()
        verification = runtime.DatabaseBackupVerificationRun.objects.create(
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

    verification_db_name = runtime.timezone.localtime(started_at).strftime(
        "templedb_verify_%Y%m%d_%H%M%S"
    )
    verification_db_name = f"{verification_db_name}_{verification.id}"
    verification.verification_database_name = verification_db_name
    verification.save(
        update_fields=["requested_by_label", "verification_database_name", "updated_at"]
    )

    lock_token = None
    admin_config = None
    created_database = False
    database_creation_started = False
    verification_summary: dict[str, object] = {}
    operation_error: Exception | None = None
    cleanup_error: Exception | None = None
    try:
        lock_token = runtime._acquire_verification_lock(verification)
        admin_config = runtime.get_postgres_admin_config()
        _recover_stale_verification_runs(verification, admin_config)
        backup_file_path = _validated_backup_file_path(backup_run)
        database_creation_started = True
        runtime._run_command(
            runtime.build_createdb_command(admin_config, verification_db_name),
            env=runtime.build_postgres_env(admin_config),
        )
        created_database = True
        runtime._run_command(
            runtime.build_pg_restore_command(admin_config, verification_db_name, backup_file_path),
            env=runtime.build_postgres_env(admin_config),
        )
        verification_summary = runtime.inspect_restored_database(
            admin_config,
            verification_db_name,
        )
    except Exception as exc:
        operation_error = exc
        if database_creation_started and isinstance(exc.__cause__, runtime.subprocess.TimeoutExpired):
            # createdb may have committed before its response was lost. This run's
            # unique temporary name is safe to clean up with dropdb --if-exists.
            created_database = True
    finally:
        if created_database and admin_config is not None:
            try:
                runtime._run_command(
                    runtime.build_dropdb_command(admin_config, verification_db_name),
                    env=runtime.build_postgres_env(admin_config),
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
                f"一時検証DB {verification_db_name} を削除できませんでした: {cleanup_error}"
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


def _validated_backup_file_path(backup_run) -> Path:
    runtime = _backup_module()
    if backup_run.status != "succeeded":
        raise runtime.BackupServiceError("成功したバックアップだけをテスト復元できます。")

    backup_file_path = Path((backup_run.backup_file_path or "").strip())
    if backup_file_path.is_symlink() or not backup_file_path.is_file():
        raise runtime.BackupServiceError("対象バックアップファイルが見つかりません。")

    actual_size = backup_file_path.stat().st_size
    if actual_size <= 0:
        raise runtime.BackupServiceError("対象バックアップファイルが空です。")
    if backup_run.backup_file_size is not None and backup_run.backup_file_size != actual_size:
        raise runtime.BackupServiceError("対象バックアップファイルのサイズが記録と一致しません。")

    expected_sha256 = (backup_run.backup_sha256 or "").strip().lower()
    if expected_sha256:
        actual_sha256 = runtime.calculate_sha256(backup_file_path).lower()
        if actual_sha256 != expected_sha256:
            raise runtime.BackupServiceError("対象バックアップファイルのSHA256が記録と一致しません。")
    return backup_file_path


def _recover_stale_verification_runs(current_verification, admin_config) -> None:
    runtime = _backup_module()
    stale_before = runtime.timezone.now() - timedelta(
        seconds=runtime.MAINTENANCE_RESERVATION_GRACE_SECONDS
    )
    stale_runs = runtime.DatabaseBackupVerificationRun.objects.filter(
        backup_run__database_engine="postgresql",
        status="running",
        started_at__lt=stale_before,
    ).exclude(
        pk=current_verification.pk,
    )
    for stale_run in stale_runs:
        database_name = (stale_run.verification_database_name or "").strip()
        error_message = "前回のテスト復元が中断されたため、失敗として回収しました。"
        if database_name:
            if _is_safe_verification_database_name(database_name):
                try:
                    runtime._run_command(
                        runtime.build_dropdb_command(admin_config, database_name),
                        env=runtime.build_postgres_env(admin_config),
                    )
                except Exception as exc:
                    error_message += (
                        f" 一時検証DB {database_name} を自動削除できませんでした: {exc}"
                    )
                else:
                    error_message += f" 一時検証DB {database_name} は削除しました。"
            else:
                error_message += (
                    f" 安全な検証DB名ではないため {database_name} は自動削除していません。"
                )
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


def _is_safe_verification_database_name(database_name: str) -> bool:
    return bool(
        re.fullmatch(r"templedb_verify_\d{8}_\d{6}(?:_\d+)?", database_name)
    )


def build_pg_dump_command(
    config,
    *,
    output_path: Path,
) -> list[str]:
    runtime = _backup_module()
    executable = runtime.ensure_command_available("pg_dump") or "pg_dump"
    command = [
        executable, "--no-password", f"--lock-wait-timeout={POSTGRES_LOCK_TIMEOUT_SECONDS}s",
        "-Fc", "-f", str(output_path),
    ]
    if config.database_host:
        command.extend(["-h", config.database_host])
    if config.database_port:
        command.extend(["-p", config.database_port])
    if config.database_user:
        command.extend(["-U", config.database_user])
    command.append(config.database_name)
    return command


def build_createdb_command(config, database_name: str) -> list[str]:
    runtime = _backup_module()
    executable = runtime.ensure_command_available("createdb") or "createdb"
    command = [executable, "--no-password"]
    if config.database_host:
        command.extend(["-h", config.database_host])
    if config.database_port:
        command.extend(["-p", config.database_port])
    if config.database_user:
        command.extend(["-U", config.database_user])
    command.append(database_name)
    return command


def build_pg_restore_command(
    config,
    database_name: str,
    backup_file_path: Path,
) -> list[str]:
    runtime = _backup_module()
    executable = runtime.ensure_command_available("pg_restore") or "pg_restore"
    command = [executable, "--no-password", "--no-owner", "--no-privileges"]
    if config.database_host:
        command.extend(["-h", config.database_host])
    if config.database_port:
        command.extend(["-p", config.database_port])
    if config.database_user:
        command.extend(["-U", config.database_user])
    command.extend(["-d", database_name, str(backup_file_path)])
    return command


def build_dropdb_command(config, database_name: str) -> list[str]:
    runtime = _backup_module()
    executable = runtime.ensure_command_available("dropdb") or "dropdb"
    command = [executable, "--no-password", "--if-exists"]
    if config.database_host:
        command.extend(["-h", config.database_host])
    if config.database_port:
        command.extend(["-p", config.database_port])
    if config.database_user:
        command.extend(["-U", config.database_user])
    command.append(database_name)
    return command


def inspect_restored_database(config, database_name: str) -> dict[str, object]:
    runtime = _backup_module()
    connection_kwargs = {
        "dbname": database_name,
        "user": config.database_user or None,
        "password": config.database_password or None,
        "host": config.database_host or None,
        "port": config.database_port or None,
        "connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS,
        "options": (
            f"-c statement_timeout={POSTGRES_INSPECTION_TIMEOUT_SECONDS * 1000} "
            f"-c lock_timeout={POSTGRES_LOCK_TIMEOUT_SECONDS * 1000}"
        ),
    }
    connection_kwargs = {
        key: value for key, value in connection_kwargs.items() if value not in {None, ""}
    }
    with runtime.psycopg.connect(**connection_kwargs) as connection:
        with connection.cursor() as cursor:
            summary = {}
            for table_name in (
                "django_migrations",
                "auth_user",
                "imports_household",
                "imports_person",
                "imports_deceasedprofile",
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                summary[table_name] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT installation_id::text, runtime_kind "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            )
            identity_row = cursor.fetchone()
            if identity_row is None:
                raise runtime.BackupServiceError(
                    "復元したPostgreSQLにDB識別情報がありません。"
                )
            cursor.execute(
                "SELECT app, name FROM django_migrations ORDER BY app, name"
            )
            migration_rows = cursor.fetchall()
            cursor.execute("SHOW server_version_num")
            server_version_num = int(cursor.fetchone()[0])
            summary[backup_restore_contract.RESTORE_CONTRACT_KEY] = (
                backup_restore_contract.build_restore_contract(
                    database_engine="postgresql",
                    database_version=str(server_version_num // 10_000),
                    database_version_scope="server_major",
                    installation_id=identity_row[0],
                    runtime_kind=identity_row[1],
                    migration_rows=migration_rows,
                )
            )
            return summary


def build_postgres_env(config) -> dict[str, str]:
    runtime = _backup_module()
    env = runtime.os.environ.copy()
    if config.database_password:
        env["PGPASSWORD"] = config.database_password
    else:
        env.pop("PGPASSWORD", None)
    return env


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_old_backup_artifacts(setting) -> None:
    runtime = _backup_module()
    destination_path = runtime.effective_backup_destination_path(setting)
    runs = list(
        runtime.backup_runs_for_current_engine().filter(
            status="succeeded",
            destination_path=destination_path,
        )
        .exclude(backup_file_path="")
        .order_by("-started_at", "-id")
    )
    # Older releases could record more than one run against the same filename.
    # Keep files still referenced by a retained successful run.
    protected_paths = {
        str(Path(value).resolve())
        for run in runs[:setting.retention_count]
        for value in (run.backup_file_path, run.manifest_file_path)
        if value
    }
    for stale_run in runs[setting.retention_count :]:
        backup_path = Path(stale_run.backup_file_path)
        manifest_path = Path(stale_run.manifest_file_path) if stale_run.manifest_file_path else None
        if backup_path.exists() and str(backup_path.resolve()) not in protected_paths:
            backup_path.unlink()
        if (manifest_path is not None and manifest_path.exists()
                and str(manifest_path.resolve()) not in protected_paths):
            manifest_path.unlink()


def ensure_command_available(command_name: str) -> str:
    selected_tool = _selected_homebrew_postgresql_tool(command_name)
    if selected_tool is not None:
        return str(selected_tool)

    resolved_command = shutil.which(command_name)
    if resolved_command is not None:
        return resolved_command
    raise _backup_module().BackupServiceError(f"{command_name} が見つかりません。")


def _selected_homebrew_postgresql_tool(command_name: str) -> Path | None:
    if command_name not in _POSTGRESQL_TOOL_NAMES:
        return None

    formula = os.environ.get("TEMPLEDB_POSTGRESQL_FORMULA", "").strip()
    if not formula:
        return None
    if formula not in _POSTGRESQL_HOMEBREW_FORMULAS:
        raise _backup_module().BackupServiceError(
            "TEMPLEDB_POSTGRESQL_FORMULA が不正です。"
        )

    prefixes: list[Path] = []
    brew_command = shutil.which("brew")
    if brew_command:
        prefixes.append(Path(brew_command).parent.parent)
    prefixes.extend(_HOMEBREW_DEFAULT_PREFIXES)

    seen_prefixes: set[Path] = set()
    for prefix in prefixes:
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        candidate = prefix / "opt" / formula / "bin" / command_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    raise _backup_module().BackupServiceError(
        f"{formula} の {command_name} が見つかりません。"
    )


def _run_command(command: list[str], *, env: dict[str, str]):
    runtime = _backup_module()
    executable_name = Path(command[0]).name.lower().removesuffix(".exe")
    timeout = POSTGRES_COMMAND_TIMEOUT_SECONDS.get(executable_name, 600)
    if executable_name in _POSTGRESQL_TOOL_NAMES:
        # This boundary also covers transfer callers with their own sanitized env.
        env = {
            **env,
            "PGCONNECT_TIMEOUT": str(POSTGRES_CONNECT_TIMEOUT_SECONDS),
            "PGOPTIONS": (
                env.get("PGOPTIONS", "")
                + f" -c lock_timeout={POSTGRES_LOCK_TIMEOUT_SECONDS * 1000}"
            ).strip(),
        }
    try:
        # These builders run one PostgreSQL process, without parallel workers or
        # a shell. run(timeout=...) kills and reaps that child before raising, so
        # callers can release the maintenance lock without leaving it running.
        return runtime.subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=runtime.BASE_DIR,
            timeout=timeout,
        )
    except runtime.subprocess.TimeoutExpired as exc:
        raise runtime.BackupServiceError(
            f"{executable_name} が制限時間（{timeout}秒）を超えたため停止しました。"
        ) from exc
    except runtime.subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise runtime.BackupServiceError(stderr or f"{command[0]} の実行に失敗しました。") from exc


def _acquire_backup_lock(run) -> dict[str, object]:
    return _acquire_database_maintenance_lock(operation_kind="backup", record_id=run.id)


def _acquire_verification_lock(verification) -> dict[str, object]:
    return _acquire_database_maintenance_lock(
        operation_kind="verification",
        record_id=verification.id,
    )


_MAINTENANCE_LOCK_PROTOCOL = "os-held-v1"


class _MaintenanceLockToken(dict):
    """JSON-compatible ownership receipt plus a process-local OS-lock handle."""

    def __init__(self, payload: dict, descriptor: int):
        super().__init__(payload)
        self.descriptor: int | None = descriptor
        self.owner_pid = os.getpid()


def _open_maintenance_activity_lock(lock_path: Path) -> int:
    path = lock_path.with_name(f"{lock_path.name}.active.guard")
    if path.is_symlink():
        raise _backup_module().BackupServiceError("DB maintenanceのOSロックが不正です。")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _backup_module().BackupServiceError("DB maintenanceのOSロックが不正です。")
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _close_maintenance_activity_lock(descriptor: int) -> None:
    try:
        unlock(descriptor)
    finally:
        os.close(descriptor)


def _acquire_database_maintenance_lock(
    *,
    operation_kind: str,
    record_id: int,
) -> dict[str, object]:
    runtime = _backup_module()
    runtime.BACKUP_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor = _open_maintenance_activity_lock(runtime.BACKUP_LOCK_PATH)
    acquired = False
    payload = {
        "lock_protocol": _MAINTENANCE_LOCK_PROTOCOL,
        "lock_id": uuid.uuid4().hex,
        "pid": os.getpid(),
        "operation_kind": operation_kind,
        "record_id": record_id,
        "started_at": runtime.timezone.now().isoformat(),
    }
    try:
        try:
            lock_exclusive(descriptor, blocking=False)
        except PlatformFileLockBusyError:
            raise runtime.BackupAlreadyRunningError(
                "別のバックアップ、テスト復元、DB移送処理がまだ実行中です。"
            ) from None
        acquired = True
        # Keep the old short guard and PID receipt so older processes still refuse
        # to overlap us. Only v1 OS-lock receipts can disregard a reused PID.
        with _database_maintenance_lock_guard(runtime.BACKUP_LOCK_PATH):
            for _attempt in range(3):
                try:
                    with runtime.BACKUP_LOCK_PATH.open("x", encoding="utf-8") as handle:
                        json.dump(payload, handle, ensure_ascii=False)
                    return _MaintenanceLockToken(payload, descriptor)
                except FileExistsError:
                    stale_payload = _read_lock_payload(runtime.BACKUP_LOCK_PATH)
                    if (stale_payload
                            and stale_payload.get("lock_protocol") != _MAINTENANCE_LOCK_PROTOCOL
                            and _pid_is_alive(int(stale_payload.get("pid", 0)))):
                        raise runtime.BackupAlreadyRunningError(
                            "別のバックアップ、テスト復元、DB移送処理がまだ実行中です。"
                        ) from None
                    if stale_payload is None and _lock_file_is_recent(runtime.BACKUP_LOCK_PATH):
                        raise runtime.BackupAlreadyRunningError(
                            "DB maintenanceの実行ロックを確認中です。"
                        ) from None
                    try:
                        runtime.BACKUP_LOCK_PATH.unlink()
                    except FileNotFoundError:
                        continue
        raise runtime.BackupAlreadyRunningError(
            "バックアップ／テスト復元の実行ロックを取得できませんでした。"
        )
    except BaseException:
        if acquired:
            _close_maintenance_activity_lock(descriptor)
        else:
            os.close(descriptor)
        raise


def _maintenance_lock_is_active() -> bool:
    runtime = _backup_module()
    active_path = runtime.BACKUP_LOCK_PATH.with_name(f"{runtime.BACKUP_LOCK_PATH.name}.active.guard")
    if not runtime.BACKUP_LOCK_PATH.exists() and not active_path.exists():
        return False
    descriptor = _open_maintenance_activity_lock(runtime.BACKUP_LOCK_PATH)
    try:
        lock_exclusive(descriptor, blocking=False)
    except PlatformFileLockBusyError:
        os.close(descriptor)
        return True
    except BaseException:
        os.close(descriptor)
        raise
    try:
        with _database_maintenance_lock_guard(runtime.BACKUP_LOCK_PATH):
            payload = _read_lock_payload(runtime.BACKUP_LOCK_PATH)
            if payload is None:
                return _lock_file_is_recent(runtime.BACKUP_LOCK_PATH)
            if payload.get("lock_protocol") == _MAINTENANCE_LOCK_PROTOCOL:
                return False
            return _pid_is_alive(int(payload.get("pid", 0)))
    finally:
        _close_maintenance_activity_lock(descriptor)


def _lock_file_is_recent(lock_path: Path, *, grace_seconds: float = 60.0) -> bool:
    runtime = _backup_module()
    try:
        age_seconds = runtime.time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    return age_seconds < grace_seconds


def _release_backup_lock(lock_token: dict[str, object] | None) -> None:
    runtime = _backup_module()
    if lock_token is None:
        return
    if isinstance(lock_token, _MaintenanceLockToken):
        if lock_token.descriptor is None:
            return
        if lock_token.owner_pid != os.getpid():
            # A forked child must not unlock its parent's shared file description.
            os.close(lock_token.descriptor)
            lock_token.descriptor = None
            return
    try:
        with _database_maintenance_lock_guard(runtime.BACKUP_LOCK_PATH):
            if not runtime.BACKUP_LOCK_PATH.exists():
                return
            payload = _read_lock_payload(runtime.BACKUP_LOCK_PATH)
            if payload == lock_token:
                runtime.BACKUP_LOCK_PATH.unlink()
    finally:
        if isinstance(lock_token, _MaintenanceLockToken) and lock_token.descriptor is not None:
            descriptor, lock_token.descriptor = lock_token.descriptor, None
            _close_maintenance_activity_lock(descriptor)


@contextmanager
def _database_maintenance_lock_guard(lock_path: Path):
    guard_path = lock_path.with_name(f"{lock_path.name}.guard")
    guard_fd = os.open(guard_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.chmod(guard_path, 0o600)
        lock_exclusive(guard_fd)
        yield
    finally:
        try:
            unlock(guard_fd)
        finally:
            os.close(guard_fd)


def _read_lock_payload(lock_path: Path) -> dict[str, object] | None:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_is_alive(pid: int) -> bool:
    return platform_process.pid_is_alive(pid)


_windows_pid_is_alive = platform_process._windows_pid_is_alive


def _update_setting_after_run(
    setting,
    run,
    *,
    success: bool,
) -> None:
    runtime = _backup_module()
    setting.last_status = run.status
    setting.last_status_message = (
        run.error_message if not success else "バックアップが完了しました。"
    )
    setting.last_completed_at = run.finished_at
    if run.trigger_kind == "scheduled":
        setting.last_scheduled_attempt_on = runtime.timezone.localdate(run.started_at)
        setting.last_scheduled_attempt_engine = run.database_engine
    setting.save(
        update_fields=[
            "last_status",
            "last_status_message",
            "last_completed_at",
            "last_scheduled_attempt_on",
            "last_scheduled_attempt_engine",
            "updated_at",
        ]
    )
