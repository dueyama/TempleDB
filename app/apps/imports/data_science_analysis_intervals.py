from __future__ import annotations

from . import (
    data_science_interval_distribution,
    data_science_interval_models,
    data_science_year_count_analysis,
)

__all__ = [
    "_death_interval_distribution",
    "_empty_interval_bucket_series",
    "_death_interval_bucket_labels",
    "_death_interval_bucket_label",
    "_poisson_process_consistency_analysis",
    "_interval_survival_analysis",
    "_interval_qq_analysis",
    "_year_count_diagnostics",
    "_year_count_distribution_analysis",
]


def _death_interval_distribution(dataframe, *, start_year: int | None) -> dict:
    return data_science_interval_distribution._death_interval_distribution(
        dataframe,
        start_year=start_year,
    )


def _empty_interval_bucket_series():
    return data_science_interval_distribution._empty_interval_bucket_series()


def _death_interval_bucket_labels() -> list[str]:
    return data_science_interval_distribution._death_interval_bucket_labels()


def _death_interval_bucket_label(days: int) -> str:
    return data_science_interval_distribution._death_interval_bucket_label(days)


def _poisson_process_consistency_analysis(
    dataframe,
    *,
    start_year: int | None,
    end_year: int | None,
    interval_stats: dict,
) -> dict:
    return data_science_interval_models._poisson_process_consistency_analysis(
        dataframe,
        start_year=start_year,
        end_year=end_year,
        interval_stats=interval_stats,
    )


def _interval_survival_analysis(intervals: list[int], *, mean_days: float | None) -> dict:
    return data_science_interval_models._interval_survival_analysis(
        intervals,
        mean_days=mean_days,
    )


def _interval_qq_analysis(intervals: list[int], *, mean_days: float | None) -> dict:
    return data_science_interval_models._interval_qq_analysis(
        intervals,
        mean_days=mean_days,
    )


def _year_count_diagnostics(year_counts) -> dict:
    return data_science_year_count_analysis._year_count_diagnostics(year_counts)


def _year_count_distribution_analysis(year_counts) -> dict:
    return data_science_year_count_analysis._year_count_distribution_analysis(
        year_counts
    )
