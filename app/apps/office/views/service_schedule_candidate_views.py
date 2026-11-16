from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.models import Person, RecordEditLog, ServiceSchedule
from apps.office import services
from apps.office.services import google_calendar_sync
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_service_schedule_record
from apps.office.services.service_schedule_core import (
    _apply_manual_service_schedule_defaults,
    _new_manual_service_schedule,
    _parse_prefill_date,
    _persist_manual_service_schedule_identity,
    _service_schedule_for_edit,
)
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_service_ledger_url,
    _request_actor_label,
    _resolve_next_url,
)

from .service_schedule_view_shared import (
    _flash_google_calendar_sync_messages,
    _flash_record_action_message,
    _queue_google_calendar_sync,
)

DEFAULT_FUNERAL_RECORD_NOTE = "葬儀と一緒に勤めた"


def _candidate_service_category(
    candidate_type: str,
    service_label: str | None = None,
) -> str:
    return services._service_schedule_category_for_candidate_type(candidate_type, service_label)


def _find_funeral_schedule_for_person(
    *,
    household_id: str,
    person: Person,
) -> ServiceSchedule | None:
    schedules = ServiceSchedule.objects.filter(
        household_uid=household_id,
        person_uid=person.person_uid,
        deleted_at__isnull=True,
    ).order_by("-completed_on", "-scheduled_date", "-id")
    for schedule in schedules:
        if not services._is_actual_service_schedule(schedule):
            continue
        if (
            schedule.category == ServiceSchedule.Category.FUNERAL
            or schedule.service_label == "葬儀"
        ):
            return schedule
    return None


def _funeral_record_default_completed_on(
    *,
    funeral_schedule: ServiceSchedule | None,
    target_date_text: str,
) -> str:
    completed_on = None
    if funeral_schedule is not None:
        completed_on = funeral_schedule.completed_on or funeral_schedule.scheduled_date
    completed_on = completed_on or _parse_prefill_date(target_date_text)
    return completed_on.isoformat() if completed_on is not None else ""


def _find_existing_schedule_for_candidate(
    *,
    household_id: str,
    person: Person,
    service_label: str,
    target_date_text: str,
) -> ServiceSchedule | None:
    candidate = {
        "person_id": person.person_uid,
        "label": service_label,
        "target_date": target_date_text,
    }
    schedules = [
        item
        for item in ServiceSchedule.objects.filter(
            household_uid=household_id,
            person_uid=person.person_uid,
            deleted_at__isnull=True,
        ).select_related("person", "person__deceased_profile")
        if services._is_actual_service_schedule(item)
    ]
    return services._matching_actual_schedule_for_candidate(candidate, schedules)


def cancel_memorial_candidate(request: HttpRequest, household_id: str, person_id: str) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    batch = person.batch
    active_source_id = batch.source.source_id
    service_label = (
        request.GET.get("service_label") or request.POST.get("service_label") or ""
    ).strip()
    target_date_text = (
        request.GET.get("target_date") or request.POST.get("target_date") or ""
    ).strip()
    candidate_type = (
        request.GET.get("candidate_type") or request.POST.get("candidate_type") or ""
    ).strip()
    next_url = _resolve_next_url(
        request,
        _default_service_ledger_url(),
    )
    if not service_label:
        messages.error(request, "中止記録する法要候補を特定できませんでした。")
        return redirect(next_url)

    existing_schedule = _find_existing_schedule_for_candidate(
        household_id=household_id,
        person=person,
        service_label=service_label,
        target_date_text=target_date_text,
    )
    if existing_schedule is not None:
        messages.info(request, "この法要候補はすでに記録済みです。")
        return redirect(
            _edit_url(
                "office:edit_service_schedule",
                household_id,
                existing_schedule.schedule_uid,
                source_id=active_source_id,
                next_url=next_url,
                extra_query={"source_table": existing_schedule.source_table}
                if existing_schedule.source_table
                else None,
            )
        )

    category = _candidate_service_category(candidate_type, service_label)
    candidate_label = candidate_type or "回忌"
    household_label = (
        _household_display_head_name(person.household)
        if person.household_id and person.household is not None
        else household_id
    )

    if request.method == "POST":
        cancel_note = (request.POST.get("cancel_note") or "").strip()
        change_note = cancel_note or "法要候補を中止として記録"
        sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
        with transaction.atomic():
            schedule = _new_manual_service_schedule(batch, person)
            _apply_manual_service_schedule_defaults(schedule, batch, person)
            schedule.category = category
            schedule.service_label = service_label
            schedule.subject_name = person.name
            schedule.target_date = _parse_prefill_date(target_date_text)
            schedule.scheduled_date = None
            schedule.scheduled_time = None
            schedule.completed_on = None
            schedule.location = ""
            schedule.status = ServiceSchedule.Status.CANCELLED
            schedule.notes = cancel_note
            schedule.external_calendar_ref = ""
            schedule.save()
            _persist_manual_service_schedule_identity(schedule)
            schedule = _service_schedule_for_edit(schedule.pk)
            log_entry = _create_record_edit_log(
                record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
                record=schedule,
                before_data={},
                after_data=_serialize_service_schedule_record(schedule),
                editor_label=_request_actor_label(request),
                change_note=change_note,
            )
            _queue_google_calendar_sync(
                [google_calendar_sync.google_calendar_sync_key_for_schedule(schedule)],
                results_buffer=sync_results,
            )
        _flash_record_action_message(
            request,
            log_entry,
            f"{person.name} の {service_label} を中止として記録しました。",
        )
        _flash_google_calendar_sync_messages(request, sync_results)
        return redirect(next_url)

    return render(
        request,
        "office/service_candidate_cancel_confirm.html",
        {
            "title": "法要候補を中止記録",
            "next_url": next_url,
            "person": person,
            "household_id": household_id,
            "household_label": household_label,
            "service_label": service_label,
            "target_date": target_date_text,
            "candidate_type": candidate_label,
            "category": category,
        },
    )


