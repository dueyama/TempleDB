from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from contextlib import contextmanager
from weakref import WeakValueDictionary

from config.platform_file_lock import PlatformFileLockBusyError, lock_exclusive, unlock
from config.runtime_paths import runtime_root

GOOGLE_CALENDAR_SYNC_LOCK_TIMEOUT_SECONDS = 10.0
_thread_locks: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
_thread_locks_guard = threading.Lock()


class GoogleCalendarSyncLockTimeout(TimeoutError):
    pass


class GoogleCalendarSyncLockUnsafe(RuntimeError):
    pass


def _safe_lock_metadata(metadata, *, directory: bool = False) -> bool:
    if directory:
        if not stat.S_ISDIR(metadata.st_mode):
            return False
    elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        return False
    # Windows does not expose the POSIX owner/mode contract, but still requires
    # a regular non-linked file and the same open inode below.
    if hasattr(os, "getuid"):
        if metadata.st_uid != os.getuid():
            return False
        mode = stat.S_IMODE(metadata.st_mode)
        unsafe_mode = bool(mode & 0o022) if directory else mode != 0o600
        if unsafe_mode:
            return False
    return True


@contextmanager
def google_calendar_sync_key_lock(sync_key: str):
    """Serialize all writers on this tenant's single active runtime host.

    Keep the inode permanently: unlinking it on release lets old and new
    waiters acquire different locks. Hash keys so they never become paths or
    expose schedule identifiers. The local mutex also covers Windows threads.
    """
    digest = hashlib.sha256(sync_key.encode("utf-8")).hexdigest()
    path = runtime_root() / "google_calendar_sync_locks" / f"{digest}.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _safe_lock_metadata(path.parent.lstat(), directory=True):
        raise GoogleCalendarSyncLockUnsafe("Google Calendar lock directory is unsafe")
    with _thread_locks_guard:
        thread_lock = _thread_locks.get(str(path))
        if thread_lock is None:
            thread_lock = threading.Lock()
            _thread_locks[str(path)] = thread_lock
    deadline = time.monotonic() + GOOGLE_CALENDAR_SYNC_LOCK_TIMEOUT_SECONDS
    if not thread_lock.acquire(timeout=max(0, deadline - time.monotonic())):
        raise GoogleCalendarSyncLockTimeout
    descriptor = None
    acquired = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            not _safe_lock_metadata(metadata)
            or not _safe_lock_metadata(path_metadata)
            or (metadata.st_dev, metadata.st_ino) != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise GoogleCalendarSyncLockUnsafe("Google Calendar lock file is unsafe")
        while True:
            try:
                lock_exclusive(descriptor, blocking=False)
                acquired = True
                break
            except PlatformFileLockBusyError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GoogleCalendarSyncLockTimeout from None
                time.sleep(min(0.05, remaining))
        yield
    finally:
        try:
            if descriptor is not None:
                try:
                    if acquired:
                        unlock(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            thread_lock.release()
