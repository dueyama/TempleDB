from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from apps.imports.models import RecordEditLog, ServiceSchedule
from apps.office.forms_funeral import FuneralScheduleEditForm
from apps.office.services import google_calendar_sync
from apps.office.services.offering_payments import snapshot_service_schedule_payments
from apps.office.services.record_history_snapshot import (
    _deleted_meta,
    _serialize_service_schedule_record,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options,
    _recent_record_history,
)
from apps.office.services.service_schedule_core import (
    _prepare_service_schedule_post_data,
    _service_payment_formset,
    _service_payment_summary,
)
from apps.office.services.service_schedule_printing import _service_schedule_print_url
from apps.office.services.service_schedule_save import (
    ServiceScheduleSaveOptions,
    ServiceScheduleSaveSnapshot,
    save_service_schedule,
)
from apps.office.web_support import (
    _google_calendar_settings_url,
    _request_actor_label,
    _time_machine_toggle_url,
)

from .service_schedule_edit_state import ServiceScheduleEditState
from .service_schedule_view_shared import (
    _completed_schedule_enable_edit_url,
    _disable_bound_form_fields,
    _disable_payment_formset_fields,
    _flash_google_calendar_sync_messages,
    _flash_record_action_message,
    _queue_google_calendar_sync,
    _service_schedule_supports_linking,
    _service_schedule_supports_linking_values,
)


def _build_service_schedule_edit_form_bundle(
    request: HttpRequest,
    state: ServiceScheduleEditState,
) -> dict[str, object]:
    selectable_link_candidates = [
        item for item in state.link_candidates if item.get("is_selectable", True)
    ]
    completed_link_candidates = [
        item for item in state.link_candidates if not item.get("is_selectable", True)
    ]
    if request.method == "POST":
        form_data = _prepare_service_schedule_post_data(request.POST, state.action)
        form_supports_linking = _service_schedule_supports_linking_values(
            form_data.get("category"),
            form_data.get("service_label"),
        )
        before_payment_snapshots, before_payment_records = snapshot_service_schedule_payments(
            state.schedule
        )
        bundle = {
            "existing_link_group_key": state.schedule.link_group_key or "",
            "existing_sync_key": google_calendar_sync.google_calendar_sync_key_for_schedule(
                state.schedule
            ),
            "before_data": _serialize_service_schedule_record(state.schedule),
            "before_payment_snapshots": before_payment_snapshots,
            "before_payment_records": before_payment_records,
        }
        payment_formset = _service_payment_formset(data=request.POST, schedule=state.schedule)
        form = FuneralScheduleEditForm(
            form_data,
            instance=state.schedule,
            link_candidate_choices=[
                (item["token"], item["display_label"]) for item in selectable_link_candidates
            ],
            completed_link_candidate_choices=[
                (item["token"], item["display_label"]) for item in completed_link_candidates
            ],
            show_link_range_toggle=form_supports_linking,
            show_3_year_links_initial=state.show_3_year_links,
            show_10_year_links_initial=state.show_10_year_links,
            show_link_candidates=form_supports_linking and bool(selectable_link_candidates),
            show_completed_link_candidates=form_supports_linking
            and bool(completed_link_candidates),
            linked_schedule_choices=state.linked_schedule_choices,
            linked_schedule_initial=state.linked_schedule_initial,
            show_linked_schedule_choices=form_supports_linking
            and bool(state.linked_schedule_choices),
            show_apply_to_linked_group=form_supports_linking
            and bool(state.schedule.link_group_key),
            target_date_initial=state.actual_death_date,
            target_date_label=state.target_date_label,
        )
    else:
        bundle = {}
        payment_formset = _service_payment_formset(schedule=state.schedule)
        form = FuneralScheduleEditForm(
            instance=state.schedule,
            link_candidate_choices=[
                (item["token"], item["display_label"]) for item in selectable_link_candidates
            ],
            completed_link_candidate_choices=[
                (item["token"], item["display_label"]) for item in completed_link_candidates
            ],
            show_link_range_toggle=state.schedule_supports_linking,
            show_3_year_links_initial=state.show_3_year_links,
            show_10_year_links_initial=state.show_10_year_links,
            show_link_candidates=state.schedule_supports_linking
            and bool(selectable_link_candidates),
            show_completed_link_candidates=state.schedule_supports_linking
            and bool(completed_link_candidates),
            linked_schedule_choices=state.linked_schedule_choices,
            linked_schedule_initial=state.linked_schedule_initial,
            show_linked_schedule_choices=state.schedule_supports_linking
            and bool(state.linked_schedule_choices),
            show_apply_to_linked_group=state.schedule_supports_linking
            and bool(state.schedule.link_group_key),
            target_date_initial=state.actual_death_date,
            target_date_label=state.target_date_label,
        )
    if state.read_only_mode:
        _disable_bound_form_fields(form)
        _disable_payment_formset_fields(payment_formset)
    bundle["form"] = form
    bundle["payment_formset"] = payment_formset
    return bundle


