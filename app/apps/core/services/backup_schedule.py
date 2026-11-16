from __future__ import annotations

import json
import os
from datetime import timedelta

from . import runtime_role


def _backup_module():
    from . import backup

    return backup


def reset_schedule_check_cache() -> None:
    runtime = _backup_module()
    runtime._last_schedule_check_monotonic = 0.0
    runtime._last_verification_schedule_check_monotonic = 0.0


def maybe_dispatch_scheduled_backup(*, requested_by_label: str = "") -> bool:
    if not runtime_role.scheduled_maintenance_allowed():
        return False
    runtime = _backup_module()
    if not runtime.is_database_backup_supported():
        return False
    if not runtime._schedule_check_due():
        return False

    schedule_lock = _acquire_schedule_lock()
    if schedule_lock is None:
        return False

    try:
        with runtime.transaction.atomic():
            setting = runtime.DatabaseBackupSetting.objects.select_for_update().get_or_create(
                singleton_key=1
            )[0]
            try:
                destination_path = runtime.effective_backup_destination_path(setting)
            except runtime.BackupServiceError:
                return False
            if not setting.daily_enabled or not destination_path:
                return False
            now = runtime.timezone.now()
            today = runtime.timezone.localdate(now)
            engine = runtime.current_database_engine()
            if (
                setting.last_scheduled_attempt_on == today
                and setting.last_scheduled_attempt_engine == engine
            ):
                return False
            if _fresh_running_backup_exists(now=now):
                return False
            if _fresh_running_verification_exists(now=now):
                return False
            if runtime._maintenance_lock_is_active():
                return False
            setting.last_scheduled_attempt_on = today
            setting.last_scheduled_attempt_engine = engine
            setting.last_status = "running"
            setting.last_status_message = "日次バックアップを起動しました。"
            setting.save(
                update_fields=[
                    "last_scheduled_attempt_on",
                    "last_scheduled_attempt_engine",
                    "last_status",
                    "last_status_message",
                    "updated_at",
                ]
            )
        try:
            runtime.spawn_scheduled_backup_process(requested_by_label=requested_by_label)
        except Exception as exc:
            runtime._record_scheduled_spawn_failure(
                str(exc), requested_by_label=requested_by_label
            )
            return False
        return True
    except (runtime.OperationalError, runtime.ProgrammingError):
        return False
    finally:
        _release_schedule_lock(schedule_lock)


def maybe_dispatch_scheduled_verification(*, requested_by_label: str = "") -> bool:
    if not runtime_role.scheduled_maintenance_allowed():
        return False
    runtime = _backup_module()
    if not runtime.is_database_backup_supported():
        return False
    if not runtime._verification_schedule_check_due():
        return False

    schedule_lock = _acquire_schedule_lock()
    if schedule_lock is None:
        return False

    verification = None
    try:
        with runtime.transaction.atomic():
            setting = runtime.DatabaseBackupSetting.objects.select_for_update().get_or_create(
                singleton_key=1
            )[0]
            try:
                destination_path = runtime.effective_backup_destination_path(setting)
            except runtime.BackupServiceError:
                return False
            if not setting.weekly_verification_enabled or not destination_path:
                return False
            now = runtime.timezone.now()
            today = runtime.timezone.localdate(now)
            if (
                setting.last_scheduled_attempt_on == today
                and setting.last_scheduled_attempt_engine
                == runtime.current_database_engine()
                and setting.last_status == "running"
                and setting.updated_at >= _maintenance_reservation_cutoff(now)
            ):
                return False
            if _fresh_running_backup_exists(now=now):
                return False
            if runtime._maintenance_lock_is_active():
                return False

            backup_run = runtime.latest_successful_backup_run()
            if backup_run is None:
                return False

            if runtime.verification_runs_for_current_engine().filter(
                trigger_kind="scheduled",
                started_at__date=today,
            ).exists():
                return False
            if not _scheduled_verification_needed(now=now):
                return False

            verification = runtime.DatabaseBackupVerificationRun.objects.create(
                backup_run=backup_run,
                trigger_kind="scheduled",
                status="running",
                requested_by_label=(requested_by_label or "").strip(),
                started_at=now,
            )
        try:
            runtime.spawn_scheduled_verification_process(verification)
        except Exception as exc:
            runtime._record_scheduled_verification_spawn_failure(verification, str(exc))
            return False
        return True
    except (runtime.OperationalError, runtime.ProgrammingError):
        return False
    finally:
        _release_schedule_lock(schedule_lock)


def _scheduled_verification_needed(*, now) -> bool:
    runtime = _backup_module()
    latest_success = runtime.latest_successful_verification_run()
    if latest_success is None or latest_success.finished_at is None:
        return True
    due_at = latest_success.finished_at + timedelta(
        days=runtime.WEEKLY_VERIFICATION_INTERVAL_DAYS
    )
    return due_at <= now


def _maintenance_reservation_cutoff(now):
    runtime = _backup_module()
    return now - timedelta(seconds=runtime.MAINTENANCE_RESERVATION_GRACE_SECONDS)


