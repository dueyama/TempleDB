from __future__ import annotations

import logging
import os
import subprocess
import sys

from django.conf import settings
from django.utils import timezone

from apps.core.services import google_calendar as google_calendar_service
from apps.core.services import runtime_role

from . import google_calendar_sync_bindings as sync_bindings
from . import google_calendar_sync_state as sync_state
from . import google_calendar_sync_targets as sync_targets
from .google_calendar_sync_types import GoogleCalendarBulkSyncAlreadyRunningError

logger = logging.getLogger(__name__)


def start_google_calendar_bulk_sync_process(*, requested_by_label: str = "") -> dict[str, object]:
    _assert_google_calendar_remote_access_allowed()
    current_status = sync_state.read_google_calendar_bulk_sync_status()
    if current_status.get("running"):
        raise GoogleCalendarBulkSyncAlreadyRunningError(
            "Google カレンダー一括同期はすでに実行中です。"
        )

    sync_keys = sorted(sync_targets._collect_google_calendar_reconcile_keys())
    if not sync_keys:
        payload = sync_state._default_google_calendar_bulk_sync_status()
        payload.update(
            {
                "status": "succeeded",
                "summary": "一括同期の対象はありませんでした。",
                "started_at": timezone.now().isoformat(),
                "finished_at": timezone.now().isoformat(),
            }
        )
        sync_state._write_google_calendar_bulk_sync_status(payload)
        return payload

    command = [
        sys.executable,
        "manage.py",
        "run_google_calendar_bulk_sync",
        "--actor",
        (requested_by_label or "").strip(),
    ]
    process = subprocess.Popen(
        command,
        cwd=settings.BASE_DIR,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    payload = sync_state._default_google_calendar_bulk_sync_status()
    payload.update(
        {
            "status": "starting",
            "pid": process.pid,
            "actor": (requested_by_label or "").strip(),
            "running": True,
            "started_at": timezone.now().isoformat(),
            "finished_at": "",
            "total_count": len(sync_keys),
            "processed_count": 0,
            "summary": f"Google カレンダー一括同期を開始しました。対象 {len(sync_keys)} 件です。",
        }
    )
    sync_state._write_google_calendar_bulk_sync_status(payload)
    return payload


def execute_google_calendar_bulk_sync(*, actor: str = "") -> dict[str, object]:
    _assert_google_calendar_remote_access_allowed()
    lock_fd = sync_state.acquire_google_calendar_bulk_sync_lock()
    if lock_fd is None:
        raise GoogleCalendarBulkSyncAlreadyRunningError(
            "Google カレンダー一括同期はすでに実行中です。"
        )

    try:
        sync_keys = sorted(sync_targets._collect_google_calendar_reconcile_keys())
        payload = sync_state._default_google_calendar_bulk_sync_status()
        payload.update(
            {
                "status": "running",
                "pid": os.getpid(),
                "actor": (actor or "").strip(),
                "running": True,
                "started_at": timezone.now().isoformat(),
                "finished_at": "",
                "total_count": len(sync_keys),
                "processed_count": 0,
                "summary": f"Google カレンダー一括同期を開始しました。対象 {len(sync_keys)} 件です。",
            }
        )
        sync_state._write_google_calendar_bulk_sync_status(payload)

        try:
            if not sync_keys:
                payload["status"] = "succeeded"
                payload["running"] = False
                payload["finished_at"] = timezone.now().isoformat()
                payload["summary"] = "一括同期の対象はありませんでした。"
                sync_state._write_google_calendar_bulk_sync_status(payload)
                return payload

            action_counts = sync_state._normalized_google_calendar_bulk_sync_action_counts(None)
            recent_results: list[dict[str, str]] = []
            total_count = len(sync_keys)
            for index, sync_key in enumerate(sync_keys, start=1):
                payload["current_sync_key"] = sync_key
                payload["summary"] = f"{index - 1}/{total_count} 件完了。{sync_key} を同期中です。"
                sync_state._write_google_calendar_bulk_sync_status(payload)

                result = sync_bindings.sync_google_calendar_for_sync_keys([sync_key], check_remote=True)[0]
                action_counts[result.action] = action_counts.get(result.action, 0) + 1
                recent_results.append(
                    {
                        "sync_key": result.sync_key,
                        "action": result.action,
                        "message": result.message,
                    }
                )
                recent_results = recent_results[-8:]
                payload["processed_count"] = index
                payload["current_sync_key"] = sync_key
                payload["current_message"] = result.message
                payload["action_counts"] = action_counts
                payload["recent_results"] = recent_results
                payload["summary"] = (
                    f"{index}/{total_count} 件完了。"
                    f"{sync_state._google_calendar_action_label(result.action)}: {result.message}"
                )
                sync_state._write_google_calendar_bulk_sync_status(payload)

            payload["status"] = "succeeded"
            payload["running"] = False
            payload["finished_at"] = timezone.now().isoformat()
            payload["summary"] = sync_state._google_calendar_bulk_sync_summary_message(
                action_counts, total_count=total_count
            )
            sync_state._write_google_calendar_bulk_sync_status(payload)
            return payload
        except Exception as exc:
            payload["status"] = "failed"
            payload["running"] = False
            payload["finished_at"] = timezone.now().isoformat()
            payload["summary"] = f"Google カレンダー一括同期に失敗しました: {exc}"
            payload["error_message"] = str(exc)
            sync_state._write_google_calendar_bulk_sync_status(payload)
            raise
    finally:
        sync_state.release_google_calendar_bulk_sync_lock(lock_fd)


def maybe_dispatch_scheduled_google_calendar_reconcile(*, requested_by_label: str = "") -> bool:
    del requested_by_label
    if not runtime_role.google_calendar_access_allowed():
        return False
    setting = google_calendar_service.get_or_create_google_calendar_sync_setting()
    if not google_calendar_service.google_calendar_is_ready(setting):
        return False
    if sync_state.read_google_calendar_bulk_sync_status().get("running"):
        return False
    if not sync_state._google_calendar_schedule_check_due():
        return False
    today = timezone.localdate()
    if sync_state._scheduled_google_calendar_attempted_on() == today:
        return False
    if not sync_state._scheduled_google_calendar_reconcile_needed():
        sync_state._write_scheduled_google_calendar_attempt_on(today)
        return False
    try:
        sync_state.spawn_scheduled_google_calendar_reconcile_process()
    except Exception:
        logger.exception("google calendar reconcile spawn failed")
        return False
    sync_state._write_scheduled_google_calendar_attempt_on(today)
    return True


def _assert_google_calendar_remote_access_allowed() -> None:
    try:
        runtime_role.assert_google_calendar_access_allowed()
    except runtime_role.RuntimeRoleConfigurationError as exc:
        raise google_calendar_service.GoogleCalendarConfigurationError(str(exc)) from exc
