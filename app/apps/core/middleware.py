from __future__ import annotations

import logging

from apps.core.services import backup

logger = logging.getLogger(__name__)


class DatabaseBackupScheduleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        authenticated = bool(getattr(user, "is_authenticated", False))
        backup_dispatched = False
        requested_by_label = ""
        if authenticated:
            requested_by_label = user.get_username().strip()
            try:
                from apps.office.services import google_calendar_sync

                google_calendar_sync.maybe_dispatch_scheduled_google_calendar_reconcile(
                    requested_by_label=requested_by_label,
                )
            except Exception:  # pragma: no cover - request safety logging only
                logger.exception("google calendar scheduling failed")
        response = self.get_response(request)
        if authenticated:
            try:
                backup_dispatched = backup.maybe_dispatch_scheduled_backup(
                    requested_by_label=requested_by_label,
                )
            except Exception:  # pragma: no cover - request safety logging only
                logger.exception("daily backup scheduling failed")
        if authenticated and not backup_dispatched:
            try:
                backup.maybe_dispatch_scheduled_verification(
                    requested_by_label=requested_by_label,
                )
            except Exception:  # pragma: no cover - request safety logging only
                logger.exception("weekly backup verification scheduling failed")
        return response
