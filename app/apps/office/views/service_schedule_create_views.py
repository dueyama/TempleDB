from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.forms import ServiceScheduleEditForm
from apps.imports.models import Person, ServiceSchedule
from apps.office import services
from apps.office.services import google_calendar_sync
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.record_history_urls import _edit_url
from apps.office.services.service_schedule_core import (
    _new_manual_service_schedule,
    _parse_prefill_date,
    _prepare_service_schedule_post_data,
    _service_payment_formset,
    apply_service_schedule_prefill_values,
    find_existing_memorial_candidate_schedule,
)
from apps.office.services.service_schedule_links import (
    _build_household_service_link_candidates,
)
from apps.office.services.service_schedule_save import (
    ServiceScheduleSaveOptions,
    save_service_schedule,
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
    _service_link_extended_lookback_requested,
    _service_link_extended_requested,
    _service_link_lookahead_years,
    _service_link_lookback_years,
    _service_schedule_supports_linking_values,
)


def _service_schedule_create_title(category: str | None, service_label: str | None) -> str:
    normalized_label = (service_label or "").strip()
    normalized_category = (category or "").strip()
    if normalized_label == "葬儀":
        return "葬儀予定を追加"
    if normalized_category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    }:
        return f"{dict(ServiceSchedule.Category.choices).get(normalized_category, 'イベント')}イベントを追加"
    if normalized_category == ServiceSchedule.Category.OTHER:
        return "その他イベントを追加"
    return "法要予定を追加"


