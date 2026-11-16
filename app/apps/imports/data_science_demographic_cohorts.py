from __future__ import annotations

import math

from .data_science_demographic_completeness import (
    _age_bucket_label,
    _age_bucket_labels,
    _member_field_value,
    _normalize_gender,
    _parse_positive_int,
    _weekday_label_from_monday_index,
)
from .data_science_shared import (
    ANALYTICS_YEAR_LOWER_QUANTILE,
    AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER,
    AVERAGE_AGE_TREND_LABELS,
    AVERAGE_AGE_TREND_WINDOW_YEARS,
    COHORT_MODE_OPTIONS,
    _display_value,
    _parse_iso_date,
)

__all__ = [
    "_memorial_members_dataframe",
    "_analysis_year_range",
    "_analysis_year_rule_label",
    "_normalize_cohort_mode",
    "_cohort_mode_label",
    "_cohort_mode_colorbar_label",
    "_cohort_mode_options",
    "_normalize_matrix_by_column",
    "_cohort_matrix_for_mode",
    "_death_decade_age_analysis",
    "_death_decade_month_analysis",
    "_average_age_trend_analysis",
    "_annual_age_sum_trend_analysis",
]


def _memorial_members_dataframe(memorial_members: list[dict]):
    import pandas as pd

    rows = [
        {
            "person_id": member.get("person_id", ""),
            "household_id": member.get("household_id", ""),
            "household_name": member.get("household_name", ""),
            "name": member.get("name", ""),
            "gender": _normalize_gender(_member_field_value(member, "性別")),
            "has_gender_value": bool(_member_field_value(member, "性別")),
            "death_date_raw": _display_value(
                member.get("death_date_raw") or member.get("death_date_iso")
            ),
            "death_date": _parse_iso_date(member.get("death_date_iso")),
            "age_at_death": _parse_positive_int(member.get("age_at_death")),
            "has_homyo": bool(_display_value(member.get("kaimyo"))),
        }
        for member in memorial_members
    ]
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return pd.DataFrame(
            columns=[
                "person_id",
                "household_id",
                "household_name",
                "name",
                "gender",
                "has_gender_value",
                "death_date_raw",
                "death_date",
                "age_at_death",
                "has_homyo",
                "death_year",
                "death_month",
                "death_day",
                "death_weekday_label",
            ]
        )
    dataframe["death_date"] = pd.to_datetime(dataframe["death_date"])
    dataframe["death_year"] = dataframe["death_date"].dt.year
    dataframe["death_month"] = dataframe["death_date"].dt.month
    dataframe["death_day"] = dataframe["death_date"].dt.day
    dataframe["death_weekday_label"] = dataframe["death_date"].dt.dayofweek.apply(
        _weekday_label_from_monday_index
    )
    return dataframe


def _analysis_year_range(year_series) -> dict:
    if len(year_series) == 0:
        return {
            "start": None,
            "end": None,
            "lower_quantile": ANALYTICS_YEAR_LOWER_QUANTILE,
        }
    start = int(
        year_series.quantile(ANALYTICS_YEAR_LOWER_QUANTILE, interpolation="nearest")
    )
    end = int(year_series.max())
    return {
        "start": start,
        "end": end,
        "lower_quantile": ANALYTICS_YEAR_LOWER_QUANTILE,
    }


def _analysis_year_rule_label(analysis_year_range: dict) -> str:
    percentage = int(analysis_year_range.get("lower_quantile", 0) * 100)
    return f"命日年の下位 {percentage}% を外れ値として別表示"


def _normalize_cohort_mode(value: str | None) -> str:
    return value if value in {"share", "count"} else "share"


def _cohort_mode_label(mode: str) -> str:
    return "年代内構成比" if mode == "share" else "実件数"


def _cohort_mode_colorbar_label(mode: str) -> str:
    return "%" if mode == "share" else "件数"


def _cohort_mode_options(selected_mode: str) -> list[dict]:
    return [
        {
            **option,
            "selected": option["value"] == selected_mode,
        }
        for option in COHORT_MODE_OPTIONS
    ]


def _normalize_matrix_by_column(matrix):
    import numpy as np

    values = np.asarray(matrix, dtype="float64")
    if values.size == 0:
        return values
    column_totals = values.sum(axis=0)
    normalized = np.zeros_like(values, dtype="float64")
    nonzero = column_totals > 0
    normalized[:, nonzero] = values[:, nonzero] / column_totals[nonzero] * 100.0
    return normalized


