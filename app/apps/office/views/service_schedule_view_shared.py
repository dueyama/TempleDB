from __future__ import annotations

import logging
import traceback

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest

from apps.imports.models import RecordEditLog, ServiceSchedule
from apps.office.services import google_calendar_sync
from apps.office.services.record_history_mutations import record_action_message_text
from apps.office.web_support import _parse_boolean_flag

logger = logging.getLogger(__name__)

SERVICE_LINK_EXTENDED_FIELD_NAME = "show_10_year_links"
SERVICE_LINK_EXTENDED_LOOKBACK_FIELD_NAME = "show_3_year_links"
SERVICE_LINKABLE_OTHER_LABELS = {"満中陰（四十九日）"}


def _service_schedule_supports_linking_values(category: str | None, service_label: str | None) -> bool:
    normalized_category = (category or "").strip()
    normalized_label = (service_label or "").strip()
    if normalized_label == "葬儀" or normalized_category == ServiceSchedule.Category.FUNERAL:
        return False
    if (
        normalized_category == ServiceSchedule.Category.OTHER
        and normalized_label in SERVICE_LINKABLE_OTHER_LABELS
    ):
        return True
    return normalized_category in {
        ServiceSchedule.Category.MEMORIAL,
        ServiceSchedule.Category.HATSUBON,
    }


def _service_schedule_supports_linking(schedule: ServiceSchedule) -> bool:
    return _service_schedule_supports_linking_values(schedule.category, schedule.service_label)


def _service_link_extended_requested(request: HttpRequest) -> bool:
    request_data = request.POST if request.method == "POST" else request.GET
    return _parse_boolean_flag(
        request_data.get(SERVICE_LINK_EXTENDED_FIELD_NAME),
        default=False,
    )


def _service_link_lookahead_years(request: HttpRequest) -> int:
    from apps.office.services.service_schedule_links import (
        SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS,
        SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS,
    )

    if _service_link_extended_requested(request):
        return SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS
    return SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS


def _service_link_extended_lookback_requested(request: HttpRequest) -> bool:
    request_data = request.POST if request.method == "POST" else request.GET
    return _parse_boolean_flag(
        request_data.get(SERVICE_LINK_EXTENDED_LOOKBACK_FIELD_NAME),
        default=False,
    )


def _service_link_lookback_years(request: HttpRequest) -> int:
    from apps.office.services.service_schedule_links import (
        SERVICE_LINK_DEFAULT_LOOKBACK_YEARS,
        SERVICE_LINK_EXTENDED_LOOKBACK_YEARS,
    )

    if _service_link_extended_lookback_requested(request):
        return SERVICE_LINK_EXTENDED_LOOKBACK_YEARS
    return SERVICE_LINK_DEFAULT_LOOKBACK_YEARS


def _completed_schedule_edit_enabled(request: HttpRequest, schedule: ServiceSchedule) -> bool:
    if schedule.is_deleted or schedule.status != ServiceSchedule.Status.COMPLETED:
        return True
    return _parse_boolean_flag(request.GET.get("edit") or request.POST.get("_edit_mode"))


def _completed_schedule_enable_edit_url(request: HttpRequest) -> str:
    query = request.GET.copy()
    query["edit"] = "1"
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _disable_bound_form_fields(form) -> None:
    for field in form.fields.values():
        field.disabled = True


def _disable_payment_formset_fields(formset) -> None:
    for payment_form in formset.forms:
        _disable_bound_form_fields(payment_form)


def _flash_record_action_message(
    request: HttpRequest,
    log_entry: RecordEditLog | None,
    message_text: str,
) -> None:
    messages.success(request, record_action_message_text(log_entry, message_text))


def _queue_google_calendar_sync(
    sync_keys: list[str] | tuple[str, ...],
    *,
    results_buffer: list[google_calendar_sync.GoogleCalendarSyncResult],
    check_remote: bool = False,
    force_remote_update: bool = False,
) -> None:
    normalized_keys: list[str] = []
    for sync_key in sync_keys:
        value = str(sync_key or "").strip()
        if not value or value in normalized_keys:
            continue
        normalized_keys.append(value)
    if not normalized_keys:
        return

    def _run_sync() -> None:
        try:
            results = google_calendar_sync.sync_google_calendar_for_sync_keys(
                normalized_keys,
                check_remote=check_remote,
                force_remote_update=force_remote_update,
            )
        except Exception as exc:
            # This callback runs only after the business transaction committed.
            # Keep the traceback without echoing remote responses/credentials.
            logger.error(
                "Google Calendar sync failed after service save (%s):\n%s",
                type(exc).__name__,
                "".join(traceback.format_tb(exc.__traceback__)),
            )
            results = [google_calendar_sync.GoogleCalendarSyncResult(
                sync_key,
                "error",
                "法要・入金の保存は完了しています。Google カレンダー同期に失敗しました。再同期してください。",
                google_calendar_sync.GoogleCalendarSyncBinding.SyncStatus.ERROR,
            ) for sync_key in normalized_keys]
        results_buffer.extend(results)

    transaction.on_commit(_run_sync)


def _flash_google_calendar_sync_messages(
    request: HttpRequest,
    results: list[google_calendar_sync.GoogleCalendarSyncResult],
    *,
    show_success: bool = False,
) -> None:
    for result in results:
        message_text = f"Google カレンダー: {result.message}"
        if result.binding_status in {
            google_calendar_sync.GoogleCalendarSyncBinding.SyncStatus.ERROR,
            google_calendar_sync.GoogleCalendarSyncBinding.SyncStatus.CONFLICT,
        }:
            messages.warning(request, message_text)
            continue
        if not show_success:
            continue
        if result.action in {"created", "updated", "deleted"}:
            messages.success(request, message_text)
        elif result.action in {"unchanged", "skipped", "disabled"}:
            messages.info(request, message_text)
