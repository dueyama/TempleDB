from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404

from apps.imports.models import ServiceSchedule
from apps.office import services
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.service_schedule_links import (
    _build_household_service_link_candidates,
    _linked_service_schedule_choices,
    _linked_service_schedule_members,
)
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _normalize_time_machine_mode,
    _resolve_next_url,
)

from .service_schedule_view_shared import (
    _completed_schedule_edit_enabled,
    _service_link_extended_lookback_requested,
    _service_link_extended_requested,
    _service_link_lookahead_years,
    _service_link_lookback_years,
    _service_schedule_supports_linking,
)


@dataclass
class ServiceScheduleEditState:
    active_source_id: str
    batch: Any
    schedule: ServiceSchedule
    source_table: str
    action: str
    next_url: str
    current_edit_url: str
    read_only_mode: bool
    time_machine_mode: bool
    actual_death_date: date | None
    target_date_label: str
    schedule_supports_linking: bool
    link_lookback_years: int
    link_lookahead_years: int
    show_3_year_links: bool
    show_10_year_links: bool
    link_candidate_category: str
    link_candidate_service_label: str
    linked_schedule_members: list[dict[str, Any]]
    linked_schedule_choices: list[tuple[str, str]]
    linked_schedule_initial: list[str]
    link_candidates: list[dict[str, Any]]
    can_delete_schedule: bool


def _service_schedule_edit_state(
    request: HttpRequest,
    *,
    household_id: str,
    event_id: str,
) -> ServiceScheduleEditState:
    schedule_uid = event_id
    source_table = request.GET.get("source_table") or request.POST.get("source_table") or ""
    _canonical_ledger_context()
    schedules = (
        ServiceSchedule.objects.select_related(
            "household",
            "person",
            "person__deceased_profile",
            "related_batch__source",
        )
        .filter(
            household_uid=household_id,
            schedule_uid=schedule_uid,
        )
    )
    if source_table:
        schedules = schedules.filter(source_table=source_table)
    schedule = get_object_or_404(schedules)
    batch = schedule.related_batch
    if batch is None:
        raise Http404("service schedule provenance batch not found")
    active_source_id = batch.source.source_id
    action = request.POST.get("action") or "save"
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    current_edit_url = _edit_url(
        "office:edit_service_schedule",
        household_id,
        schedule_uid,
        source_id=active_source_id,
        next_url=next_url,
        extra_query={"source_table": source_table} if source_table else None,
    )
    read_only_mode = not _completed_schedule_edit_enabled(request, schedule)
    time_machine_mode = _normalize_time_machine_mode(
        request.GET.get("time_machine") or request.POST.get("time_machine")
    )
    if read_only_mode:
        time_machine_mode = False
    actual_death_date = services._actual_service_schedule_death_date(schedule)
    target_date_label = (
        f"本当の命日（{schedule.service_label}）"
        if schedule.service_label
        and schedule.category
        in {
            ServiceSchedule.Category.MEMORIAL,
            ServiceSchedule.Category.CHUIN,
            ServiceSchedule.Category.HATSUBON,
            ServiceSchedule.Category.FUNERAL,
        }
        else "本当の命日"
    )
    schedule_supports_linking = _service_schedule_supports_linking(schedule)
    linked_schedule_members = (
        _linked_service_schedule_members(schedule) if schedule_supports_linking else []
    )
    linked_schedule_choices, linked_schedule_initial = (
        _linked_service_schedule_choices(schedule) if schedule_supports_linking else ([], [])
    )
    link_lookback_years = _service_link_lookback_years(request)
    link_lookahead_years = _service_link_lookahead_years(request)
    link_candidate_category = request.POST.get("category") or schedule.category
    link_candidate_service_label = request.POST.get("service_label") or schedule.service_label
    link_candidates = (
        _build_household_service_link_candidates(
            active_source_id,
            batch,
            household_id,
            primary_person_id=schedule.person_uid,
            primary_target_date=services._resolved_service_schedule_target_date(schedule)
            or actual_death_date,
            primary_category=link_candidate_category,
            primary_service_label=link_candidate_service_label,
            lookback_years=link_lookback_years,
            lookahead_years=link_lookahead_years,
        )
        if schedule_supports_linking and schedule.person_uid
        else []
    )
    return ServiceScheduleEditState(
        active_source_id=active_source_id,
        batch=batch,
        schedule=schedule,
        source_table=source_table,
        action=action,
        next_url=next_url,
        current_edit_url=current_edit_url,
        read_only_mode=read_only_mode,
        time_machine_mode=time_machine_mode,
        actual_death_date=actual_death_date,
        target_date_label=target_date_label,
        schedule_supports_linking=schedule_supports_linking,
        link_lookback_years=link_lookback_years,
        link_lookahead_years=link_lookahead_years,
        show_3_year_links=_service_link_extended_lookback_requested(request),
        show_10_year_links=_service_link_extended_requested(request),
        link_candidate_category=link_candidate_category,
        link_candidate_service_label=link_candidate_service_label,
        linked_schedule_members=linked_schedule_members,
        linked_schedule_choices=linked_schedule_choices,
        linked_schedule_initial=linked_schedule_initial,
        link_candidates=link_candidates,
        can_delete_schedule=schedule.record_origin == ServiceSchedule.Origin.IMPORTED,
    )