def _cohort_matrix_for_mode(analysis: dict, mode: str):
    return analysis["share_matrix"] if mode == "share" else analysis["count_matrix"]


def _death_decade_age_analysis(dataframe, *, start_year: int | None, end_year: int | None) -> dict:
    import numpy as np
    import pandas as pd

    row_labels = _age_bucket_labels()
    if start_year is None or end_year is None or dataframe.empty:
        return {
            "count_matrix": np.zeros((len(row_labels), 0)),
            "share_matrix": np.zeros((len(row_labels), 0)),
            "row_labels": row_labels,
            "column_labels": [],
            "stats": {
                "start_decade": None,
                "end_decade": None,
                "cohort_counts": [],
            },
        }

    start_decade = (start_year // 10) * 10
    end_decade = (end_year // 10) * 10
    decade_values = list(range(start_decade, end_decade + 10, 10))
    column_labels = [f"{value}年代" for value in decade_values]
    filtered = dataframe[
        (dataframe["death_year"] >= start_year)
        & (dataframe["death_year"] <= end_year)
    ].copy()
    filtered["age_bucket"] = filtered["age_at_death"].apply(_age_bucket_label)
    filtered["death_decade"] = filtered["death_year"].apply(lambda year: int(year) // 10 * 10)
    pivot = pd.pivot_table(
        filtered,
        index="age_bucket",
        columns="death_decade",
        values="person_id",
        aggfunc="count",
        fill_value=0,
    ).reindex(index=row_labels, columns=decade_values, fill_value=0)
    count_matrix = pivot.to_numpy(dtype="float64")
    return {
        "count_matrix": count_matrix,
        "share_matrix": _normalize_matrix_by_column(count_matrix),
        "row_labels": row_labels,
        "column_labels": column_labels,
        "stats": {
            "start_decade": start_decade,
            "end_decade": end_decade,
            "cohort_counts": [
                {
                    "label": label,
                    "count": int(count_matrix[:, index].sum()),
                }
                for index, label in enumerate(column_labels)
            ],
        },
    }


def _death_decade_month_analysis(dataframe, *, start_year: int | None, end_year: int | None) -> dict:
    import numpy as np
    import pandas as pd

    month_values = list(range(1, 13))
    row_labels = [f"{value}月" for value in month_values]
    if start_year is None or end_year is None or dataframe.empty:
        return {
            "count_matrix": np.zeros((len(row_labels), 0)),
            "share_matrix": np.zeros((len(row_labels), 0)),
            "row_labels": row_labels,
            "column_labels": [],
            "stats": {
                "start_decade": None,
                "end_decade": None,
                "cohort_counts": [],
            },
        }

    start_decade = (start_year // 10) * 10
    end_decade = (end_year // 10) * 10
    decade_values = list(range(start_decade, end_decade + 10, 10))
    column_labels = [f"{value}年代" for value in decade_values]
    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    filtered["death_decade"] = filtered["death_year"].apply(lambda year: int(year) // 10 * 10)
    pivot = pd.pivot_table(
        filtered,
        index="death_month",
        columns="death_decade",
        values="person_id",
        aggfunc="count",
        fill_value=0,
    ).reindex(index=month_values, columns=decade_values, fill_value=0)
    count_matrix = pivot.to_numpy(dtype="float64")
    return {
        "count_matrix": count_matrix,
        "share_matrix": _normalize_matrix_by_column(count_matrix),
        "row_labels": row_labels,
        "column_labels": column_labels,
        "stats": {
            "start_decade": start_decade,
            "end_decade": end_decade,
            "cohort_counts": [
                {
                    "label": label,
                    "count": int(count_matrix[:, index].sum()),
                }
                for index, label in enumerate(column_labels)
            ],
        },
    }


def _average_age_trend_analysis(
    dataframe,
    *,
    start_year: int | None,
    end_year: int | None,
    window_years: int = AVERAGE_AGE_TREND_WINDOW_YEARS,
) -> dict:
    import pandas as pd

    empty_series_map = {
        label: pd.Series(dtype="float64")
        for label in AVERAGE_AGE_TREND_LABELS
    }
    empty_stats = {
        "start_year": start_year,
        "end_year": end_year,
        "window_years": window_years,
        "window_rule_label": "",
        "trend_rule_label": "",
        "trend_rows": [],
        "input_count": 0,
        "included_count": 0,
        "excluded_count": 0,
        "excluded_below_count": 0,
        "excluded_above_count": 0,
        "iqr_filter_applied": False,
        "pre_iqr_mean_age": None,
        "pre_iqr_median_age": None,
        "post_iqr_mean_age": None,
        "lower_bound": None,
        "upper_bound": None,
        "rule_label": "分析レンジ内に享年データがありません。",
    }
    if start_year is None or end_year is None or dataframe.empty:
        return {
            "series_map": empty_series_map,
            "annual_series_map": empty_series_map,
            "trend_series_map": empty_series_map,
            "stats": empty_stats,
        }

    filtered = dataframe[
        (dataframe["death_year"] >= start_year)
        & (dataframe["death_year"] <= end_year)
        & (dataframe["age_at_death"].notna())
    ].copy()
    if filtered.empty:
        return {
            "series_map": empty_series_map,
            "annual_series_map": empty_series_map,
            "trend_series_map": empty_series_map,
            "stats": empty_stats,
        }

    age_series = filtered["age_at_death"].astype(float)
    q1 = float(age_series.quantile(0.25))
    q3 = float(age_series.quantile(0.75))
    iqr = q3 - q1
    if len(filtered) < 4 or iqr <= 0:
        iqr_filter_applied = False
        lower_bound = float(age_series.min())
        upper_bound = float(age_series.max())
        cleaned = filtered.copy()
        rule_label = "享年分布が狭いため、外れ値除外は行っていません。"
    else:
        iqr_filter_applied = True
        lower_bound = max(0.0, q1 - (AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER * iqr))
        upper_bound = q3 + (AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER * iqr)
        cleaned = filtered[
            (filtered["age_at_death"] >= lower_bound)
            & (filtered["age_at_death"] <= upper_bound)
        ].copy()
        rule_label = (
            "分析レンジ内の享年分布に対して IQR 法 "
            f"(Q1 - {AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER:.1f}×IQR, "
            f"Q3 + {AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER:.1f}×IQR) を適用しています。"
        )

    years = list(range(start_year, end_year + 1))
    year_labels = [str(year) for year in years]
    half_window = window_years // 2
    if window_years % 2 == 1:
        window_rule_label = f"各年を中心に前後{half_window}年の対象者全員で平均しています。"
    else:
        window_rule_label = f"各年を中心とした {window_years} 年窓の対象者全員で平均しています。"

    def annual_mean(frame) -> pd.Series:
        totals = (
            frame.groupby("death_year")["age_at_death"].sum().reindex(years, fill_value=0.0)
        ).astype("float64")
        counts = (
            frame.groupby("death_year")["age_at_death"].size().reindex(years, fill_value=0)
        ).astype("float64")
        series = totals.div(counts.where(lambda values: values > 0))
        series.index = year_labels
        return series.astype("float64").round(1)

    def window_mean(frame) -> pd.Series:
        totals = (
            frame.groupby("death_year")["age_at_death"].sum().reindex(years, fill_value=0.0)
        ).astype("float64")
        counts = (
            frame.groupby("death_year")["age_at_death"].size().reindex(years, fill_value=0)
        ).astype("float64")
        series = totals.rolling(window=window_years, center=True, min_periods=1).sum().div(
            counts.rolling(window=window_years, center=True, min_periods=1)
            .sum()
            .where(lambda values: values > 0)
        )
        series.index = year_labels
        return series.astype("float64").round(1)

    def trend_series(series: pd.Series) -> dict:
        valid_points: list[tuple[int, float]] = []
        for index, value in series.items():
            if pd.isna(value):
                continue
            try:
                year = int(index)
            except (TypeError, ValueError):
                continue
            valid_points.append((year, float(value)))
        trend = pd.Series([math.nan] * len(series.index), index=series.index, dtype="float64")
        if len(valid_points) < 2:
            return {
                "series": trend,
                "slope_per_year": None,
                "slope_per_decade": None,
                "slope_per_year_label": "-",
                "slope_per_decade_label": "-",
            }

        x_values = [point[0] for point in valid_points]
        y_values = [point[1] for point in valid_points]
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(y_values) / len(y_values)
        denominator = sum((value - x_mean) ** 2 for value in x_values)
        slope = (
            0.0
            if denominator == 0
            else sum((x - x_mean) * (y - y_mean) for x, y in valid_points) / denominator
        )
        intercept = y_mean - (slope * x_mean)
        for index in trend.index:
            try:
                year = int(index)
            except (TypeError, ValueError):
                continue
            trend.loc[index] = intercept + (slope * year)
        return {
            "series": trend.round(1),
            "slope_per_year": round(slope, 3),
            "slope_per_decade": round(slope * 10, 2),
            "slope_per_year_label": f"{slope:+.3f} 歳/年",
            "slope_per_decade_label": f"{(slope * 10):+.2f} 歳/10年",
        }

    annual_series_map = {
        "合計": annual_mean(cleaned),
        "男": annual_mean(cleaned[cleaned["gender"] == "男"]),
        "女": annual_mean(cleaned[cleaned["gender"] == "女"]),
    }
    smoothed_series_map = {
        "合計": window_mean(cleaned),
        "男": window_mean(cleaned[cleaned["gender"] == "男"]),
        "女": window_mean(cleaned[cleaned["gender"] == "女"]),
    }
    trend_analysis_map = {
        label: trend_series(series) for label, series in smoothed_series_map.items()
    }
    return {
        "series_map": smoothed_series_map,
        "annual_series_map": annual_series_map,
        "trend_series_map": {
            label: trend_analysis["series"] for label, trend_analysis in trend_analysis_map.items()
        },
        "stats": {
            "start_year": start_year,
            "end_year": end_year,
            "window_years": window_years,
            "window_rule_label": window_rule_label,
            "trend_rule_label": "破線は表示中の5年平均に対する線形トレンド直線です。",
            "trend_rows": [
                {
                    "label": label,
                    "slope_per_year": trend_analysis["slope_per_year"],
                    "slope_per_decade": trend_analysis["slope_per_decade"],
                    "slope_per_year_label": trend_analysis["slope_per_year_label"],
                    "slope_per_decade_label": trend_analysis["slope_per_decade_label"],
                }
                for label, trend_analysis in trend_analysis_map.items()
            ],
            "input_count": int(len(filtered)),
            "included_count": int(len(cleaned)),
            "excluded_count": int(len(filtered) - len(cleaned)),
            "excluded_below_count": int(
                (filtered["age_at_death"] < lower_bound).sum()
            ),
            "excluded_above_count": int(
                (filtered["age_at_death"] > upper_bound).sum()
            ),
            "iqr_filter_applied": iqr_filter_applied,
            "pre_iqr_mean_age": round(float(age_series.mean()), 1),
            "pre_iqr_median_age": round(float(age_series.median()), 1),
            "post_iqr_mean_age": round(
                float(cleaned["age_at_death"].astype(float).mean()),
                1,
            ),
            "lower_bound": round(lower_bound, 1),
            "upper_bound": round(upper_bound, 1),
            "rule_label": rule_label,
        },
    }


def _annual_age_sum_trend_analysis(
    dataframe,
    *,
    start_year: int | None,
    end_year: int | None,
) -> dict:
    import pandas as pd

    empty_series_map = {
        label: pd.Series(dtype="float64")
        for label in AVERAGE_AGE_TREND_LABELS
    }
    empty_stats = {
        "start_year": start_year,
        "end_year": end_year,
        "input_count": 0,
        "max_sum": None,
        "max_year": None,
        "rule_label": "分析レンジ内に享年データがありません。",
    }
    if start_year is None or end_year is None or dataframe.empty:
        return {"series_map": empty_series_map, "stats": empty_stats}

    filtered = dataframe[
        (dataframe["death_year"] >= start_year)
        & (dataframe["death_year"] <= end_year)
        & (dataframe["age_at_death"].notna())
    ].copy()
    if filtered.empty:
        return {"series_map": empty_series_map, "stats": empty_stats}

    years = list(range(start_year, end_year + 1))
    year_labels = [str(year) for year in years]

    def yearly_sum(frame) -> pd.Series:
        series = (
            frame.groupby("death_year")["age_at_death"]
            .sum()
            .reindex(years, fill_value=0.0)
            .astype("float64")
        )
        series.index = year_labels
        return series

    total_series = yearly_sum(filtered)
    max_sum = float(total_series.max()) if len(total_series) else None
    max_year = str(total_series.idxmax()) if max_sum is not None else None
    return {
        "series_map": {
            "合計": total_series,
            "男": yearly_sum(filtered[filtered["gender"] == "男"]),
            "女": yearly_sum(filtered[filtered["gender"] == "女"]),
        },
        "stats": {
            "start_year": start_year,
            "end_year": end_year,
            "input_count": int(len(filtered)),
            "max_sum": round(max_sum, 1) if max_sum is not None else None,
            "max_year": max_year,
            "rule_label": "分析用命日年レンジ内で、享年がある往生者の享年を年ごとに合計しています。",
        },
    }
