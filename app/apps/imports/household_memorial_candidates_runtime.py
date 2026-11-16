from __future__ import annotations

from datetime import date

from apps.core.services import memorial_dates

from . import (
    household_memorial_candidate_actions,
    household_memorial_candidate_dates,
    household_memorial_candidate_members,
    runtime_shared,
    service_ledger_runtime,
)
from .household_browser_runtime_shared import _runtime_timezone as _runtime_timezone

KIJITSU_STEPS = memorial_dates.KIJITSU_STEPS


def _service_event_is_actual(event: dict) -> bool:
    return service_ledger_runtime._service_event_is_actual(event)


def _service_schedule_category_for_candidate_type(
    candidate_type: str | None,
    service_label: str | None = None,
) -> str:
    return service_ledger_runtime._service_schedule_category_for_candidate_type(
        candidate_type,
        service_label,
    )


def _candidate_can_record_with_funeral(
    candidate_type: str | None,
    service_label: str | None = None,
) -> bool:
    return service_ledger_runtime._candidate_can_record_with_funeral(
        candidate_type,
        service_label,
    )


def _clean_value(value: str | None) -> str:
    return runtime_shared._clean_value(value)


def _effective_memorial_rules(memorial_rules: list[dict]) -> list[dict]:
    return household_memorial_candidate_members._effective_memorial_rules(memorial_rules)


def _int_sort(value: str | None) -> int:
    return runtime_shared._int_sort(value)


def _parse_iso_date(value: str | None) -> date | None:
    return runtime_shared._parse_iso_date(value)


def _read_csv_rows(path) -> list[dict]:
    return runtime_shared._read_csv_rows(path)


def _sort_text(value: str | None) -> str:
    return runtime_shared._sort_text(value)


def _to_memorial_label(rank: int) -> str:
    return memorial_dates._to_memorial_label(rank)


def _to_memorial_label_from_offset(offset_years: int) -> str:
    return memorial_dates._to_memorial_label_from_offset(offset_years)


def _kijitsu_offset_days_from_label(label: str | None) -> int | None:
    return household_memorial_candidate_dates._kijitsu_offset_days_from_label(label)


def _effective_service_schedule_status(schedule) -> str:
    return household_memorial_candidate_actions._effective_service_schedule_status(schedule)


def _effective_service_event_status(event: dict) -> str:
    return household_memorial_candidate_actions._effective_service_event_status(event)


def _person_is_service_target(person) -> bool:
    return household_memorial_candidate_actions._person_is_service_target(person)


def _build_memorial_candidates(
    memorial_members: list[dict],
    memorial_rules: list[dict],
    period_start: date,
    period_end: date,
) -> list[dict]:
    return household_memorial_candidate_members._build_memorial_candidates(
        memorial_members,
        memorial_rules,
        period_start,
        period_end,
    )


def _notice_eligible_memorial_members(detail: dict) -> list[dict]:
    return household_memorial_candidate_members._notice_eligible_memorial_members(detail)


def _attach_action_to_memorial_candidates(
    candidates: list[dict],
    events: list[dict] | None = None,
) -> list[dict]:
    return household_memorial_candidate_actions._attach_action_to_memorial_candidates(
        candidates,
        events,
    )


def _decorate_memorial_members(
    memorial_members: list[dict],
    memorial_rules: list[dict],
    period_start: date,
    period_end: date,
    events: list[dict] | None = None,
) -> list[dict]:
    return household_memorial_candidate_members._decorate_memorial_members(
        memorial_members,
        memorial_rules,
        period_start,
        period_end,
        events=events,
    )


def _parse_input_date(value: str | None) -> date | None:
    return household_memorial_candidate_dates._parse_input_date(value)


def _add_memorial_years(death_date: date, memorial_years: int) -> date:
    return household_memorial_candidate_dates._add_memorial_years(death_date, memorial_years)


def _add_memorial_offset_years(death_date: date, offset_years: int) -> date:
    return household_memorial_candidate_dates._add_memorial_offset_years(death_date, offset_years)


def _memorial_offset_years_from_label(label: str | None) -> int | None:
    return household_memorial_candidate_dates._memorial_offset_years_from_label(label)


def _memorial_offset_years(memorial_rank: int) -> int:
    return household_memorial_candidate_dates._memorial_offset_years(memorial_rank)


def _first_obon_date(death_date: date) -> date:
    return household_memorial_candidate_dates._first_obon_date(death_date)


def _replace_year_clamped(original: date, target_year: int) -> date:
    return household_memorial_candidate_dates._replace_year_clamped(original, target_year)


def _to_wareki_date_numeric(target: date) -> str:
    return household_memorial_candidate_dates._to_wareki_date_numeric(target)


__all__ = [
    "_add_memorial_offset_years",
    "_add_memorial_years",
    "_attach_action_to_memorial_candidates",
    "_build_memorial_candidates",
    "_candidate_can_record_with_funeral",
    "_decorate_memorial_members",
    "_effective_memorial_rules",
    "_effective_service_event_status",
    "_effective_service_schedule_status",
    "_first_obon_date",
    "_kijitsu_offset_days_from_label",
    "_memorial_offset_years",
    "_memorial_offset_years_from_label",
    "_notice_eligible_memorial_members",
    "_parse_input_date",
    "_person_is_service_target",
    "_replace_year_clamped",
    "_service_event_is_actual",
    "_service_schedule_category_for_candidate_type",
    "_to_wareki_date_numeric",
]
