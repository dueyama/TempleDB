from __future__ import annotations

import math
from datetime import date, timedelta

# Star-import precedence is part of this compatibility surface: shared names load
# first, then explicit month/day detail helpers take precedence.
# isort: off
from .data_science_shared import *  # noqa: F401,F403
from .data_science_month_day_details import (
    _all_missing_month_day_groups,
    _empty_month_day_grid_rows,
    _top_month_day_rows,
)
# isort: on

__all__ = [
    "_month_day_distribution",
    "_month_day_bias_analysis",
    "_month_day_overlap_distribution_analysis",
    "_heatmap_cell_style",
]


def _month_day_distribution(dataframe) -> dict:
    import numpy as np

    matrix = np.full((12, 31), np.nan)
    if dataframe.empty:
        return {
            "matrix": matrix,
            "grid_rows": _empty_month_day_grid_rows(),
            "missing_groups": _all_missing_month_day_groups(),
            "top_days": [],
            "stats": {
                "observed_count": 0,
                "missing_count": 366,
                "total_count": 366,
            },
        }

    counts = (
        dataframe.groupby(["death_month", "death_day"])
        .size()
        .to_dict()
    )
    max_count = max((int(count) for count in counts.values()), default=0)
    seen = set()
    missing_groups: list[dict] = []
    grid_rows: list[dict] = []
    missing_count = 0
    for month in range(1, 13):
        missing_dates: list[str] = []
        cells: list[dict] = []
        for day in range(1, 32):
            try:
                date(2000, month, day)
            except ValueError:
                cells.append(
                    {
                        "valid": False,
                        "day": day,
                        "label": "",
                        "count": None,
                        "has_records": False,
                        "modal_id": "",
                        "style": "",
                    }
                )
                continue
            count = int(counts.get((month, day), 0))
            matrix[month - 1, day - 1] = count
            cells.append(
                {
                    "valid": True,
                    "month": month,
                    "day": day,
                    "label": f"{month}/{day}",
                    "count": count,
                    "has_records": count > 0,
                    "modal_id": f"month-day-{month}-{day}",
                    "style": _heatmap_cell_style(count, max_count),
                }
            )
            if count > 0:
                seen.add((month, day))
            else:
                missing_dates.append(f"{month}/{day}")
                missing_count += 1
        missing_groups.append(
            {
                "month": month,
                "month_label": f"{month}月",
                "dates": missing_dates,
            }
        )
        grid_rows.append(
            {
                "month": month,
                "month_label": f"{month}月",
                "cells": cells,
            }
        )

    return {
        "matrix": matrix,
        "grid_rows": grid_rows,
        "missing_groups": missing_groups,
        "top_days": _top_month_day_rows(counts),
        "stats": {
            "observed_count": len(seen),
            "missing_count": missing_count,
            "total_count": len(seen) + missing_count,
        },
    }


def _month_day_expected_matrix(
    dataframe,
    *,
    observation_start: date,
    observation_end: date,
):
    import numpy as np

    expected_matrix = np.full((12, 31), np.nan)
    for month in range(1, 13):
        for day in range(1, 32):
            try:
                date(2000, month, day)
            except ValueError:
                continue
            expected_matrix[month - 1, day - 1] = 0.0

    if dataframe.empty or observation_end < observation_start:
        return expected_matrix

    year_counts = dataframe["death_year"].dropna().astype(int).value_counts()
    for year, count in year_counts.items():
        window_start = max(observation_start, date(int(year), 1, 1))
        window_end = min(observation_end, date(int(year), 12, 31))
        if window_end < window_start:
            continue
        observed_day_count = (window_end - window_start).days + 1
        expected_per_observed_day = float(count) / observed_day_count
        current_date = window_start
        while current_date <= window_end:
            expected_matrix[current_date.month - 1, current_date.day - 1] += (
                expected_per_observed_day
            )
            current_date += timedelta(days=1)
    return expected_matrix


def _month_day_bias_analysis(
    matrix,
    *,
    exposure_dataframe=None,
    observation_start: date | None = None,
    observation_end: date | None = None,
) -> dict:
    import numpy as np

    valid_mask = np.isfinite(matrix)
    observed_total = float(np.nansum(matrix))
    valid_day_count = int(valid_mask.sum())
    use_exposure_adjustment = (
        exposure_dataframe is not None
        and observation_start is not None
        and observation_end is not None
    )
    if use_exposure_adjustment:
        expected_matrix = _month_day_expected_matrix(
            exposure_dataframe,
            observation_start=observation_start,
            observation_end=observation_end,
        )
    else:
        expected = (observed_total / valid_day_count) if valid_day_count else 0.0
        expected_matrix = np.where(valid_mask, expected, np.nan)
    bias_matrix = np.where(valid_mask, matrix - expected_matrix, np.nan)
    finite_expected = expected_matrix[np.isfinite(expected_matrix)]
    expected_mean = float(finite_expected.mean()) if finite_expected.size else 0.0
    expected_min = float(finite_expected.min()) if finite_expected.size else 0.0
    expected_max = float(finite_expected.max()) if finite_expected.size else 0.0
    rows = []
    for month in range(1, 13):
        for day in range(1, 32):
            value = bias_matrix[month - 1, day - 1]
            if np.isnan(value):
                continue
            actual = int(matrix[month - 1, day - 1])
            expected = float(expected_matrix[month - 1, day - 1])
            rows.append(
                {
                    "label": f"{month}/{day}",
                    "month": month,
                    "day": day,
                    "modal_id": f"month-day-{month}-{day}",
                    "actual": actual,
                    "expected": round(expected, 2),
                    "bias": round(float(value), 2),
                }
            )
    rows.sort(key=lambda item: (-item["bias"], item["month"], item["day"]))
    return {
        "matrix": bias_matrix,
        "expected_matrix": expected_matrix,
        "top_rows": rows[:15],
        "stats": {
            "expected_per_day": round(expected_mean, 2),
            "expected_min": round(expected_min, 2),
            "expected_max": round(expected_max, 2),
            "valid_day_count": valid_day_count,
            "exposure_adjusted": use_exposure_adjustment,
            "observation_start": observation_start.isoformat()
            if observation_start is not None
            else None,
            "observation_end": observation_end.isoformat()
            if observation_end is not None
            else None,
        },
    }