def create_service_schedule(request: HttpRequest, household_id: str, person_id: str) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    batch = person.batch
    active_source_id = batch.source.source_id
    next_url = _resolve_next_url(
        request,
        _default_service_ledger_url(),
    )
    if request.method == "GET":
        existing = find_existing_memorial_candidate_schedule(
            person,
            category=request.GET.get("category") or "",
            service_label=request.GET.get("service_label") or "",
            target_date=request.GET.get("target_date") or "",
        )
        if existing is not None:
            return redirect(_edit_url(
                "office:edit_service_schedule", household_id, existing.schedule_uid,
                source_id=active_source_id, next_url=next_url,
                extra_query={"source_table": existing.source_table},
            ))
    schedule = _new_manual_service_schedule(batch, person)
    if request.method == "GET":
        apply_service_schedule_prefill_values(
            schedule,
            category=request.GET.get("category") or "",
            service_label=request.GET.get("service_label") or "",
            target_date=request.GET.get("target_date") or "",
        )
    display_category = (
        (request.POST.get("category") or "").strip()
        if request.method == "POST"
        else (schedule.category or "").strip()
    )
    display_service_label = (
        (request.POST.get("service_label") or "").strip()
        if request.method == "POST"
        else (schedule.service_label or "").strip()
    )
    target_date_label = (
        f"本当の命日（{display_service_label}）"
        if display_service_label and display_category in {
            ServiceSchedule.Category.MEMORIAL,
            ServiceSchedule.Category.CHUIN,
            ServiceSchedule.Category.HATSUBON,
            ServiceSchedule.Category.FUNERAL,
        }
        else "本当の命日"
    )
    actual_death_date = services._actual_service_schedule_death_date(schedule)
    primary_target_date = (
        _parse_prefill_date(request.POST.get("target_date"))
        or _parse_prefill_date(request.GET.get("target_date"))
        or services._resolved_service_schedule_target_date(schedule)
    )
    link_candidate_category = request.POST.get("category") or schedule.category
    link_candidate_service_label = request.POST.get("service_label") or schedule.service_label
    schedule_supports_linking = _service_schedule_supports_linking_values(
        link_candidate_category,
        link_candidate_service_label,
    )
    link_lookback_years = _service_link_lookback_years(request)
    link_lookahead_years = _service_link_lookahead_years(request)
    show_3_year_links = _service_link_extended_lookback_requested(request)
    show_10_year_links = _service_link_extended_requested(request)
    link_candidates = (
        _build_household_service_link_candidates(
            active_source_id,
            batch,
            household_id,
            primary_person_id=person.person_uid,
            primary_target_date=primary_target_date,
            primary_category=link_candidate_category,
            primary_service_label=link_candidate_service_label,
            lookback_years=link_lookback_years,
            lookahead_years=link_lookahead_years,
        )
        if schedule_supports_linking
        else []
    )
    selectable_link_candidates = [
        item for item in link_candidates if item.get("is_selectable", True)
    ]
    completed_link_candidates = [
        item for item in link_candidates if not item.get("is_selectable", True)
    ]

    if request.method == "POST":
        form_data = _prepare_service_schedule_post_data(request.POST, request.POST.get("action") or "save")
        form_supports_linking = _service_schedule_supports_linking_values(
            form_data.get("category"),
            form_data.get("service_label"),
        )
        payment_formset = _service_payment_formset(data=request.POST, schedule=schedule)
        form = ServiceScheduleEditForm(
            form_data,
            instance=schedule,
            link_candidate_choices=[
                (item["token"], item["display_label"]) for item in selectable_link_candidates
            ],
            completed_link_candidate_choices=[
                (item["token"], item["display_label"]) for item in completed_link_candidates
            ],
            show_link_range_toggle=form_supports_linking,
            show_3_year_links_initial=show_3_year_links,
            show_10_year_links_initial=show_10_year_links,
            show_link_candidates=form_supports_linking and bool(selectable_link_candidates),
            show_completed_link_candidates=form_supports_linking
            and bool(completed_link_candidates),
            target_date_initial=actual_death_date,
            target_date_label=target_date_label,
        )
        if form.is_valid() and payment_formset.is_valid():
            sync_results: list[google_calendar_sync.GoogleCalendarSyncResult] = []
            with transaction.atomic():
                schedule = form.save(commit=False)
                payment_formset.instance = schedule
                result = save_service_schedule(
                    schedule,
                    batch=batch,
                    person=person,
                    source_id=active_source_id,
                    options=ServiceScheduleSaveOptions(
                        supports_linking=_service_schedule_supports_linking_values(
                            schedule.category, schedule.service_label,
                        ),
                        link_candidates=link_candidates,
                        linked_candidate_tokens=form.cleaned_data.get("linked_candidate_tokens", []),
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
                    f"法要予定 {schedule.service_label or schedule.schedule_uid} を登録しました。"
                    + (
                        f" 一緒に勤める対象 {len(result.linked_created)} 件もリンクしました。"
                        if result.linked_created
                        else ""
                    )
                    + (
                        f" 入金履歴 {len(result.payment_logs)} 件を記録しました。"
                        if result.payment_logs
                        else ""
                    )
                ),
            )
            _flash_google_calendar_sync_messages(request, sync_results)
            return redirect(next_url)
    else:
        form = ServiceScheduleEditForm(
            instance=schedule,
            link_candidate_choices=[
                (item["token"], item["display_label"]) for item in selectable_link_candidates
            ],
            completed_link_candidate_choices=[
                (item["token"], item["display_label"]) for item in completed_link_candidates
            ],
            show_link_range_toggle=schedule_supports_linking,
            show_3_year_links_initial=show_3_year_links,
            show_10_year_links_initial=show_10_year_links,
            show_link_candidates=schedule_supports_linking and bool(selectable_link_candidates),
            show_completed_link_candidates=schedule_supports_linking
            and bool(completed_link_candidates),
            target_date_initial=actual_death_date,
            target_date_label=target_date_label,
        )
        payment_formset = _service_payment_formset(schedule=schedule)

    return render(
        request,
        "office/record_edit.html",
        {
            "title": _service_schedule_create_title(display_category, display_service_label),
            "subtitle": f"{person.name or person.person_uid} / {_household_display_head_name(person.household) if person.household_id else household_id}",
            "form": form,
            "next_url": next_url,
            "editor_label": _request_actor_label(request),
            "change_note": request.POST.get("change_note", ""),
            "record_deleted": False,
            "deleted_meta": {},
            "history_entries": [],
            "linked_schedule_members": [],
            "can_delete": False,
            "submit_label": "登録",
            "show_complete_save_action": display_service_label == "臨終勤行",
            "payment_formset": payment_formset,
            "payment_summary": [],
            "service_schedule_title_autofill": True,
        },
    )
