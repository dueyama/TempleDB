from __future__ import annotations

from . import (
    browser_dataset_detail_builders,
    browser_dataset_filtering,
    browser_dataset_same_name,
    browser_dataset_summary_builders,
)

_build_same_name_groups = browser_dataset_same_name._build_same_name_groups
_attach_same_name_metadata = browser_dataset_same_name._attach_same_name_metadata
_household_same_name_groups = browser_dataset_same_name._household_same_name_groups


def _filter_households(
    households: list[dict],
    query: str,
    kana_group: str = "all",
    *,
    household_details: dict[str, dict] | None = None,
    memorial_search_index: dict[str, tuple[str, ...]] | None = None,
    include_memorial_search: bool = False,
) -> list[dict]:
    return browser_dataset_filtering._filter_households(
        households,
        query,
        kana_group,
        household_details=household_details,
        memorial_search_index=memorial_search_index,
        include_memorial_search=include_memorial_search,
    )


def _build_household_group_buttons(
    households: list[dict],
    filtered_households: list[dict],
    selected_group_key: str,
) -> list[dict]:
    return browser_dataset_filtering._build_household_group_buttons(
        households,
        filtered_households,
        selected_group_key,
    )


def _build_household_browser_summary_dataset_from_rows(
    *,
    household_rows: list[dict],
    person_rows: list[dict],
    schedule_rows: list[dict],
    bon_rows: list[dict],
    memorial_rules: list[dict],
    schedule_type_labels: dict[str, str],
) -> dict:
    return browser_dataset_summary_builders._build_household_browser_summary_dataset_from_rows(
        household_rows=household_rows,
        person_rows=person_rows,
        schedule_rows=schedule_rows,
        bon_rows=bon_rows,
        memorial_rules=memorial_rules,
        schedule_type_labels=schedule_type_labels,
    )


def _build_household_browser_detail_from_summary_dataset(dataset: dict, household_id: str) -> dict | None:
    return browser_dataset_detail_builders._build_household_browser_detail_from_summary_dataset(
        dataset,
        household_id,
    )


def _build_household_browser_dataset_from_rows(
    *,
    household_rows: list[dict],
    person_rows: list[dict],
    schedule_rows: list[dict],
    bon_rows: list[dict],
    memorial_rules: list[dict],
    schedule_type_labels: dict[str, str],
) -> dict:
    return browser_dataset_detail_builders._build_household_browser_dataset_from_rows(
        household_rows=household_rows,
        person_rows=person_rows,
        schedule_rows=schedule_rows,
        bon_rows=bon_rows,
        memorial_rules=memorial_rules,
        schedule_type_labels=schedule_type_labels,
    )


__all__ = [
    "_filter_households",
    "_build_household_group_buttons",
    "_build_same_name_groups",
    "_attach_same_name_metadata",
    "_household_same_name_groups",
    "_build_household_browser_summary_dataset_from_rows",
    "_build_household_browser_detail_from_summary_dataset",
    "_build_household_browser_dataset_from_rows",
]
