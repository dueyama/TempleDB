from __future__ import annotations

from datetime import date

# Preserve the established façade owner/shared initialization order and grouped
# runtime aliases used by compatibility and monkeypatch seams.
# isort: off
from . import household_memorial_list_runtime, memorial_sheet_document_runtime
from . import memorial_shared
from .household_browser_dataset_runtime import (
    _load_household_browser_dataset as _load_household_browser_dataset,
)
from .household_browser_runtime_shared import (
    latest_export_snapshot as latest_export_snapshot,
    resolve_runtime_source_entry as resolve_runtime_source_entry,
)
# isort: on

KIJITSU_STEPS = memorial_shared.KIJITSU_STEPS
MEMORIAL_RANKS = memorial_shared.MEMORIAL_RANKS
WEEKDAYS_JA = memorial_shared.WEEKDAYS_JA
HOUSEHOLD_MEMORIAL_LIST_PAGE_ROW_BUDGET = 19.0
HOUSEHOLD_MEMORIAL_LIST_SUBLINE_ROW_WEIGHT = 0.35
HOUSEHOLD_MEMORIAL_LIST_LONG_KAIMYO_WEIGHT = 0.25
HOUSEHOLD_MEMORIAL_LIST_LONG_NAME_WEIGHT = 0.15
HOUSEHOLD_MEMORIAL_LIST_LONG_NAME_THRESHOLD = 8
HOUSEHOLD_MEMORIAL_LIST_LONG_KAIMYO_THRESHOLD = 9


def build_memorial_sheet_context(
    source_id: str | None = None,
    household_id: str | None = None,
    person_id: str | None = None,
    data_backend: str = "db",
) -> dict:
    return memorial_sheet_document_runtime.build_memorial_sheet_context(
        source_id=source_id,
        household_id=household_id,
        person_id=person_id,
        data_backend=data_backend,
    )


def _legacy_build_memorial_sheet_context(
    source_id: str | None = None,
    household_id: str | None = None,
    person_id: str | None = None,
    data_backend: str = "db",
) -> dict:
    return memorial_sheet_document_runtime._legacy_build_memorial_sheet_context(
        source_id=source_id,
        household_id=household_id,
        person_id=person_id,
        data_backend=data_backend,
    )


def build_household_memorial_list_context(
    source_id: str | None = None,
    household_id: str | None = None,
    data_backend: str = "db",
    start_date: str | date | None = None,
) -> dict:
    return household_memorial_list_runtime.build_household_memorial_list_context(
        source_id=source_id,
        household_id=household_id,
        data_backend=data_backend,
        start_date=start_date,
    )


def _legacy_build_household_memorial_list_context(
    source_id: str | None = None,
    household_id: str | None = None,
    data_backend: str = "db",
    start_date: str | date | None = None,
) -> dict:
    return household_memorial_list_runtime._legacy_build_household_memorial_list_context(
        source_id=source_id,
        household_id=household_id,
        data_backend=data_backend,
        start_date=start_date,
    )


def _build_memorial_sheet_document(person: dict) -> dict | None:
    return memorial_sheet_document_runtime._build_memorial_sheet_document(person)


def _memorial_sheet_display_homyo(person: dict) -> str:
    return memorial_sheet_document_runtime._memorial_sheet_display_homyo(person)


def _memorial_sheet_homyo_center_offset_em(display_text: str) -> float:
    return memorial_sheet_document_runtime._memorial_sheet_homyo_center_offset_em(display_text)


def _memorial_sheet_homyo_display_parts(display_text: str) -> dict[str, str]:
    return memorial_sheet_document_runtime._memorial_sheet_homyo_display_parts(display_text)


def _format_memorial_sheet_age_at_death(value) -> str:
    return memorial_sheet_document_runtime._format_memorial_sheet_age_at_death(value)


def _build_kijitsu_rows(death_date: date) -> list[dict]:
    return memorial_sheet_document_runtime._build_kijitsu_rows(death_date)


def _build_memorial_sheet_rows(death_date: date) -> list[dict]:
    return memorial_sheet_document_runtime._build_memorial_sheet_rows(death_date)


def _build_household_memorial_list_rows(
    memorial_members: list[dict],
    *,
    start_date: date | None = None,
) -> list[dict]:
    return household_memorial_list_runtime._build_household_memorial_list_rows(
        memorial_members,
        start_date=start_date,
    )


def _resolve_household_memorial_list_start_date(value: str | date | None) -> date:
    return household_memorial_list_runtime._resolve_household_memorial_list_start_date(value)


def _household_memorial_list_subline(person: dict) -> str:
    return household_memorial_list_runtime._household_memorial_list_subline(person)


def _household_memorial_list_age_display(age_at_death, age_unit: str) -> str:
    return household_memorial_list_runtime._household_memorial_list_age_display(
        age_at_death,
        age_unit,
    )


def _household_memorial_list_date_with_wareki_year(target: date) -> str:
    return household_memorial_list_runtime._household_memorial_list_date_with_wareki_year(target)


def _household_memorial_list_compact_memorial_label(rank: int) -> str:
    return household_memorial_list_runtime._household_memorial_list_compact_memorial_label(rank)


def _household_memorial_list_display_name(value) -> str:
    return household_memorial_list_runtime._household_memorial_list_display_name(value)


def _household_memorial_list_row_weight(entry: dict) -> float:
    return household_memorial_list_runtime._household_memorial_list_row_weight(entry)


def _paginate_household_memorial_list_rows(rows: list[dict]) -> list[dict]:
    return household_memorial_list_runtime._paginate_household_memorial_list_rows(rows)


def _to_memorial_label(rank: int) -> str:
    return memorial_shared._to_memorial_label(rank)


def _to_memorial_label_from_offset(offset_years: int) -> str:
    return memorial_shared._to_memorial_label_from_offset(offset_years)


def _to_wareki_date(target: date) -> str:
    return memorial_shared._to_wareki_date(target)


def _to_wareki_date_numeric(target: date) -> str:
    return memorial_shared._to_wareki_date_numeric(target)


def _to_wareki_year_numeric(year: int) -> str:
    return memorial_shared._to_wareki_year_numeric(year)


def _format_month_day_kanji(target: date) -> str:
    return memorial_shared._format_month_day_kanji(target)


def _to_kanji_number(value: int) -> str:
    return memorial_shared._to_kanji_number(value)


def _to_zenkaku_digits(value: int | str) -> str:
    return memorial_shared._to_zenkaku_digits(value)


def _to_kanji_year_digits(value: int | str) -> str:
    return memorial_shared._to_kanji_year_digits(value)


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    return memorial_shared._chunked(items, size)


__all__ = [
    "_build_kijitsu_rows",
    "_build_memorial_sheet_document",
    "_build_household_memorial_list_rows",
    "_build_memorial_sheet_rows",
    "_chunked",
    "_format_memorial_sheet_age_at_death",
    "_memorial_sheet_display_homyo",
    "_memorial_sheet_homyo_display_parts",
    "_memorial_sheet_homyo_center_offset_em",
    "_format_month_day_kanji",
    "_household_memorial_list_row_weight",
    "_legacy_build_memorial_sheet_context",
    "_paginate_household_memorial_list_rows",
    "_to_kanji_number",
    "_to_kanji_year_digits",
    "_to_memorial_label",
    "_to_memorial_label_from_offset",
    "_to_wareki_date",
    "_to_wareki_date_numeric",
    "_to_wareki_year_numeric",
    "_legacy_build_household_memorial_list_context",
    "_to_zenkaku_digits",
    "build_household_memorial_list_context",
    "build_memorial_sheet_context",
]
