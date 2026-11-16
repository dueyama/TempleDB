from __future__ import annotations

from .data_science_shared import *  # noqa: F401,F403

__all__ = [
    "_same_day_cluster_analysis",
    "_household_concentration_analysis",
]


def _same_day_cluster_analysis(dataframe, *, start_year: int | None, end_year: int | None) -> dict:
    import pandas as pd

    empty_int_series = pd.Series(dtype="int64")
    if start_year is None or end_year is None or dataframe.empty:
        return {
            "available": False,
            "size_series": empty_int_series,
            "month_series": pd.Series([0] * 12, index=[f"{month}月" for month in range(1, 13)]),
            "rows": [],
            "stats": {
                "cluster_day_count": 0,
                "clustered_record_count": 0,
                "max_cluster_size": None,
                "cluster_day_share": None,
            },
        }

    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        return {
            "available": False,
            "size_series": empty_int_series,
            "month_series": pd.Series([0] * 12, index=[f"{month}月" for month in range(1, 13)]),
            "rows": [],
            "stats": {
                "cluster_day_count": 0,
                "clustered_record_count": 0,
                "max_cluster_size": None,
                "cluster_day_share": None,
            },
        }

    day_counts = filtered["death_date"].dt.normalize().value_counts().sort_index()
    cluster_counts = day_counts[day_counts >= 2]
    if cluster_counts.empty:
        return {
            "available": False,
            "size_series": empty_int_series,
            "month_series": pd.Series([0] * 12, index=[f"{month}月" for month in range(1, 13)]),
            "rows": [],
            "stats": {
                "cluster_day_count": 0,
                "clustered_record_count": 0,
                "max_cluster_size": None,
                "cluster_day_share": 0.0,
            },
        }

    size_counts = cluster_counts.value_counts().sort_index()
    size_series = pd.Series(
        size_counts.tolist(),
        index=[f"{int(index)}件" for index in size_counts.index.tolist()],
        dtype="int64",
    )
    month_counts = (
        pd.Series(1, index=cluster_counts.index)
        .groupby(cluster_counts.index.month)
        .sum()
        .reindex(range(1, 13), fill_value=0)
    )
    month_series = pd.Series(
        month_counts.tolist(),
        index=[f"{month}月" for month in range(1, 13)],
        dtype="int64",
    )
    cluster_frame = (
        cluster_counts.rename("count")
        .rename_axis("death_date")
        .reset_index()
        .sort_values(["count", "death_date"], ascending=[False, True])
    )

    return {
        "available": True,
        "size_series": size_series,
        "month_series": month_series,
        "rows": [
            {
                "death_date": row["death_date"].date().isoformat(),
                "count": int(row["count"]),
            }
            for _, row in cluster_frame.head(12).iterrows()
        ],
        "stats": {
            "cluster_day_count": int(len(cluster_counts)),
            "clustered_record_count": int(cluster_counts.sum()),
            "max_cluster_size": int(cluster_counts.max()),
            "cluster_day_share": round((len(cluster_counts) / len(day_counts)) * 100.0, 2)
            if len(day_counts) > 0
            else None,
        },
    }


def _household_concentration_analysis(household_rows: list[dict]) -> dict:
    positive_rows = [
        row
        for row in household_rows
        if int(row.get("memorial_count") or 0) > 0
    ]
    if not positive_rows:
        return {
            "available": False,
            "total_households": 0,
            "total_records": 0,
            "gini": None,
            "top10_share": None,
            "top20_share": None,
            "household_share_points": [],
            "record_share_points": [],
        }

    counts_desc = sorted(
        [int(row["memorial_count"]) for row in positive_rows],
        reverse=True,
    )
    counts_asc = sorted(counts_desc)
    total_households = len(counts_desc)
    total_records = sum(counts_desc)

    cumulative_records = [0.0]
    running = 0
    for value in counts_asc:
        running += value
        cumulative_records.append(running / total_records)
    household_share_points = [index / total_households for index in range(total_households + 1)]

    area = 0.0
    for index in range(total_households):
        area += (
            (cumulative_records[index] + cumulative_records[index + 1])
            * (household_share_points[index + 1] - household_share_points[index])
            / 2.0
        )
    gini = max(0.0, 1.0 - (2.0 * area))

    return {
        "available": True,
        "total_households": total_households,
        "total_records": total_records,
        "gini": round(gini, 3),
        "top10_share": round((sum(counts_desc[:10]) / total_records) * 100.0, 1),
        "top20_share": round((sum(counts_desc[:20]) / total_records) * 100.0, 1),
        "household_share_points": household_share_points,
        "record_share_points": cumulative_records,
    }
