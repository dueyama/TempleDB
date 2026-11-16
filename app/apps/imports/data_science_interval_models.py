from __future__ import annotations

import math
from datetime import date


def _poisson_process_consistency_analysis(
    dataframe,
    *,
    start_year: int | None,
    end_year: int | None,
    interval_stats: dict,
) -> dict:
    rule_label = "指数側は命日間隔、Poisson 側は年次件数と日次件数で見ています。"
    if (
        start_year is None
        or end_year is None
        or dataframe.empty
        or interval_stats.get("count", 0) <= 0
        or interval_stats.get("mean_days") in (None, 0)
    ):
        return {
            "available": False,
            "year_count": 0,
            "calendar_day_count": 0,
            "interval_rate_per_year": None,
            "yearly_rate_per_year": None,
            "interval_cv": None,
            "yearly_fano": None,
            "rows": [],
            "rule_label": rule_label,
        }

    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        return {
            "available": False,
            "year_count": 0,
            "calendar_day_count": 0,
            "interval_rate_per_year": None,
            "yearly_rate_per_year": None,
            "interval_cv": None,
            "yearly_fano": None,
            "rows": [],
            "rule_label": rule_label,
        }

    full_years = list(range(start_year, end_year + 1))
    year_counts = (
        filtered["death_year"].value_counts().reindex(full_years, fill_value=0).sort_index()
    )
    year_count = len(full_years)
    calendar_day_count = (date(end_year, 12, 31) - date(start_year, 1, 1)).days + 1
    filtered_count = int(len(filtered))
    interval_count = max(filtered_count - 1, 0)
    sorted_filtered = filtered.sort_values(["death_date", "person_id"])
    observed_span_days = (
        int((sorted_filtered["death_date"].iloc[-1] - sorted_filtered["death_date"].iloc[0]).days)
        if filtered_count >= 2
        else 0
    )

    mean_days = float(interval_stats["mean_days"])
    interval_rate_per_day = (1.0 / mean_days) if mean_days > 0 else None
    interval_rate_per_day_from_span = (
        (interval_count / observed_span_days)
        if interval_count > 0 and observed_span_days > 0
        else None
    )
    interval_rate_per_year = (
        interval_rate_per_day * 365.2425 if interval_rate_per_day is not None else None
    )
    yearly_rate_per_year = float(year_counts.mean()) if year_count else None
    yearly_rate_per_day = (
        yearly_rate_per_year / 365.2425 if yearly_rate_per_year is not None else None
    )
    calendar_rate_per_day = (
        (filtered_count / calendar_day_count) if calendar_day_count > 0 else None
    )
    median_days = interval_stats.get("median_days")
    expected_median_days = (
        math.log(2.0) / interval_rate_per_day if interval_rate_per_day not in (None, 0) else None
    )
    mean_days_from_span = (
        (observed_span_days / interval_count)
        if interval_count > 0 and observed_span_days > 0
        else None
    )

    std_days_value = interval_stats.get("std_days")
    interval_cv = None
    if (
        std_days_value is not None
        and mean_days > 0
        and math.isfinite(float(std_days_value))
    ):
        interval_cv = float(std_days_value) / mean_days

    yearly_fano = None
    if yearly_rate_per_year is not None and yearly_rate_per_year > 0:
        yearly_variance = float(year_counts.var(ddof=0))
        yearly_fano = yearly_variance / yearly_rate_per_year

    normalized_dates = filtered["death_date"].dt.normalize()
    observed_multi_day_count = int(normalized_dates.value_counts().ge(2).sum())
    observed_multi_day_share = (
        (observed_multi_day_count / calendar_day_count) * 100 if calendar_day_count else None
    )
    predicted_multi_day_share = None
    if yearly_rate_per_day is not None:
        predicted_multi_day_share = (
            1.0 - math.exp(-yearly_rate_per_day) * (1.0 + yearly_rate_per_day)
        ) * 100

    observed_zero_year_count = int((year_counts == 0).sum())
    observed_zero_year_share = ((observed_zero_year_count / year_count) * 100) if year_count else None
    predicted_zero_year_share = (
        math.exp(-yearly_rate_per_year) * 100 if yearly_rate_per_year is not None else None
    )

    def _fmt(value: float | int | None, digits: int = 2) -> str:
        if value is None or not math.isfinite(float(value)):
            return "-"
        return f"{float(value):.{digits}f}"

    rows = [
        {
            "label": "平均間隔",
            "observed": f"差分平均 {_fmt(mean_days, 1)} 日",
            "reference": f"観測スパン {observed_span_days}日 / 間隔数 {interval_count} = {_fmt(mean_days_from_span, 1)} 日",
            "hint": "隣接差分の総和は、最初と最後の命日の差に一致します。",
        },
        {
            "label": "日換算 λ（間隔）",
            "observed": f"1 / 平均間隔 = {_fmt(interval_rate_per_day, 5)} 件/日",
            "reference": f"{interval_count} / {observed_span_days}日 = {_fmt(interval_rate_per_day_from_span, 5)} 件/日",
            "hint": "平均間隔の逆数と、総スパンから出す日次率が一致するかを見ます。",
        },
        {
            "label": "日換算 λ（単純平均）",
            "observed": f"間隔由来 {_fmt(interval_rate_per_day, 5)} 件/日",
            "reference": f"総件数 {filtered_count} / 分析日数 {calendar_day_count} = {_fmt(calendar_rate_per_day, 5)} 件/日",
            "hint": "分析レンジ全体の日次平均で均した場合の値です。",
        },
        {
            "label": "年換算 λ",
            "observed": f"{_fmt(interval_rate_per_year, 2)} 件/年",
            "reference": f"総件数 {filtered_count} / 分析年数 {year_count} = {_fmt(yearly_rate_per_year, 2)} 件/年",
            "hint": "間隔平均の指数近似と、年ごとの件数平均が近いかを見ます。",
        },
        {
            "label": "中央値",
            "observed": f"実測 {_fmt(median_days, 1)} 日",
            "reference": f"指数近似 {_fmt(expected_median_days, 1)} 日",
            "hint": "指数分布なら中央値は 平均 × ln(2) に近づきます。",
        },
        {
            "label": "変動係数 CV",
            "observed": _fmt(interval_cv, 2),
            "reference": "指数理論 1.00",
            "hint": "間隔の標準偏差 / 平均です。指数分布では 1 に近づきます。",
        },
        {
            "label": "年次 Fano",
            "observed": _fmt(yearly_fano, 2),
            "reference": "Poisson 理論 1.00",
            "hint": "年別件数の 分散 / 平均 です。Poisson では 1 が基準です。",
        },
        {
            "label": "0件の年",
            "observed": f"{_fmt(observed_zero_year_share, 2)}% ({observed_zero_year_count}/{year_count}年)",
            "reference": f"Poisson 予測 {_fmt(predicted_zero_year_share, 2)}%",
            "hint": "年ごとの空年が、Poisson の無発生確率とどの程度合うかです。",
        },
        {
            "label": "2件以上ある日",
            "observed": f"{_fmt(observed_multi_day_share, 3)}% ({observed_multi_day_count}日)",
            "reference": f"Poisson 予測 {_fmt(predicted_multi_day_share, 3)}%",
            "hint": "同日に複数件ある頻度を、日次 Poisson 近似と比べています。",
        },
    ]

    return {
        "available": True,
        "filtered_count": filtered_count,
        "interval_count": interval_count,
        "year_count": year_count,
        "calendar_day_count": calendar_day_count,
        "observed_span_days": observed_span_days,
        "interval_rate_per_year": round(interval_rate_per_year, 2)
        if interval_rate_per_year is not None
        else None,
        "yearly_rate_per_year": round(yearly_rate_per_year, 2)
        if yearly_rate_per_year is not None
        else None,
        "interval_cv": round(interval_cv, 2) if interval_cv is not None else None,
        "yearly_fano": round(yearly_fano, 2) if yearly_fano is not None else None,
        "rows": rows,
        "rule_label": rule_label,
    }