def record_candidate_with_funeral(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    batch = person.batch
    active_source_id = batch.source.source_id
    service_label = (
        request.GET.get("service_label") or request.POST.get("service_label") or ""
    ).strip()
    target_date_text = (
        request.GET.get("target_date") or request.POST.get("target_date") or ""
    ).strip()
    candidate_type = (
        request.GET.get("candidate_type") or request.POST.get("candidate_type") or ""
    ).strip()
    next_url = _resolve_next_url(
        request,
        _default_service_ledger_url(),
    )
    if not services._candidate_can_record_with_funeral(candidate_type, service_label):
        messages.error(request, "葬儀と一緒に記録できる候補は初七日だけです。")
        return redirect(next_url)

    existing_schedule = _find_existing_schedule_for_candidate(
        household_id=household_id,
        person=person,
        service_label=service_label,
        target_date_text=target_date_text,
    )
    if existing_schedule is not None:
        messages.info(request, "この法要候補はすでに記録済みです。")
        return redirect(
            _edit_url(
                "office:edit_service_schedule",
                household_id,
                existing_schedule.schedule_uid,
                source_id=active_source_id,
                next_url=next_url,
                extra_query={"source_table": existing_schedule.source_table}
                if existing_schedule.source_table
                else None,
            )
        )

    funeral_schedule = _find_funeral_schedule_for_person(
        household_id=household_id,
        person=person,
    )
    default_completed_on = _funeral_record_default_completed_on(
        funeral_schedule=funeral_schedule,
        target_date_text=target_date_text,
    )
    household_label = (
        _household_display_head_name(person.household)
        if person.household_id and person.household is not None
        else household_id
    )
    render_context = {
        "title": "初七日を葬儀同日として記録",
        "next_url": next_url,
        "person": person,
        "household_id": household_id,
        "household_label": household_label,
        "service_label": service_label,
        "target_date": target_date_text,
        "candidate_type": candidate_type or "中陰",
        "completed_on": default_completed_on,
        "default_note": DEFAULT_FUNERAL_RECORD_NOTE,
        "funeral_schedule": funeral_schedule,
    }

    if request.method == "POST":
        completed_on_text = (request.POST.get("completed_on") or "").strip()
        completed_on = _parse_prefill_date(completed_on_text)
        if completed_on is None:
            messages.error(request, "実施日を正しい日付で入力してください。")
            render_context["completed_on"] = completed_on_text
            render_context["default_note"] = (
                request.POST.get("record_note") or DEFAULT_FUNERAL_RECORD_NOTE
            )
            return render(
                request,
                "office/service_candidate_funeral_confirm.html",
                render_context,
            )

        record_note = (request.POST.get("record_note") or "").strip() or DEFAULT_FUNERAL_RECORD_NOTE
        change_note = record_note or "初七日を葬儀同日として記録"
        sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
        with transaction.atomic():
            schedule = _new_manual_service_schedule(batch, person)
            _apply_manual_service_schedule_defaults(schedule, batch, person)
            schedule.category = _candidate_service_category(candidate_type, service_label)
            schedule.service_label = service_label
            schedule.subject_name = person.name
            schedule.target_date = _parse_prefill_date(target_date_text)
            schedule.scheduled_date = completed_on
            schedule.scheduled_time = (
                funeral_schedule.scheduled_time if funeral_schedule is not None else None
            )
            schedule.completed_on = completed_on
            schedule.location = funeral_schedule.location if funeral_schedule is not None else ""
            schedule.status = ServiceSchedule.Status.COMPLETED
            schedule.notes = record_note
            schedule.external_calendar_ref = ""
            schedule.save()
            _persist_manual_service_schedule_identity(schedule)
            schedule = _service_schedule_for_edit(schedule.pk)
            log_entry = _create_record_edit_log(
                record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
                record=schedule,
                before_data={},
                after_data=_serialize_service_schedule_record(schedule),
                editor_label=_request_actor_label(request),
                change_note=change_note,
            )
            _queue_google_calendar_sync(
                [google_calendar_sync.google_calendar_sync_key_for_schedule(schedule)],
                results_buffer=sync_results,
            )
        _flash_record_action_message(
            request,
            log_entry,
            f"{person.name} の {service_label} を葬儀と一緒に勤めた記録として保存しました。",
        )
        _flash_google_calendar_sync_messages(request, sync_results)
        return redirect(next_url)

    return render(
        request,
        "office/service_candidate_funeral_confirm.html",
        render_context,
    )