def _fresh_running_backup_exists(*, now) -> bool:
    runtime = _backup_module()
    return runtime.backup_runs_for_current_engine().filter(
        status="running",
        started_at__gte=_maintenance_reservation_cutoff(now),
    ).exists()


def _fresh_running_verification_exists(*, now) -> bool:
    runtime = _backup_module()
    return runtime.verification_runs_for_current_engine().filter(
        status="running",
        started_at__gte=_maintenance_reservation_cutoff(now),
    ).exists()


def spawn_scheduled_backup_process(*, requested_by_label: str = "") -> None:
    runtime = _backup_module()
    command = [
        runtime.sys.executable,
        str(runtime.BASE_DIR / "manage.py"),
        "run_database_backup",
        "--trigger",
        "scheduled",
    ]
    if requested_by_label.strip():
        command.extend(["--requested-by", requested_by_label.strip()])
    runtime.subprocess.Popen(
        command,
        cwd=runtime.BASE_DIR,
        env=runtime.os.environ.copy(),
        stdout=runtime.subprocess.DEVNULL,
        stderr=runtime.subprocess.DEVNULL,
    )


def spawn_scheduled_verification_process(verification) -> None:
    runtime = _backup_module()
    command = [
        runtime.sys.executable,
        str(runtime.BASE_DIR / "manage.py"),
        "verify_database_backup",
        "--run-id",
        str(verification.backup_run_id),
        "--verification-id",
        str(verification.id),
        "--trigger",
        "scheduled",
    ]
    if verification.requested_by_label.strip():
        command.extend(["--requested-by", verification.requested_by_label.strip()])
    runtime.subprocess.Popen(
        command,
        cwd=runtime.BASE_DIR,
        env=runtime.os.environ.copy(),
        stdout=runtime.subprocess.DEVNULL,
        stderr=runtime.subprocess.DEVNULL,
    )


def _schedule_check_due() -> bool:
    runtime = _backup_module()
    now_monotonic = runtime.time.monotonic()
    if now_monotonic - runtime._last_schedule_check_monotonic < runtime.SCHEDULE_CHECK_INTERVAL_SECONDS:
        return False
    runtime._last_schedule_check_monotonic = now_monotonic
    return True


def _verification_schedule_check_due() -> bool:
    runtime = _backup_module()
    now_monotonic = runtime.time.monotonic()
    if (
        now_monotonic - runtime._last_verification_schedule_check_monotonic
        < runtime.SCHEDULE_CHECK_INTERVAL_SECONDS
    ):
        return False
    runtime._last_verification_schedule_check_monotonic = now_monotonic
    return True


def _record_scheduled_spawn_failure(error_message: str, *, requested_by_label: str = "") -> None:
    runtime = _backup_module()
    try:
        setting = runtime.get_or_create_backup_setting()
        destination_path = runtime.effective_backup_destination_path(setting)
        run = runtime.DatabaseBackupRun.objects.create(
            setting=setting,
            database_engine=runtime.current_database_engine(),
            trigger_kind="scheduled",
            status="failed",
            requested_by_label=(requested_by_label or "").strip(),
            database_name=runtime.settings.DATABASES["default"].get("NAME", ""),
            database_host=runtime.settings.DATABASES["default"].get("HOST", ""),
            destination_path=destination_path,
            error_message=error_message,
            started_at=runtime.timezone.now(),
            finished_at=runtime.timezone.now(),
        )
        runtime._update_setting_after_run(setting, run, success=False)
    except Exception:  # pragma: no cover - logging only
        runtime.logger.exception("failed to record scheduled backup spawn failure")


def _record_scheduled_verification_spawn_failure(verification, error_message: str) -> None:
    runtime = _backup_module()
    try:
        verification.status = "failed"
        verification.error_message = error_message
        verification.finished_at = runtime.timezone.now()
        verification.save(
            update_fields=["status", "error_message", "finished_at", "updated_at"]
        )
    except Exception:  # pragma: no cover - logging only
        runtime.logger.exception("failed to record scheduled verification spawn failure")


def _acquire_schedule_lock() -> dict[str, object] | None:
    runtime = _backup_module()
    runtime.SCHEDULE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "started_at": runtime.timezone.now().isoformat(),
    }
    for _attempt in range(3):
        try:
            with runtime.SCHEDULE_LOCK_PATH.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            return payload
        except FileExistsError:
            stale_payload = runtime._read_lock_payload(runtime.SCHEDULE_LOCK_PATH)
            if stale_payload and runtime._pid_is_alive(int(stale_payload.get("pid", 0))):
                return None
            if stale_payload is None and runtime._lock_file_is_recent(
                runtime.SCHEDULE_LOCK_PATH
            ):
                return None
            try:
                runtime.SCHEDULE_LOCK_PATH.unlink()
            except FileNotFoundError:
                continue
    return None


def _release_schedule_lock(lock_token: dict[str, object] | None) -> None:
    runtime = _backup_module()
    if lock_token is None or not runtime.SCHEDULE_LOCK_PATH.exists():
        return
    payload = runtime._read_lock_payload(runtime.SCHEDULE_LOCK_PATH)
    if payload != lock_token:
        return
    runtime.SCHEDULE_LOCK_PATH.unlink()
