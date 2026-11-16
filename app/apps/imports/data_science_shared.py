from __future__ import annotations

from datetime import date
from pathlib import Path

from apps.core.services import tenant_policy

from . import browser_dataset, runtime_shared, source_runtime

__all__ = [
    "WEEKDAYS_JA",
    "ANALYTICS_YEAR_LOWER_QUANTILE",
    "DAYS_PER_SOLAR_YEAR",
    "DEATH_INTERVAL_BUCKETS",
    "GENDER_LABELS",
    "GENDER_COLOR_MAP",
    "AVERAGE_AGE_TREND_LABELS",
    "AVERAGE_AGE_TREND_COLOR_MAP",
    "AVERAGE_AGE_TREND_WINDOW_YEARS",
    "AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER",
    "COHORT_MODE_OPTIONS",
    "HOMYO_INGO_SUFFIXES",
    "HOMYO_PREFIX_TOKENS",
    "HOMYO_INGO_TYPE_LABELS",
    "HOMYO_INGO_TYPE_COLORS",
    "COMPLETENESS_LABELS",
    "COMPLETENESS_COLOR_MAP",
    "completeness_labels",
    "completeness_color_map",
    "base_dir",
    "resolve_runtime_source_entry",
    "source_summary",
    "registered_sources",
    "latest_export_snapshot",
    "_load_household_browser_dataset",
    "_sort_text",
    "_int_sort",
    "_clean_value",
    "_display_value",
    "_parse_iso_date",
]

WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"]
ANALYTICS_YEAR_LOWER_QUANTILE = 0.02
DAYS_PER_SOLAR_YEAR = 365.2425
DEATH_INTERVAL_BUCKETS = [
    {"label": "0日", "minimum": 0, "maximum": 0},
    {"label": "1-6日", "minimum": 1, "maximum": 6},
    {"label": "7-13日", "minimum": 7, "maximum": 13},
    {"label": "14-29日", "minimum": 14, "maximum": 29},
    {"label": "30-89日", "minimum": 30, "maximum": 89},
    {"label": "90-179日", "minimum": 90, "maximum": 179},
    {"label": "180-364日", "minimum": 180, "maximum": 364},
    {"label": "365日以上", "minimum": 365, "maximum": None},
]
GENDER_LABELS = ["男", "女", "不明"]
GENDER_COLOR_MAP = {
    "男": "#4a6fa5",
    "女": "#c96a80",
    "不明": "#938777",
}
AVERAGE_AGE_TREND_LABELS = ["合計", "男", "女"]
AVERAGE_AGE_TREND_COLOR_MAP = {
    "合計": "#5d4631",
    "男": "#4a6fa5",
    "女": "#c96a80",
}
AVERAGE_AGE_TREND_WINDOW_YEARS = 5
AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER = 1.5
COHORT_MODE_OPTIONS = [
    {"value": "share", "label": "構成比"},
    {"value": "count", "label": "実件数"},
]
HOMYO_INGO_SUFFIXES = ("院", "庵", "軒")
HOMYO_PREFIX_TOKENS = ("釋尼", "釈尼", "釋", "釈", "尼")
HOMYO_INGO_TYPE_LABELS = ["院", "庵", "軒", "院号なし"]
HOMYO_INGO_TYPE_COLORS = {
    "院": "#a65233",
    "庵": "#cf8d2e",
    "軒": "#6d8a49",
    "院号なし": "#9a9388",
}


def completeness_labels() -> list[str]:
    terms = tenant_policy.terminology_terms()
    return ["享年あり", terms["homyo_presence"], "性別あり"]


def completeness_color_map() -> dict[str, str]:
    labels = completeness_labels()
    return {
        labels[0]: "#b17d1b",
        labels[1]: "#8f5f2c",
        labels[2]: "#4a6fa5",
    }


COMPLETENESS_LABELS = completeness_labels()
COMPLETENESS_COLOR_MAP = completeness_color_map()


def base_dir() -> Path:
    return source_runtime.base_dir()


def resolve_runtime_source_entry() -> dict:
    return source_runtime.resolve_runtime_source_entry()


def source_summary(source_id: str) -> dict:
    return source_runtime.source_summary(source_id)


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    return source_runtime.registered_sources(selected_source_id)


def latest_export_snapshot(source_id: str) -> dict | None:
    return source_runtime.latest_export_snapshot(source_id)


def _load_household_browser_dataset(
    source_id: str,
    snapshot_id: str,
    *,
    data_backend: str = "db",
) -> dict:
    return browser_dataset._load_household_browser_dataset(
        source_id,
        snapshot_id,
        data_backend=data_backend,
    )


def _sort_text(value: str | None) -> tuple[int, str]:
    return runtime_shared._sort_text(value)


def _int_sort(value: str | None) -> tuple[int, int | str]:
    return runtime_shared._int_sort(value)


def _clean_value(value: str | None) -> str:
    return runtime_shared._clean_value(value)


def _display_value(value: str | None) -> str:
    return runtime_shared._display_value(value)


def _parse_iso_date(value: str | None) -> date | None:
    return runtime_shared._parse_iso_date(value)
