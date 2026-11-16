"""Ownership and progress of one OCR run per tenant/year.

The long-lived run lock is the source of truth, not a PID or a JSON state.
The short state lock serializes starts, stop requests and progress publication.
Lock files are permanent: removing them would let waiters lock different inodes.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from weakref import WeakValueDictionary

from django.utils import timezone

from config import runtime_paths
from config.platform_file_lock import PlatformFileLockBusyError, lock_exclusive, unlock

ROOT_NAME = "annual_membership_fee_postal_scans"
ACTIVE_STATES = frozenset({"running", "stopping"})
_thread_locks: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
_thread_locks_guard = threading.Lock()


def _path(year: int, name: str) -> Path:
    root = runtime_paths.runtime_root() / ROOT_NAME / str(int(year))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise OSError("OCR job directory is unsafe")
    return root / name


def progress_path(year: int) -> Path:
    return _path(year, "ai_ocr_progress.json")


def stop_path(year: int) -> Path:
    return _path(year, "ai_ocr_stop.requested")


class RunLease:
    """A non-reentrant lease transferable from the request to its worker thread."""

    def __init__(self, descriptor: int, thread_lock: threading.Lock):
        self.descriptor = descriptor
        self.thread_lock = thread_lock

    def close(self) -> None:
        if self.descriptor is None:
            return
        descriptor, self.descriptor = self.descriptor, None
        try:
            try:
                unlock(descriptor)
            finally:
                os.close(descriptor)
        finally:
            self.thread_lock.release()


def _acquire_file(path: Path, *, blocking: bool) -> RunLease | None:
    with _thread_locks_guard:
        thread_lock = _thread_locks.get(str(path))
        if thread_lock is None:
            thread_lock = threading.Lock()
            _thread_locks[str(path)] = thread_lock
    if not thread_lock.acquire(blocking=blocking):
        return None
    descriptor = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        metadata, linked = os.fstat(descriptor), path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino) != (linked.st_dev, linked.st_ino)
            or (hasattr(os, "getuid") and (
                metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600
            ))
        ):
            raise OSError("OCR job lock is unsafe")
        try:
            lock_exclusive(descriptor, blocking=blocking)
        except PlatformFileLockBusyError:
            os.close(descriptor)
            thread_lock.release()
            return None
        return RunLease(descriptor, thread_lock)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        thread_lock.release()
        raise


@contextmanager
def _state_lock(year: int):
    lease = _acquire_file(_path(year, "ai_ocr_state.lock"), blocking=True)
    try:
        yield
    finally:
        lease.close()


def _try_run_lock(year: int) -> RunLease | None:
    return _acquire_file(_path(year, "ai_ocr_run.lock"), blocking=False)


def progress_snapshot(
    *, state: str, total_count: int = 0, completed_count: int = 0,
    processed_count: int = 0, skipped_count: int = 0,
    error_messages: list[str] | None = None, current_label: str = "",
    current_scan_id: int | None = None, message: str = "",
) -> dict[str, Any]:
    total_count = max(int(total_count or 0), 0)
    completed_count = min(max(int(completed_count or 0), 0), total_count)
    return {
        "state": state, "total_count": total_count, "completed_count": completed_count,
        "processed_count": int(processed_count or 0), "skipped_count": int(skipped_count or 0),
        "error_count": len(error_messages or []), "error_messages": list(error_messages or [])[-10:],
        "current_label": current_label, "current_scan_id": current_scan_id,
        "percent": int(round(completed_count / total_count * 100)) if total_count else 0,
        "message": message, "updated_at": timezone.localtime().isoformat(timespec="seconds"),
        "stop_requested": False,
    }


def _read_progress(year: int) -> dict:
    try:
        payload = json.loads(progress_path(year).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return progress_snapshot(state="idle", message="AI OCRは未実行です。")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return progress_snapshot(state="unknown", message="AI OCR進捗を読めません。")
    if not isinstance(payload, dict):
        return progress_snapshot(state="unknown", message="AI OCR進捗を読めません。")
    payload.setdefault("state", "unknown")
    payload.setdefault("message", "")
    return payload


def _write_progress(year: int, progress: dict) -> None:
    path = progress_path(year)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def write_progress(*, year: int, progress: dict) -> None:
    with _state_lock(year):
        _write_progress(year, progress)


def stop_requested(*, year: int) -> bool:
    return stop_path(year).exists()


def _clear_stop(year: int) -> None:
    stop_path(year).unlink(missing_ok=True)


def clear_stop(*, year: int) -> None:
    with _state_lock(year):
        _clear_stop(year)


def begin_run(*, year: int, clear_stop: bool = True) -> RunLease | None:
    with _state_lock(year):
        lease = _try_run_lock(year)
        if lease is None:
            return None
        try:
            if clear_stop:
                _clear_stop(year)
            _write_progress(year, progress_snapshot(state="running", message="AI OCRを開始しました。"))
        except BaseException:
            lease.close()
            raise
        return lease


def finish_run(*, year: int, lease: RunLease) -> None:
    try:
        with _state_lock(year):
            _clear_stop(year)
    finally:
        lease.close()


def record_failure(*, year: int, error: Exception) -> None:
    with _state_lock(year):
        progress = _read_progress(year)
        progress.update(
            state="error", message=f"AI OCRを実行できませんでした: {error}",
            error_messages=[*progress.get("error_messages", []), str(error)][-10:],
            error_count=int(progress.get("error_count", 0)) + 1,
            updated_at=timezone.localtime().isoformat(timespec="seconds"), stop_requested=False,
        )
        _write_progress(year, progress)


def _recover_abandoned(year: int, progress: dict) -> dict:
    # Called only while holding BOTH locks. A live owner is never overwritten.
    if progress.get("state") in ACTIVE_STATES:
        progress.update(
            state="error", message="AI OCRが中断されました。未処理分を再実行できます。",
            updated_at=timezone.localtime().isoformat(timespec="seconds"), stop_requested=False,
        )
        _write_progress(year, progress)
    _clear_stop(year)
    progress["stop_requested"] = False
    return progress


def read_progress(*, year: int) -> dict:
    with _state_lock(year):
        lease = _try_run_lock(year)
        try:
            progress = _read_progress(year)
            if lease is not None:
                return _recover_abandoned(year, progress)
            progress["stop_requested"] = stop_requested(year=year)
            if progress["state"] in ACTIVE_STATES and progress["stop_requested"]:
                progress.update(state="stopping", message="停止要求を受け付けました。現在の1件が終わったら停止します。")
            return progress
        finally:
            if lease is not None:
                lease.close()


def request_stop(*, year: int) -> None:
    with _state_lock(year):
        lease = _try_run_lock(year)
        if lease is not None:
            try:
                _recover_abandoned(year, _read_progress(year))
            finally:
                lease.close()
            return
        # Do not write a stale progress snapshot over the worker's latest counts.
        stop_path(year).write_text("stop\n", encoding="utf-8")
