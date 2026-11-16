"""Shared results and errors for calendar synchronization, without orchestration imports."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleCalendarSyncResult:
    sync_key: str
    action: str
    message: str
    binding_status: str


class GoogleCalendarBulkSyncAlreadyRunningError(RuntimeError):
    pass
