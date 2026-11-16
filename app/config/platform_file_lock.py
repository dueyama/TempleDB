from __future__ import annotations

import errno
import os

if os.name == "nt":  # pragma: no cover - exercised on Windows
    _fcntl = None
    import msvcrt as _msvcrt
else:
    import fcntl as _fcntl

    _msvcrt = None


class PlatformFileLockUnavailableError(RuntimeError):
    """Raised when the host has no supported advisory file-lock implementation."""


class PlatformFileLockBusyError(BlockingIOError):
    """Raised when a non-blocking exclusive lock is already owned."""


_BUSY_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EDEADLK", None),
    )
    if value is not None
)
_BUSY_WINERRORS = frozenset({33, 36})


def lock_exclusive(descriptor: int, *, blocking: bool = True) -> None:
    """Acquire an exclusive advisory lock without weakening the POSIX contract."""

    if _fcntl is not None:
        flags = _fcntl.LOCK_EX
        if not blocking:
            flags |= _fcntl.LOCK_NB
        try:
            _fcntl.flock(descriptor, flags)
        except OSError as exc:
            if not blocking and _is_busy_error(exc):
                raise PlatformFileLockBusyError from exc
            raise
        return

    if _msvcrt is not None:
        _prepare_windows_lock_byte(descriptor)
        mode = _msvcrt.LK_LOCK if blocking else _msvcrt.LK_NBLCK
        while True:
            try:
                _msvcrt.locking(descriptor, mode, 1)
            except OSError as exc:
                if not _is_busy_error(exc):
                    raise
                if not blocking:
                    raise PlatformFileLockBusyError from exc
                continue
            break
        return

    raise PlatformFileLockUnavailableError(
        "This platform has no supported advisory file-lock implementation."
    )


def unlock(descriptor: int) -> None:
    """Release a lock acquired by :func:`lock_exclusive`."""

    if _fcntl is not None:
        _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
        return
    raise PlatformFileLockUnavailableError(
        "This platform has no supported advisory file-lock implementation."
    )


def _prepare_windows_lock_byte(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
        os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)


def _is_busy_error(exc: OSError) -> bool:
    return exc.errno in _BUSY_ERRNOS or getattr(exc, "winerror", None) in _BUSY_WINERRORS


__all__ = [
    "PlatformFileLockBusyError",
    "PlatformFileLockUnavailableError",
    "lock_exclusive",
    "unlock",
]
