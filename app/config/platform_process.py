from __future__ import annotations

import ctypes
import os


def pid_is_alive(pid: int) -> bool:
    """Return whether a process is alive without signalling it on Windows."""

    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int, *, kernel32=None) -> bool:
    """Inspect a Windows PID with process-query APIs instead of ``os.kill``.

    Python's Windows implementation can translate non-console ``os.kill``
    signals into ``TerminateProcess``. Unknown query failures therefore fail
    closed as "possibly alive" so stale-lock cleanup never risks another
    process.
    """

    if pid <= 0:
        return False
    if kernel32 is None:  # pragma: no cover - exercised on Windows
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError):
            return True

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87

    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    open_process.restype = ctypes.c_void_p
    handle = open_process(process_query_limited_information, 0, pid)
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == error_invalid_parameter:
            return False
        if error_code == error_access_denied:
            return True
        return True

    try:
        exit_code = ctypes.c_uint32()
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        get_exit_code.restype = ctypes.c_int
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (ctypes.c_void_p,)
        close_handle.restype = ctypes.c_int
        close_handle(handle)


__all__ = ["pid_is_alive"]
