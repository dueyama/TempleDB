from __future__ import annotations

from apps.core.services import google_calendar as google_calendar_service
from apps.imports.models import GoogleCalendarSyncBinding, ServiceSchedule

from . import google_calendar_sync_targets as sync_targets

GOOGLE_CALENDAR_BINDING_STATUS_LABELS = {
    "disabled": "無効",
    "not_configured": "未設定",
    "out_of_scope": "同期対象外",
    GoogleCalendarSyncBinding.SyncStatus.PENDING: "未同期",
    GoogleCalendarSyncBinding.SyncStatus.SYNCED: "同期済み",
    GoogleCalendarSyncBinding.SyncStatus.ERROR: "エラー",
    GoogleCalendarSyncBinding.SyncStatus.CONFLICT: "競合",
    "missing": "未作成",
}


def build_service_schedule_google_calendar_sync_status(schedule: ServiceSchedule) -> dict[str, object]:
    setting = google_calendar_service.get_or_create_google_calendar_sync_setting()
    account_info = google_calendar_service.google_calendar_service_account_info()
    sync_key = sync_targets.google_calendar_sync_key_for_schedule(schedule)
    binding = (
        GoogleCalendarSyncBinding.objects.filter(sync_key=sync_key)
        .select_related("primary_schedule")
        .first()
    )
    target = sync_targets._build_sync_target(sync_key)
    if not setting.enabled:
        status_key = "disabled"
    elif google_calendar_service.google_calendar_configuration_errors(setting):
        status_key = "not_configured"
    elif not target.should_exist and binding is None:
        status_key = "out_of_scope"
    elif binding is None:
        status_key = "missing"
    else:
        status_key = binding.sync_status
    return {
        "enabled": bool(setting.enabled),
        "calendar_id": (setting.calendar_id or "").strip(),
        "client_email": account_info.client_email,
        "service_account_path": account_info.path,
        "service_account_error": account_info.error,
        "sync_key": sync_key,
        "status_key": status_key,
        "status_label": GOOGLE_CALENDAR_BINDING_STATUS_LABELS.get(status_key, status_key),
        "google_event_id": binding.google_event_id if binding is not None else "",
        "last_synced_at": binding.last_synced_at if binding is not None else None,
        "last_error_message": binding.last_error_message if binding is not None else "",
        "can_resync": binding is not None or status_key in {"missing", "not_configured", "disabled"},
    }
