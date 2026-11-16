from __future__ import annotations

from datetime import date

from apps.imports.data_quality_runtime import (
    build_data_quality_context as _build_data_quality_context,
)
from apps.imports.data_science_csv_export import (
    build_death_demographics_csv_rows as _build_death_demographics_csv_rows,
)
from apps.imports.quality_reports import (
    build_data_science_context as _build_data_science_context,
)
from apps.imports.quality_reports import (
    build_special_search_context as _build_special_search_context,
)


def build_data_quality_context(
    source_id: str | None = None,
    query: str = "",
    data_backend: str = "auto",
) -> dict:
    return _build_data_quality_context(
        source_id=source_id,
        query=query,
        data_backend=data_backend,
    )


def build_special_search_context(
    source_id: str | None = None,
    *,
    search_key: str | None = None,
    query: str = "",
    data_backend: str = "auto",
) -> dict:
    return _build_special_search_context(
        source_id=source_id,
        search_key=search_key,
        query=query,
        data_backend=data_backend,
        data_quality_context_builder=build_data_quality_context,
    )


def build_data_science_context(
    source_id: str | None = None,
    month_cohort_mode: str | None = None,
    age_cohort_mode: str | None = None,
    data_backend: str = "auto",
) -> dict:
    return _build_data_science_context(
        source_id=source_id,
        month_cohort_mode=month_cohort_mode,
        age_cohort_mode=age_cohort_mode,
        data_backend=data_backend,
    )


def build_death_demographics_csv_rows(*, start_date: date, end_date: date) -> dict:
    return _build_death_demographics_csv_rows(
        start_date=start_date,
        end_date=end_date,
    )
