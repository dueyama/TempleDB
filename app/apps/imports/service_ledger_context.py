from __future__ import annotations

from . import service_ledger_event_groups, service_ledger_search_context


def build_service_ledger_context(
    source_id: str | None = None,
    query: str = "",
    *,
    candidate_page: int | str = 1,
) -> dict:
    return _legacy_build_service_ledger_context(
        source_id=source_id,
        query=query,
        candidate_page=candidate_page,
    )


def _legacy_build_service_ledger_context(
    source_id: str | None = None,
    query: str = "",
    *,
    candidate_page: int | str = 1,
) -> dict:
    return service_ledger_search_context._legacy_build_service_ledger_context(
        source_id=source_id,
        query=query,
        candidate_page=candidate_page,
    )


def build_home_service_schedule_summary(
    source_id: str | None = None,
    *,
    latest_export: dict | None = None,
    batch=None,
    canonical_population_checked: bool = False,
) -> dict:
    return service_ledger_event_groups.build_home_service_schedule_summary(
        source_id,
        latest_export=latest_export,
        batch=batch,
        canonical_population_checked=canonical_population_checked,
    )


def _build_service_ledger_event_groups(
    schedule_entries: list[dict],
    *,
    today,
    overdue_period_start,
    next_week_period_end,
    future_period_end,
) -> dict:
    return service_ledger_event_groups._build_service_ledger_event_groups(
        schedule_entries,
        today=today,
        overdue_period_start=overdue_period_start,
        next_week_period_end=next_week_period_end,
        future_period_end=future_period_end,
    )


__all__ = [
    "build_service_ledger_context",
    "_legacy_build_service_ledger_context",
    "build_home_service_schedule_summary",
    "_build_service_ledger_event_groups",
]
