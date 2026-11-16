from __future__ import annotations

from datetime import date

from .data_science_shared import *  # noqa: F401,F403

__all__ = [
    "_all_missing_month_day_groups",
    "_empty_month_day_grid_rows",
    "_top_month_day_rows",
    "_selected_month_day_records",
    "_top_month_day_details",
    "_month_day_details",
]


def _all_missing_month_day_groups() -> list[dict]:
    groups = []
    for month in range(1, 13):
        dates: list[str] = []
        for day in range(1, 32):
            try:
                date(2000, month, day)
            except ValueError:
                continue
            dates.append(f"{month}/{day}")
        groups.append({"month": month, "month_label": f"{month}月", "dates": dates})
    return groups


def _empty_month_day_grid_rows() -> list[dict]:
    rows = []
    for month in range(1, 13):
        cells = []
        for day in range(1, 32):
            try:
                date(2000, month, day)
                valid = True
            except ValueError:
                valid = False
            cells.append(
                {
                    "valid": valid,
                    "month": month if valid else None,
                    "day": day,
                    "label": f"{month}/{day}" if valid else "",
                    "count": 0 if valid else None,
                    "has_records": False,
                    "modal_id": f"month-day-{month}-{day}" if valid else "",
                    "style": _detail_heatmap_cell_style(0, 0) if valid else "",
                }
            )
        rows.append({"month": month, "month_label": f"{month}月", "cells": cells})
    return rows


def _top_month_day_rows(counts: dict[tuple[int, int], int]) -> list[dict]:
    rows = [
        {
            "label": f"{int(month)}/{int(day)}",
            "month": int(month),
            "day": int(day),
            "modal_id": f"month-day-{int(month)}-{int(day)}",
            "count": int(count),
        }
        for (month, day), count in counts.items()
        if count > 0
    ]
    rows.sort(key=lambda item: (-item["count"], item["month"], item["day"]))
    return rows[:15]


def _selected_month_day_records(dataframe, selected_month_day: dict | None) -> list[dict]:
    import pandas as pd

    if selected_month_day is None or dataframe.empty:
        return []
    filtered = dataframe[
        (dataframe["death_month"] == selected_month_day["month"])
        & (dataframe["death_day"] == selected_month_day["day"])
    ].sort_values(["death_date", "person_id"], ascending=[False, False])
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


def _top_month_day_details(dataframe, top_month_day_rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "rows": _selected_month_day_records(
                dataframe,
                {"month": row["month"], "day": row["day"], "label": row["label"]},
            ),
        }
        for row in top_month_day_rows
    ]


def _month_day_details(dataframe, grid_rows: list[dict]) -> list[dict]:
    details = []
    for row in grid_rows:
        for cell in row["cells"]:
            if not cell.get("has_records"):
                continue
            details.append(
                {
                    **cell,
                    "rows": _selected_month_day_records(
                        dataframe,
                        {
                            "month": cell["month"],
                            "day": cell["day"],
                            "label": cell["label"],
                        },
                    ),
                }
            )
    return details


def _detail_heatmap_cell_style(count: int, max_count: int) -> str:
    if count <= 0 or max_count <= 0:
        return "background: rgba(201,110,47,0.08); color: #5d4631;"
    ratio = count / max_count
    alpha = 0.18 + (ratio * 0.72)
    text = "#ffffff" if ratio >= 0.45 else "#4d3828"
    return f"background: rgba(201,110,47,{alpha:.3f}); color: {text};"
