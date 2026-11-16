from __future__ import annotations

from datetime import date, timedelta

from .models import ServiceSchedule
from .runtime_shared import _parse_iso_date, _sort_text


def _runtime_module():
    from . import service_ledger_runtime

    return service_ledger_runtime


def build_home_service_schedule_summary(
    source_id: str | None = None,
    *,
    latest_export: dict | None = None,
    batch=None,
    canonical_population_checked: bool = False,
) -> dict:
    from . import service_ledger_context_sources

    resolved = service_ledger_context_sources._resolve_home_service_ledger_batch(
        source_id,
        latest_export=latest_export,
        batch=batch,
        canonical_population_checked=canonical_population_checked,
    )
    if not resolved["available"]:
        return {
            "available": False,
            "today_label": "",
            "today_count": 0,
            "next_count": 0,
            "overdue_count": 0,
            "today_events": [],
            "next_events": [],
            "overdue_events": [],
        }
    loaded = service_ledger_context_sources._load_home_service_ledger_schedules(
        resolved["latest_batch"]
    )
    if not loaded["available"]:
        return {
            "available": False,
            "today_label": "",
            "today_count": 0,
            "next_count": 0,
            "overdue_count": 0,
            "today_events": [],
            "next_events": [],
            "overdue_events": [],
        }
    runtime = _runtime_module()
    today = date.today()
    overdue_period_start = today - timedelta(days=183)
    next_week_period_end = today + timedelta(days=6)
    future_period_end = today + timedelta(days=365)
    schedule_entries = [
        runtime._service_ledger_schedule_entry(
            schedule,
            today=today,
            overdue_period_start=overdue_period_start,
        )
        for schedule in loaded["schedules"]
        if runtime._is_actual_service_schedule(schedule)
    ]
    event_groups = _build_service_ledger_event_groups(
        schedule_entries,
        today=today,
        overdue_period_start=overdue_period_start,
        next_week_period_end=next_week_period_end,
        future_period_end=future_period_end,
    )
    next_events = []
    for entry in event_groups["next_week_events"]:
        if entry.get("is_today"):
            continue
        scheduled_date = _parse_iso_date(entry.get("scheduled_date"))
        days_until = (scheduled_date - today).days if scheduled_date is not None else None
        next_events.append(
            {
                **entry,
                "days_until": days_until,
                "days_until_label": f"{days_until}日後" if days_until is not None else "",
            }
        )
        if len(next_events) >= 4:
            break
    today_events = list(event_groups["today_events"])[:4]
    overdue_events = list(event_groups["overdue_events"])[:4]
    return {
        "available": True,
        "today_label": today.strftime("%Y-%m-%d"),
        "today_count": len(today_events),
        "next_count": len(next_events),
        "overdue_count": len(overdue_events),
        "today_events": today_events,
        "next_events": next_events,
        "overdue_events": overdue_events,
    }


def _build_service_ledger_event_groups(
    schedule_entries: list[dict],
    *,
    today: date,
    overdue_period_start: date,
    next_week_period_end: date,
    future_period_end: date,
    past_unperformed_period_start: date | None = None,
) -> dict:
    runtime = _runtime_module()
    if past_unperformed_period_start is None:
        past_unperformed_period_start = today - timedelta(days=365)
    next_week_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry["scheduled_date_value"] is not None
            and today <= entry["scheduled_date_value"] <= next_week_period_end
            and not entry["is_done"]
        ],
        key=lambda item: (
            item["scheduled_date_value"] or next_week_period_end,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
    )
    next_week_events = runtime._collapse_linked_service_entries(next_week_events)
    scheduled_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry["scheduled_date_value"] is not None
            and today <= entry["scheduled_date_value"] <= future_period_end
            and not entry["is_done"]
        ],
        key=lambda item: (
            item["scheduled_date_value"] or future_period_end,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
    )
    scheduled_events = runtime._collapse_linked_service_entries(scheduled_events)
    today_events = [
        entry for entry in scheduled_events if entry["scheduled_date_value"] == today
    ]
    upcoming_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry["scheduled_date_value"] is not None
            and next_week_period_end < entry["scheduled_date_value"] <= future_period_end
            and not entry["is_done"]
        ],
        key=lambda item: (
            item["scheduled_date_value"] or future_period_end,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
    )
    upcoming_events = runtime._collapse_linked_service_entries(upcoming_events)
    unscheduled_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry["scheduled_date_value"] is None and not entry["is_done"]
        ],
        key=lambda item: (
            _sort_text(item["household_name"]),
            _sort_text(item["person_name"]),
            _sort_text(item["service_label"]),
        ),
    )
    unscheduled_events = runtime._collapse_linked_service_entries(unscheduled_events)
    overdue_events = sorted(
        [entry for entry in schedule_entries if entry["is_overdue"]],
        key=lambda item: (
            item["scheduled_date_value"] or overdue_period_start,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
        reverse=True,
    )
    overdue_events = runtime._collapse_linked_service_entries(overdue_events)
    past_unperformed_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry["scheduled_date_value"] is not None
            and past_unperformed_period_start <= entry["scheduled_date_value"] < today
            and not entry["is_done"]
        ],
        key=lambda item: (
            item["scheduled_date_value"] or past_unperformed_period_start,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
        reverse=True,
    )
    past_unperformed_events = runtime._collapse_linked_service_entries(past_unperformed_events)
    recent_completed_events = sorted(
        [
            entry
            for entry in schedule_entries
            if entry.get("effective_status") == ServiceSchedule.Status.COMPLETED
        ],
        key=lambda item: (
            item["completed_on_value"] or item["scheduled_date_value"] or today,
            item["scheduled_time_sort"],
            _sort_text(item["household_name"]),
            _sort_text(item["service_label"]),
        ),
        reverse=True,
    )[:20]
    recent_completed_events = runtime._collapse_linked_service_entries(recent_completed_events)
    return {
        "today_events": today_events,
        "next_week_events": next_week_events,
        "scheduled_events": scheduled_events,
        "upcoming_events": upcoming_events,
        "unscheduled_events": unscheduled_events,
        "overdue_events": overdue_events,
        "past_unperformed_events": past_unperformed_events,
        "recent_completed_events": recent_completed_events,
    }