def _save_service_schedule_edit_form(
    request: HttpRequest,
    state: ServiceScheduleEditState,
    bundle: dict[str, object],
) -> HttpResponse | None:
    if request.method != "POST":
        return None
    form = bundle["form"]
    payment_formset = bundle["payment_formset"]
    if not form.is_valid() or not payment_formset.is_valid():
        return None

    sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
    with transaction.atomic():
        schedule = form.save(commit=False)
        payment_formset.instance = schedule
        result = save_service_schedule(
            schedule,
            batch=state.batch,
            person=schedule.person,
            source_id=state.active_source_id,
            options=ServiceScheduleSaveOptions(
                supports_linking=_service_schedule_supports_linking(schedule),
                link_candidates=state.link_candidates,
                linked_candidate_tokens=form.cleaned_data.get("linked_candidate_tokens", []),
                linked_schedule_ids=form.cleaned_data.get("linked_schedule_ids", []),
                reset_unlinked_schedules=bool(
                    form.cleaned_data.get("reset_unlinked_schedules", False)
                ),
                apply_to_linked_group=bool(form.cleaned_data.get("apply_to_linked_group", False)),
                include_first_seventh=bool(form.cleaned_data.get("include_first_seventh", False)),
            ),
            snapshot=ServiceScheduleSaveSnapshot(
                before_data=bundle["before_data"],
                payment_snapshots=bundle["before_payment_snapshots"],
                payment_records=bundle["before_payment_records"],
                link_group_key=str(bundle["existing_link_group_key"]),
                sync_key=str(bundle["existing_sync_key"]),
            ),
            persist_payments=payment_formset.save,
            editor_label=_request_actor_label(request),
            change_note=request.POST.get("change_note", ""),
        )
        _queue_google_calendar_sync(
            result.sync_keys,
            results_buffer=sync_results,
        )
    schedule = result.schedule
    _flash_record_action_message(
        request,
        result.log_entry,
        (
            (
                f"予定レコード {schedule.schedule_uid} を完了として保存しました。"
                if state.action == "complete_save"
                else f"予定レコード {schedule.schedule_uid} を更新しました。"
            )
            + (f" リンク法要 {len(result.linked_logs)} 件にも反映しました。" if result.linked_logs else "")
            + (
                f" 一緒に勤める対象 {len(result.linked_created)} 件を追加しました。"
                if result.linked_created
                else ""
            )
            + (f" リンク解除 {len(result.unlinked_logs)} 件。" if result.unlinked_logs else "")
            + (f" 入金履歴 {len(result.payment_logs)} 件。" if result.payment_logs else "")
        ),
    )
    _flash_google_calendar_sync_messages(request, sync_results)
    return redirect(state.next_url)


def _build_service_schedule_edit_render_context(
    request: HttpRequest,
    state: ServiceScheduleEditState,
    *,
    form,
    payment_formset,
) -> dict[str, object]:
    time_machine_field_options = (
        _build_time_machine_field_options(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record_id=state.schedule.pk,
            form=form,
        )
        if state.time_machine_mode
        else {}
    )
    google_calendar_sync_status = google_calendar_sync.build_service_schedule_google_calendar_sync_status(
        state.schedule
    )
    return {
        "title": "予定レコードを編集",
        "subtitle": (
            f"{state.schedule.service_label or state.schedule.schedule_uid}"
            f" / 法要ID {state.schedule.schedule_uid}"
            f" / 台帳ID {state.schedule.household_uid}"
        ),
        "form": form,
        "next_url": state.next_url,
        "editor_label": _request_actor_label(request),
        "change_note": request.POST.get("change_note", ""),
        "read_only_mode": state.read_only_mode,
        "enable_edit_url": (
            _completed_schedule_enable_edit_url(request) if state.read_only_mode else ""
        ),
        "preserve_edit_mode": state.schedule.status == ServiceSchedule.Status.COMPLETED
        and not state.read_only_mode,
        "extra_hidden_fields": {"source_table": state.source_table},
        "record_deleted": state.schedule.is_deleted,
        "deleted_meta": _deleted_meta(state.schedule),
        "history_entries": _recent_record_history(
            RecordEditLog.RecordType.SERVICE_SCHEDULE,
            state.schedule.pk,
        ),
        "linked_schedule_members": state.linked_schedule_members,
        "print_url": _service_schedule_print_url(
            state.schedule,
            source_id=state.active_source_id,
            next_url=state.next_url,
            source_table=state.source_table,
        ),
        "show_complete_save_action": not state.schedule.is_deleted,
        "show_reset_schedule_action": not state.schedule.is_deleted,
        "can_delete": state.can_delete_schedule,
        "delete_button_label": "この旧予定を削除" if state.can_delete_schedule else "削除",
        "delete_confirm_text": (
            "この旧DB由来の予定を削除済みにします。よろしいですか？"
            if state.can_delete_schedule
            else "このレコードを削除済みにします。よろしいですか？"
        ),
        "payment_formset": payment_formset,
        "payment_summary": _service_payment_summary(state.schedule),
        "time_machine_mode": state.time_machine_mode,
        "time_machine_toggle_url": _time_machine_toggle_url(
            request,
            enabled=not state.time_machine_mode,
        ),
        "time_machine_field_options": time_machine_field_options,
        "google_calendar_sync_status": google_calendar_sync_status,
        "google_calendar_can_resync": request.user.is_superuser,
        "google_calendar_settings_url": _google_calendar_settings_url()
        if request.user.is_superuser
        else "",
    }
