from __future__ import annotations

from collections.abc import Callable

from . import (
    data_quality_runtime,
    data_science_runtime,
    special_search_context,
    special_search_runtime,
)

SPECIAL_SEARCH_DEFINITIONS = special_search_runtime.SPECIAL_SEARCH_DEFINITIONS
_build_special_search_entries = special_search_runtime._build_special_search_entries
_legacy_build_data_quality_context = data_quality_runtime._legacy_build_data_quality_context
_legacy_build_special_search_context = special_search_runtime._legacy_build_special_search_context
_legacy_build_data_science_context = data_science_runtime._legacy_build_data_science_context


def build_data_quality_context(
    source_id: str | None = None,
    query: str = "",
    data_backend: str = "db",
) -> dict:
    return data_quality_runtime.build_data_quality_context(
        source_id=source_id,
        query=query,
        data_backend=data_backend,
    )


def build_special_search_context(
    source_id: str | None = None,
    *,
    search_key: str | None = None,
    query: str = "",
    data_backend: str = "db",
    data_quality_context_builder: Callable[..., dict] | None = None,
) -> dict:
    return special_search_context._build_special_search_context(
        source_id=source_id,
        search_key=search_key,
        query=query,
        data_backend=data_backend,
        data_quality_context_builder=(
            data_quality_context_builder
            if data_quality_context_builder is not None
            else build_data_quality_context
        ),
        search_definitions=SPECIAL_SEARCH_DEFINITIONS,
        resolve_key_fn=special_search_runtime._resolve_special_search_key,
        build_entries_fn=special_search_runtime._build_special_search_entries,
        entry_matches_fn=special_search_runtime._special_search_entry_matches,
        data_quality_total_count_fn=special_search_runtime._data_quality_total_count,
        build_counts_fn=special_search_runtime._build_special_search_counts,
        build_selected_entries_fn=(
            special_search_runtime._build_selected_special_search_entries
        ),
    )


def build_data_science_context(
    source_id: str | None = None,
    month_cohort_mode: str | None = None,
    age_cohort_mode: str | None = None,
    data_backend: str = "db",
) -> dict:
    return data_science_runtime._legacy_build_data_science_context(
        source_id=source_id,
        month_cohort_mode=month_cohort_mode,
        age_cohort_mode=age_cohort_mode,
        data_backend=data_backend,
    )


__all__ = [
    "SPECIAL_SEARCH_DEFINITIONS",
    "_build_special_search_entries",
    "_legacy_build_data_quality_context",
    "_legacy_build_data_science_context",
    "_legacy_build_special_search_context",
    "build_data_quality_context",
    "build_data_science_context",
    "build_special_search_context",
]