def _month_day_overlap_distribution_analysis(
    matrix,
    *,
    exclude_february_29: bool = False,
) -> dict:
    import numpy as np

    if exclude_february_29:
        rule_label = (
            "完了年だけを対象に、同じ暦露出を持つ通常月日365セルの件数分布を見ます。"
            "2月29日は露出年数が少ないため、このPoisson比較から除外しています。"
            "総件数固定なら各セルは Binomial / Multinomial、"
            "総件数もランダムなら各セルは Poisson で近似できます。"
        )
    else:
        rule_label = (
            "ヒートマップ 1 セル = 1 月日として、366 セルの件数分布を見ます。"
            "総件数固定なら各セルは Binomial / Multinomial、"
            "総件数もランダムなら各セルは Poisson で近似でき、"
            "正規分布は λ が十分大きいときの近似です。"
        )

    values = np.array(matrix, dtype="float64", copy=True)
    february_29_count = None
    if values.ndim == 2 and values.shape[0] >= 2 and values.shape[1] >= 29:
        february_29_value = values[1, 28]
        if np.isfinite(february_29_value):
            february_29_count = int(february_29_value)
        if exclude_february_29:
            values[1, 28] = np.nan
    valid_values = values[np.isfinite(values)]
    if valid_values.size == 0:
        return {
            "available": False,
            "count_values": [],
            "observed_frequency_values": [],
            "expected_poisson_values": [],
            "stats": {
                "valid_day_count": 0,
                "observed_total": 0,
                "lambda_per_day": None,
                "variance_count": None,
                "fano": None,
                "max_count": None,
                "overlap_day_count": 0,
                "overlap_day_share": None,
                "predicted_overlap_day_share": None,
                "excluded_february_29": exclude_february_29,
                "february_29_count": february_29_count,
                "rule_label": rule_label,
            },
        }

    valid_counts = [int(value) for value in valid_values.tolist()]
    valid_day_count = len(valid_counts)
    observed_total = int(sum(valid_counts))
    lambda_per_day = (observed_total / valid_day_count) if valid_day_count else None
    variance_count = float(np.var(valid_counts)) if valid_day_count else None
    fano = (
        (variance_count / lambda_per_day)
        if variance_count is not None and lambda_per_day not in (None, 0)
        else None
    )
    max_count = max(valid_counts, default=0)
    count_values = list(range(max_count + 1))
    observed_frequency = {
        count_value: valid_counts.count(count_value)
        for count_value in count_values
    }
    expected_poisson_values = []
    for count_value in count_values:
        if lambda_per_day is None:
            expected_poisson_values.append(0.0)
            continue
        probability = (
            math.exp(-lambda_per_day)
            * (lambda_per_day**count_value)
            / math.factorial(count_value)
        )
        expected_poisson_values.append(valid_day_count * probability)

    overlap_day_count = int(sum(1 for value in valid_counts if value >= 2))
    overlap_day_share = (
        (overlap_day_count / valid_day_count) * 100.0 if valid_day_count else None
    )
    predicted_overlap_day_share = None
    if lambda_per_day is not None:
        predicted_overlap_day_share = (
            1.0 - math.exp(-lambda_per_day) * (1.0 + lambda_per_day)
        ) * 100.0

    return {
        "available": True,
        "count_values": count_values,
        "observed_frequency_values": [
            int(observed_frequency.get(count_value, 0))
            for count_value in count_values
        ],
        "expected_poisson_values": expected_poisson_values,
        "stats": {
            "valid_day_count": valid_day_count,
            "observed_total": observed_total,
            "lambda_per_day": round(lambda_per_day, 3)
            if lambda_per_day is not None
            else None,
            "variance_count": round(variance_count, 3)
            if variance_count is not None
            else None,
            "fano": round(fano, 3) if fano is not None else None,
            "max_count": max_count,
            "overlap_day_count": overlap_day_count,
            "overlap_day_share": round(overlap_day_share, 2)
            if overlap_day_share is not None
            else None,
            "predicted_overlap_day_share": round(predicted_overlap_day_share, 2)
            if predicted_overlap_day_share is not None
            else None,
            "excluded_february_29": exclude_february_29,
            "february_29_count": february_29_count,
            "rule_label": rule_label,
        },
    }


def _heatmap_cell_style(count: int, max_count: int) -> str:
    if count <= 0 or max_count <= 0:
        return "background: rgba(201,110,47,0.08); color: #5d4631;"
    ratio = count / max_count
    alpha = 0.18 + (ratio * 0.72)
    text = "#ffffff" if ratio >= 0.45 else "#4d3828"
    return f"background: rgba(201,110,47,{alpha:.3f}); color: {text};"
