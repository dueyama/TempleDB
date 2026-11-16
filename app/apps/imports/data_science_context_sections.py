from __future__ import annotations

from . import data_science_context_payload

__all__ = [
    "_legacy_build_data_science_context",
]

def _legacy_build_data_science_context(
    source_id: str | None = None,
    month_cohort_mode: str | None = None,
    age_cohort_mode: str | None = None,
    data_backend: str = "db",
) -> dict:
    return data_science_context_payload._build_data_science_context_payload(
        source_id=source_id,
        month_cohort_mode=month_cohort_mode,
        age_cohort_mode=age_cohort_mode,
        data_backend=data_backend,
    )
