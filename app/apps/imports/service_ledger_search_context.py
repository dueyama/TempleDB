from __future__ import annotations

from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.utils import OperationalError, ProgrammingError

from . import synthetic_household_runtime
from .memorial_shared import _effective_memorial_rules
from .runtime_shared import _search_text

CANDIDATE_PAGE_SIZE = 40


def _runtime_module():
    from . import service_ledger_runtime

    return service_ledger_runtime


def _legacy_build_service_ledger_context(
    source_id: str | None = None,
    query: str = "",
    *,
    candidate_page: int | str = 1,
) -> dict:
    from . import service_ledger_context_sources, service_ledger_event_groups

    runtime = _runtime_module()
    source_context = service_ledger_context_sources._resolve_service_ledger_source_context(source_id)
    active_source_id = source_context["active_source_id"]
    context_source = source_context["source"]
    context_registered_sources = source_context["registered_sources"]

    loaded = service_ledger_context_sources._load_service_ledger_dataset_and_schedules(active_source_id)
    if not loaded["available"]:
        return service_ledger_context_sources._service_ledger_unavailable_context(
            active_source_id=active_source_id,
            context_source=context_source,
            query=query,
            message=loaded["message"],
            latest_export=loaded["latest_export"],
        )

    dataset = loaded["dataset"]
    batch = loaded["latest_batch"]
    schedules = loaded["schedules"]
    latest_export = loaded["latest_export"]

    today = date.today()
    overdue_period_start = today - timedelta(days=183)
    past_unperformed_period_start = today - timedelta(days=365)
    past_unperformed_period_end = today - timedelta(days=1)
    next_week_period_end = today + timedelta(days=6)
    future_period_end = today + timedelta(days=365)
    candidate_period_end = future_period_end
    needle = _search_text(query)
    all_schedule_entries = [
        runtime._service_ledger_schedule_entry(
            schedule,
            today=today,
            overdue_period_start=overdue_period_start,
        )
        for schedule in schedules
        if runtime._is_actual_service_schedule(schedule)
    ]
    schedule_entries = all_schedule_entries
    if needle:
        schedule_entries = [
            entry for entry in schedule_entries if runtime._service_ledger_schedule_matches(entry, needle)
        ]
    event_groups = service_ledger_event_groups._build_service_ledger_event_groups(
        schedule_entries,
        today=today,
        overdue_period_start=overdue_period_start,
        past_unperformed_period_start=past_unperformed_period_start,
        next_week_period_end=next_week_period_end,
        future_period_end=future_period_end,
    )

    from .household_memorial_candidate_members import _decorate_memorial_members

    memorial_members = [
        member
        for detail in dataset["household_details"].values()
        for member in _decorate_memorial_members(
            runtime._notice_eligible_memorial_members(detail), [], today, candidate_period_end,
            detail.get("events", []),
        )
    ]
    memorial_rules = _effective_memorial_rules(dataset.get("memorial_rules", []))
    candidate_entries = runtime._build_memorial_candidates(
        memorial_members,
        memorial_rules,
        today,
        candidate_period_end,
    )
    candidate_entries = [
        entry
        for entry in candidate_entries
        if not runtime._candidate_already_has_actual_schedule(entry, all_schedule_entries)
    ]
    if needle:
        candidate_entries = [
            entry for entry in candidate_entries if runtime._service_ledger_candidate_matches(entry, needle)
        ]
    candidate_pagination = Paginator(candidate_entries, CANDIDATE_PAGE_SIZE).get_page(candidate_page)
    candidate_card_entries = [
        runtime._service_ledger_candidate_entry(
            entry,
            today=today,
            overdue_period_start=overdue_period_start,
        )
        for entry in candidate_pagination
    ]
    past_unperformed_candidate_entries = []
    if past_unperformed_period_end >= past_unperformed_period_start:
        past_unperformed_candidate_entries = runtime._build_memorial_candidates(
            memorial_members,
            memorial_rules,
            past_unperformed_period_start,
            past_unperformed_period_end,
        )
        past_unperformed_candidate_entries = [
            entry
            for entry in past_unperformed_candidate_entries
            if not runtime._candidate_already_has_actual_schedule(entry, all_schedule_entries)
        ]
        if needle:
            past_unperformed_candidate_entries = [
                entry
                for entry in past_unperformed_candidate_entries
                if runtime._service_ledger_candidate_matches(entry, needle)
            ]
    past_unperformed_candidate_card_entries = [
        runtime._service_ledger_candidate_entry(
            entry,
            today=today,
            overdue_period_start=overdue_period_start,
        )
        for entry in past_unperformed_candidate_entries
    ]
    past_unperformed_entries = sorted(
        [
            *event_groups["past_unperformed_events"],
            *past_unperformed_candidate_card_entries,
        ],
        key=lambda item: (
            item.get("scheduled_date_value")
            or item.get("target_date_value")
            or past_unperformed_period_start,
            item.get("scheduled_time_sort", ""),
            _search_text(item.get("household_name", "")),
            _search_text(item.get("person_name", "")),
            _search_text(item.get("service_label", "")),
        ),
        reverse=True,
    )

    service_targets: list[dict] = []
    if needle:
        try:
            persons = service_ledger_context_sources._load_service_target_people_or_empty(batch)
        except (OperationalError, ProgrammingError):
            persons = []
        profile_map = synthetic_household_runtime.household_profile_map_for_households(
            active_source_id,
            [person.household.household_uid for person in persons],
        )
        service_targets = [
            entry
            for entry in (
                runtime._service_target_person_entry(person)
                for person in persons
                if runtime._person_is_service_target(person)
                and not synthetic_household_runtime.is_yuen_person_hidden_from_service_target_search(
                    person,
                    profile_map.get(person.household.household_uid),
                )
            )
            if runtime._service_target_person_matches(entry, needle)
        ]
    search_result_count = (
        len(event_groups["scheduled_events"])
        + len(event_groups["recent_completed_events"])
        + len(candidate_entries)
        + len(event_groups["overdue_events"])
        + len(event_groups["unscheduled_events"])
        + len(past_unperformed_entries)
        + len(service_targets)
    )

    return {
        "available": True,
        "selected_source_id": active_source_id,
        "registered_sources": context_registered_sources,
        "source": context_source,
        "latest_export": latest_export,
        "latest_batch": batch,
        "canonical_snapshot_id": batch.prepared_snapshot_id or "",
        "query": query,
        **event_groups,
        "service_target_results": service_targets[:30],
        "candidate_entries": candidate_pagination.object_list,
        "candidate_card_entries": candidate_card_entries,
        "candidate_count": len(candidate_entries),
        "candidate_pagination": candidate_pagination,
        "past_unperformed_entries": past_unperformed_entries,
        "past_unperformed_candidate_entries": past_unperformed_candidate_entries,
        "past_unperformed_count": len(past_unperformed_entries),
        "candidate_period_from": today.isoformat(),
        "candidate_period_to": candidate_period_end.isoformat(),
        "candidate_help_text": (
            f"{today.isoformat()} から {candidate_period_end.isoformat()} の今後1年の範囲で、"
            "命日からその場で計算しています。登録済みの法要は候補から除きます。"
            f"命日基準日が近い順に1ページ{CANDIDATE_PAGE_SIZE}件ずつ表示します。"
            f"続きは「次の{CANDIDATE_PAGE_SIZE}件」で確認できます。"
        ),
        "overdue_period_from": overdue_period_start.isoformat(),
        "past_unperformed_period_from": past_unperformed_period_start.isoformat(),
        "past_unperformed_period_to": past_unperformed_period_end.isoformat(),
        "next_week_period_to": next_week_period_end.isoformat(),
        "future_period_to": future_period_end.isoformat(),
        "next_week_count": len(event_groups["next_week_events"]),
        "scheduled_count": len(event_groups["scheduled_events"]),
        "upcoming_count": len(event_groups["upcoming_events"]),
        "unscheduled_count": len(event_groups["unscheduled_events"]),
        "overdue_count": len(event_groups["overdue_events"]),
        "completed_count": len(event_groups["recent_completed_events"]),
        "active_count": len([entry for entry in schedule_entries if not entry["is_done"]]),
        "service_target_count": len(service_targets),
        "search_result_count": search_result_count,
        "today_label": today.strftime("%Y-%m-%d"),
        "today_count": len(event_groups["today_events"]),
    }
