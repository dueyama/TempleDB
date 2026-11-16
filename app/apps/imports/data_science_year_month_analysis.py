from __future__ import annotations

from .data_science_shared import *  # noqa: F401,F403

__all__ = [
    "_selected_death_year_records",
    "_death_year_details",
    "_year_month_heatmap_analysis",
]


def _selected_death_year_records(dataframe, death_year: int) -> list[dict]:
    import pandas as pd

    if dataframe.empty:
        return []
    filtered = dataframe[dataframe["death_year"] == death_year].sort_values(
        ["death_date", "person_id"],
        ascending=[False, False],
    )
    return [
        {
            "death_date": row["death_date"].date().isoformat()
            if hasattr(row["death_date"], "date")
            else str(row["death_date"])[:10],
            "name": row["name"],
            "gender": row["gender"],
            "age_at_death": "" if pd.isna(row["age_at_death"]) else int(row["age_at_death"]),
            "household_name": row["household_name"],
            "person_id": row["person_id"],
            "household_id": row["household_id"],
        }
        for _, row in filtered.iterrows()
    ]


def _death_year_details(dataframe, years: list[int]) -> list[dict]:
    details = []
    for death_year in years:
        rows = _selected_death_year_records(dataframe, death_year)
        if not rows:
            continue
        details.append(
            {
                "year": death_year,
                "label": str(death_year),
                "modal_id": f"death-year-{death_year}",
                "count": len(rows),
                "rows": rows,
            }
        )
    return details


def _year_month_heatmap_analysis(dataframe, *, start_year: int | None, end_year: int | None) -> dict:
    import numpy as np

    if start_year is None or end_year is None:
        return {
            "available": False,
            "row_labels": [],
            "column_labels": [f"{month}月" for month in range(1, 13)],
            "matrix": np.zeros((0, 12), dtype="float64"),
            "stats": {
                "start_year": start_year,
                "end_year": end_year,
                "year_count": 0,
                "max_count": 0,
            },
        }

    years = list(range(start_year, end_year + 1))
    months = list(range(1, 13))
    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        matrix = np.zeros((len(years), len(months)), dtype="float64")
    else:
        pivot = (
            filtered.groupby(["death_year", "death_month"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=years, columns=months, fill_value=0)
        )
        matrix = pivot.to_numpy(dtype="float64")

    return {
        "available": True,
        "row_labels": [str(year) for year in years],
        "column_labels": [f"{month}月" for month in months],
        "matrix": matrix,
        "stats": {
            "start_year": start_year,
            "end_year": end_year,
            "year_count": len(years),
            "max_count": int(matrix.max()) if matrix.size else 0,
        },
    }
