from __future__ import annotations

from . import (
    browser_dataset_household_event_rows,
    browser_dataset_member_rows,
    browser_dataset_model_rows,
    runtime_shared,
)


def _sorted_household_person_rows(
    persons_by_household: dict[str, list[dict]],
    household_key: str,
) -> list[dict]:
    return browser_dataset_member_rows._sorted_household_person_rows(
        persons_by_household,
        household_key,
    )


def _sort_date(value):
    return runtime_shared._sort_date(value)


def _is_yuen_household_row(row: dict) -> bool:
    return browser_dataset_household_event_rows._is_yuen_household_row(row)


def _household_summary_sort_key(item: dict) -> tuple[int, str, str, int]:
    return browser_dataset_household_event_rows._household_summary_sort_key(item)


def _member_type_labels(row: dict) -> tuple[str, str]:
    return browser_dataset_member_rows._member_type_labels(row)


def _same_name_source_member_summary(row: dict, household_name: str) -> dict:
    return browser_dataset_member_rows._same_name_source_member_summary(row, household_name)


def _household_row_from_model(
    household,
    profile=None,
) -> dict[str, object]:
    return browser_dataset_model_rows._household_row_from_model(household, profile)


def _person_row_from_model(person) -> dict[str, str]:
    return browser_dataset_model_rows._person_row_from_model(person)


def _event_summary(row: dict, source_table: str, schedule_type_labels: dict[str, str]) -> dict:
    return browser_dataset_household_event_rows._event_summary(row, source_table, schedule_type_labels)


def _sort_memorial_members(memorial_members: list[dict]) -> list[dict]:
    return browser_dataset_member_rows._sort_memorial_members(memorial_members)


def _person_summary(row: dict) -> dict:
    return browser_dataset_member_rows._person_summary(row)


def _is_placeholder_person_row(row: dict) -> bool:
    return browser_dataset_member_rows._is_placeholder_person_row(row)


def _is_memorial_person(row: dict) -> bool:
    return browser_dataset_member_rows._is_memorial_person(row)


__all__ = [
    "_sorted_household_person_rows",
    "_sort_date",
    "_is_yuen_household_row",
    "_household_summary_sort_key",
    "_member_type_labels",
    "_same_name_source_member_summary",
    "_household_row_from_model",
    "_person_row_from_model",
    "_event_summary",
    "_sort_memorial_members",
    "_person_summary",
    "_is_placeholder_person_row",
    "_is_memorial_person",
]
