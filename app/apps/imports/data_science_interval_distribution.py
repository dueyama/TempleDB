from __future__ import annotations

from .data_science_shared import DEATH_INTERVAL_BUCKETS

__all__ = [
    "_death_interval_distribution",
    "_empty_interval_bucket_series",
    "_death_interval_bucket_labels",
    "_death_interval_bucket_label",
]


def _death_interval_distribution(dataframe, *, start_year: int | None) -> dict:
    if start_year is None or dataframe.empty:
        return {
            "bucket_counts": _empty_interval_bucket_series(),
            "stats": {
                "count": 0,
                "median_days": None,
                "mean_days": None,
                "std_days": None,
                "max_days": None,
                "same_day_count": 0,
                "start_year": start_year,
            },
            "intervals": [],
        }

    filtered = dataframe[dataframe["death_year"] >= start_year].sort_values(
        ["death_date", "person_id"]
    )
    intervals = filtered["death_date"].diff().dropna().dt.days.astype(int)
    if intervals.empty:
        return {
            "bucket_counts": _empty_interval_bucket_series(),
            "stats": {
                "count": 0,
                "median_days": None,
                "mean_days": None,
                "std_days": None,
                "max_days": None,
                "same_day_count": 0,
                "start_year": start_year,
            },
            "intervals": [],
        }

    bucket_counts = (
        intervals.apply(_death_interval_bucket_label)
        .value_counts()
        .reindex(_death_interval_bucket_labels(), fill_value=0)
    )
    return {
        "bucket_counts": bucket_counts,
        "stats": {
            "count": int(len(intervals)),
            "median_days": int(intervals.median()),
            "mean_days": round(float(intervals.mean()), 1),
            "std_days": round(float(intervals.std()), 1),
            "max_days": int(intervals.max()),
            "same_day_count": int((intervals == 0).sum()),
            "start_year": start_year,
        },
        "intervals": intervals.tolist(),
    }


def _empty_interval_bucket_series():
    import pandas as pd

    return pd.Series([0] * len(DEATH_INTERVAL_BUCKETS), index=_death_interval_bucket_labels())


def _death_interval_bucket_labels() -> list[str]:
    return [bucket["label"] for bucket in DEATH_INTERVAL_BUCKETS]


def _death_interval_bucket_label(days: int) -> str:
    for bucket in DEATH_INTERVAL_BUCKETS:
        maximum = bucket["maximum"]
        if days >= bucket["minimum"] and (maximum is None or days <= maximum):
            return bucket["label"]
    return DEATH_INTERVAL_BUCKETS[-1]["label"]