def _interval_survival_analysis(intervals: list[int], *, mean_days: float | None) -> dict:
    if not intervals:
        return {
            "available": False,
            "count": 0,
            "mean_days": mean_days,
            "max_days": None,
            "x_values": [],
            "empirical_survival": [],
            "theoretical_survival": [],
        }

    sorted_intervals = sorted(int(value) for value in intervals)
    unique_values = sorted(set([0, *sorted_intervals]))
    count = len(sorted_intervals)
    empirical_survival: list[float] = []
    cursor = 0
    for value in unique_values:
        while cursor < count and sorted_intervals[cursor] < value:
            cursor += 1
        empirical_survival.append((count - cursor) / count)

    if mean_days is not None and mean_days > 0:
        theoretical_survival = [math.exp(-value / mean_days) for value in unique_values]
    else:
        theoretical_survival = []

    return {
        "available": True,
        "count": count,
        "mean_days": mean_days,
        "max_days": int(max(sorted_intervals)),
        "x_values": unique_values,
        "empirical_survival": empirical_survival,
        "theoretical_survival": theoretical_survival,
    }


def _interval_qq_analysis(intervals: list[int], *, mean_days: float | None) -> dict:
    if not intervals or mean_days is None or mean_days <= 0:
        return {
            "available": False,
            "observed_quantiles": [],
            "theoretical_quantiles": [],
        }

    sorted_intervals = sorted(float(value) for value in intervals)
    count = len(sorted_intervals)
    probabilities = [(index + 0.5) / count for index in range(count)]
    theoretical_quantiles = [
        -mean_days * math.log(1.0 - probability)
        for probability in probabilities
    ]
    return {
        "available": True,
        "observed_quantiles": sorted_intervals,
        "theoretical_quantiles": theoretical_quantiles,
    }
