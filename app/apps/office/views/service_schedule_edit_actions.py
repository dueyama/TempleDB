from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from apps.imports.models import RecordEditLog
from apps.office.services import google_calendar_sync
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    perform_record_delete_action,
)
from apps.office.services.record_history_snapshot import _serialize_service_schedule_record
from apps.office.services.service_schedule_core import _service_schedule_for_edit
from apps.office.services.service_schedule_lifecycle import (
    _is_manual_service_schedule,
    _manual_service_schedule_has_blocking_relations,
    _reset_service_schedule_planning_fields,
    _soft_delete_service_schedule,
)
from apps.office.web_support import _request_actor_label

from .service_schedule_edit_state import ServiceScheduleEditState
from .service_schedule_view_shared import (
    _completed_schedule_enable_edit_url,
    _flash_google_calendar_sync_messages,
    _flash_record_action_message,
    _queue_google_calendar_sync,
)


def _handle_service_schedule_special_post_actions(
    request: HttpRequest,
    state: ServiceScheduleEditState,
) -> HttpResponse | None:
    if request.method != "POST":
        return None
    if state.action == "resync_google_calendar":
        return _handle_google_calendar_resync_action(request, state)
    if state.read_only_mode:
        return redirect(_completed_schedule_enable_edit_url(request))
    if state.action in {"delete", "restore"}:
        response = _handle_delete_restore_action(request, state)
        if response is not None:
            return response
    if state.action == "reset_schedule":
        return _handle_reset_schedule_action(request, state)
    return None


def _handle_google_calendar_resync_action(
    request: HttpRequest,
    state: ServiceScheduleEditState,
) -> HttpResponse:
    if not request.user.is_superuser:
        messages.error(request, "Google カレンダー再同期は管理者だけ実行できます。")
        return redirect(state.current_edit_url)
    sync_results = google_calendar_sync.sync_google_calendar_for_schedule_ids(
        [state.schedule.pk],
        check_remote=True,
        force_remote_update=True,
    )
    _flash_google_calendar_sync_messages(request, sync_results, show_success=True)
    return redirect(state.current_edit_url)


def _handle_delete_restore_action(
    request: HttpRequest,
    state: ServiceScheduleEditState,
) -> HttpResponse | None:
    affected_sync_keys = [google_calendar_sync.google_calendar_sync_key_for_schedule(state.schedule)]
    if not state.can_delete_schedule:
        messages.warning(
            request,
            "手入力した法要予定は削除できません。必要ならリセットするか、状態を調整してください。",
        )
        return redirect(state.current_edit_url)
    delete_outcome = perform_record_delete_action(
        action=state.action,
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=state.schedule,
        serializer=_serialize_service_schedule_record,
        refresh=_service_schedule_for_edit,
        editor_label=_request_actor_label(request),
        change_note=request.POST.get("change_note", ""),
        deleted_message=f"予定レコード {state.schedule.schedule_uid} を削除済みにしました。",
        restored_message=f"予定レコード {state.schedule.schedule_uid} を復元しました。",
    )
    if delete_outcome is None:
        return None
    messages.success(request, delete_outcome.user_message)
    sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
    _queue_google_calendar_sync(affected_sync_keys, results_buffer=sync_results)
    _flash_google_calendar_sync_messages(request, sync_results)
    return redirect(state.current_edit_url)


def _handle_reset_schedule_action(
    request: HttpRequest,
    state: ServiceScheduleEditState,
) -> HttpResponse:
    change_note = request.POST.get("change_note", "") or "法要予定をリセット"
    affected_sync_keys = [google_calendar_sync.google_calendar_sync_key_for_schedule(state.schedule)]
    if _is_manual_service_schedule(state.schedule):
        if _manual_service_schedule_has_blocking_relations(state.schedule):
            messages.error(
                request,
                "入金または訪問メモが紐づいているため、この手入力法要は予定リセットできません。",
            )
            return redirect(state.current_edit_url)
        sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
        with transaction.atomic():
            schedule, log_entry = _soft_delete_service_schedule(
                state.schedule,
                editor_label=_request_actor_label(request),
                change_note=change_note,
            )
            _queue_google_calendar_sync(
                affected_sync_keys,
                results_buffer=sync_results,
            )
        _flash_record_action_message(
            request,
            log_entry,
            f"手入力法要 {schedule.schedule_uid} を削除しました。",
        )
        _flash_google_calendar_sync_messages(request, sync_results)
        return redirect(state.next_url)

    before_data = _serialize_service_schedule_record(state.schedule)
    sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
    with transaction.atomic():
        _reset_service_schedule_planning_fields(state.schedule)
        state.schedule.save(
            update_fields=[
                "scheduled_date",
                "scheduled_time",
                "completed_on",
                "location",
                "status",
                "external_calendar_ref",
                "updated_at",
            ]
        )
        schedule = _service_schedule_for_edit(state.schedule.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=schedule,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(schedule),
            editor_label=_request_actor_label(request),
            change_note=request.POST.get("change_note", ""),
            action_kind=RecordEditLog.ActionKind.RESET_SCHEDULE,
        )
        _queue_google_calendar_sync(
            affected_sync_keys,
            results_buffer=sync_results,
        )
    _flash_record_action_message(
        request,
        log_entry,
        f"予定レコード {schedule.schedule_uid} を未設定に戻しました。",
    )
    _flash_google_calendar_sync_messages(request, sync_results)
    return redirect(state.next_url)
