from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from config.platform_process import pid_is_alive
from config.runtime_paths import runtime_root

from .google_calendar_sync_targets import _collect_google_calendar_reconcile_keys

GOOGLE_CALENDAR_RECONCILE_LOCK_PATH = Path("data/runtime/google_calendar_reconcile.lock")
GOOGLE_CALENDAR_RECONCILE_STATE_PATH = Path("data/runtime/google_calendar_reconcile.state.json")
GOOGLE_CALENDAR_BULK_SYNC_LOCK_PATH = Path("data/runtime/google_calendar_bulk_sync.lock")
GOOGLE_CALENDAR_BULK_SYNC_STATUS_PATH = Path("data/runtime/google_calendar_bulk_sync.status.json")
GOOGLE_CALENDAR_SCHEDULE_CHECK_INTERVAL_SECONDS = 300.0
_last_schedule_check_monotonic = 0.0


def _runtime_state_path(relative_path: Path) -> Path:
    return runtime_root() / relative_path.relative_to("data/runtime")


def read_google_calendar_bulk_sync_status() -> dict[str, object]:
    path = _runtime_state_path(GOOGLE_CALENDAR_BULK_SYNC_STATUS_PATH)
    payload = _default_google_calendar_bulk_sync_status()
    if not path.exists():
        return payload
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload["status"] = "failed"
        payload["summary"] = "一括同期の状態ファイルを読めませんでした。"
        return payload

    payload.update(loaded if isinstance(loaded, dict) else {})
    payload["action_counts"] = _normalized_google_calendar_bulk_sync_action_counts(
        payload.get("action_counts")
    )
    payload["recent_results"] = _normalized_google_calendar_bulk_sync_recent_results(
        payload.get("recent_results")
    )
    payload["running"] = _google_calendar_bulk_sync_process_running(payload)
    try:
        payload["updated_at"] = timezone.make_aware(
            datetime.fromtimestamp(path.stat().st_mtime)
        ).isoformat()
    except (OSError, ValueError):
        payload["updated_at"] = ""
    if payload.get("status") in {"starting", "running"} and not payload["running"] and not payload.get("finished_at"):
        payload["status"] = "failed"
        payload["summary"] = "一括同期の開始記録が残っていますが、実行中のプロセスは見つかりません。"
    return payload


def spawn_scheduled_google_calendar_reconcile_process() -> None:
    command = [
        sys.executable,
        "manage.py",
        "reconcile_google_calendar_sync",
        "--scheduled",
    ]
    subprocess.Popen(
        command,
        cwd=settings.BASE_DIR,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def acquire_google_calendar_reconcile_lock() -> int | None:
    lock_path = _runtime_state_path(GOOGLE_CALENDAR_RECONCILE_LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def release_google_calendar_reconcile_lock(lock_fd: int | None) -> None:
    if lock_fd is None:
        return
    lock_path = _runtime_state_path(GOOGLE_CALENDAR_RECONCILE_LOCK_PATH)
    try:
        os.close(lock_fd)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def acquire_google_calendar_bulk_sync_lock() -> int | None:
    lock_path = _runtime_state_path(GOOGLE_CALENDAR_BULK_SYNC_LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if not read_google_calendar_bulk_sync_status().get("running"):
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            try:
                return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return None
        return None


def release_google_calendar_bulk_sync_lock(lock_fd: int | None) -> None:
    if lock_fd is None:
        return
    lock_path = _runtime_state_path(GOOGLE_CALENDAR_BULK_SYNC_LOCK_PATH)
    try:
        os.close(lock_fd)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass



def _default_google_calendar_bulk_sync_status() -> dict[str, object]:
    return {
        "status": "idle",
        "pid": None,
        "actor": "",
        "running": False,
        "started_at": "",
        "finished_at": "",
        "updated_at": "",
        "total_count": 0,
        "processed_count": 0,
        "current_sync_key": "",
        "current_message": "",
        "summary": "",
        "error_message": "",
        "action_counts": _normalized_google_calendar_bulk_sync_action_counts(None),
        "recent_results": [],
    }


def _write_google_calendar_bulk_sync_status(payload: dict[str, object]) -> None:
    path = _runtime_state_path(GOOGLE_CALENDAR_BULK_SYNC_STATUS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _google_calendar_bulk_sync_process_running(payload: dict[str, object] | None) -> bool:
    if not payload or payload.get("status") not in {"starting", "running"}:
        return False
    pid = payload.get("pid")
    if not pid:
        return True
    try:
        return pid_is_alive(int(pid))
    except (ValueError, TypeError):
        return False


def _normalized_google_calendar_bulk_sync_action_counts(value) -> dict[str, int]:
    action_counts = {action: 0 for action in _google_calendar_bulk_sync_action_order()}
    if not isinstance(value, dict):
        return action_counts
    for action, count in value.items():
        if action not in action_counts:
            continue
        try:
            action_counts[action] = max(int(count), 0)
        except (TypeError, ValueError):
            continue
    return action_counts


def _normalized_google_calendar_bulk_sync_recent_results(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value[-8:]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "sync_key": str(item.get("sync_key", "") or "").strip(),
                "action": str(item.get("action", "") or "").strip(),
                "message": str(item.get("message", "") or "").strip(),
            }
        )
    return normalized


def _google_calendar_bulk_sync_action_order() -> tuple[str, ...]:
    return ("created", "updated", "deleted", "unchanged", "skipped", "disabled", "error", "conflict")


def _google_calendar_action_label(action: str) -> str:
    labels = {
        "created": "作成",
        "updated": "更新",
        "deleted": "削除",
        "unchanged": "差分なし",
        "skipped": "対象なし",
        "disabled": "無効",
        "error": "エラー",
        "conflict": "競合",
    }
    return labels.get((action or "").strip(), (action or "").strip() or "不明")


def _google_calendar_bulk_sync_summary_message(
    action_counts: dict[str, int],
    *,
    total_count: int,
) -> str:
    parts = []
    for action in _google_calendar_bulk_sync_action_order():
        count = action_counts.get(action, 0)
        if not count:
            continue
        parts.append(f"{_google_calendar_action_label(action)} {count}件")
    if not parts:
        return f"Google カレンダー一括同期が完了しました。対象 {total_count} 件でした。"
    return f"Google カレンダー一括同期が完了しました。対象 {total_count} 件。 " + " / ".join(parts)

def _scheduled_google_calendar_reconcile_needed() -> bool:
    return bool(_collect_google_calendar_reconcile_keys())


def _google_calendar_schedule_check_due() -> bool:
    global _last_schedule_check_monotonic
    now_monotonic = time.monotonic()
    if now_monotonic - _last_schedule_check_monotonic < GOOGLE_CALENDAR_SCHEDULE_CHECK_INTERVAL_SECONDS:
        return False
    _last_schedule_check_monotonic = now_monotonic
    return True


def _scheduled_google_calendar_attempted_on() -> date | None:
    path = _runtime_state_path(GOOGLE_CALENDAR_RECONCILE_STATE_PATH)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw_value = str(payload.get("last_attempt_on", "") or "").strip()
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def _write_scheduled_google_calendar_attempt_on(value: date) -> None:
    path = _runtime_state_path(GOOGLE_CALENDAR_RECONCILE_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_attempt_on": value.isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
