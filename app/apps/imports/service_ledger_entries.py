from __future__ import annotations

from . import (
    service_ledger_candidate_entries,
    service_ledger_schedule_entries,
    service_ledger_target_entries,
)


def _service_row_from_model(service):
    return service_ledger_schedule_entries._service_row_from_model(service)


def _actual_service_schedule_death_date(schedule):
    return service_ledger_schedule_entries._actual_service_schedule_death_date(schedule)


def _resolved_service_schedule_target_date(schedule):
    return service_ledger_schedule_entries._resolved_service_schedule_target_date(schedule)


def _service_schedule_category_for_candidate_type(
    candidate_type: str | None,
    service_label: str | None = None,
) -> str:
    return service_ledger_candidate_entries._service_schedule_category_for_candidate_type(
        candidate_type,
        service_label,
    )


def _candidate_can_record_with_funeral(
    candidate_type: str | None,
    service_label: str | None = None,
) -> bool:
    return service_ledger_candidate_entries._candidate_can_record_with_funeral(
        candidate_type,
        service_label,
    )


def _compact_service_label(service_label: str | None) -> str:
    return service_ledger_schedule_entries._compact_service_label(service_label)


def _service_category_badge_label(
    category: str | None,
    service_label: str | None = None,
) -> str:
    return service_ledger_schedule_entries._service_category_badge_label(category, service_label)


def _service_ledger_schedule_entry(schedule, *, today, overdue_period_start):
    return service_ledger_schedule_entries._service_ledger_schedule_entry(
        schedule,
        today=today,
        overdue_period_start=overdue_period_start,
    )


def _collapse_linked_service_entries(entries: list[dict]) -> list[dict]:
    return service_ledger_schedule_entries._collapse_linked_service_entries(entries)


def _linked_service_entry_master_sort_key(entry: dict) -> tuple:
    return service_ledger_schedule_entries._linked_service_entry_master_sort_key(entry)


def _effective_service_schedule_status(schedule) -> str:
    return service_ledger_schedule_entries._effective_service_schedule_status(schedule)


def _effective_service_schedule_status_label(schedule) -> str:
    return service_ledger_schedule_entries._effective_service_schedule_status_label(schedule)


def _service_event_is_actual(event: dict) -> bool:
    return service_ledger_schedule_entries._service_event_is_actual(event)


def _is_actual_service_schedule(schedule) -> bool:
    return service_ledger_schedule_entries._is_actual_service_schedule(schedule)


def _service_ledger_schedule_matches(entry: dict, needle: str) -> bool:
    return service_ledger_schedule_entries._service_ledger_schedule_matches(entry, needle)


def _service_ledger_candidate_matches(entry: dict, needle: str) -> bool:
    return service_ledger_candidate_entries._service_ledger_candidate_matches(entry, needle)


def _matching_actual_schedule_for_candidate(candidate: dict, schedules):
    return service_ledger_candidate_entries._matching_actual_schedule_for_candidate(candidate, schedules)


def _candidate_already_has_actual_schedule(candidate: dict, schedule_entries: list[dict]) -> bool:
    return service_ledger_candidate_entries._candidate_already_has_actual_schedule(
        candidate,
        schedule_entries,
    )


def _service_ledger_candidate_entry(candidate: dict, *, today, overdue_period_start) -> dict:
    return service_ledger_candidate_entries._service_ledger_candidate_entry(
        candidate,
        today=today,
        overdue_period_start=overdue_period_start,
    )


def _service_target_person_entry(person) -> dict:
    return service_ledger_target_entries._service_target_person_entry(person)


def _person_is_service_target(person) -> bool:
    return service_ledger_target_entries._person_is_service_target(person)


def _service_target_person_matches(entry: dict, needle: str) -> bool:
    return service_ledger_target_entries._service_target_person_matches(entry, needle)


__all__ = [
    "_service_row_from_model",
    "_actual_service_schedule_death_date",
    "_resolved_service_schedule_target_date",
    "_service_schedule_category_for_candidate_type",
    "_candidate_can_record_with_funeral",
    "_compact_service_label",
    "_service_category_badge_label",
    "_service_ledger_schedule_entry",
    "_collapse_linked_service_entries",
    "_linked_service_entry_master_sort_key",
    "_effective_service_schedule_status",
    "_effective_service_schedule_status_label",
    "_service_event_is_actual",
    "_is_actual_service_schedule",
    "_service_ledger_schedule_matches",
    "_service_ledger_candidate_matches",
    "_matching_actual_schedule_for_candidate",
    "_candidate_already_has_actual_schedule",
    "_service_ledger_candidate_entry",
    "_service_target_person_entry",
    "_person_is_service_target",
    "_service_target_person_matches",
]
