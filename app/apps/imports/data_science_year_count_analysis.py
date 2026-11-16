from __future__ import annotations

import math

from .data_science_shared import AVERAGE_AGE_TREND_WINDOW_YEARS


def _year_count_diagnostics(year_counts) -> dict:
    if len(year_counts) == 0:
        return {
            "available": False,
            "row_labels": [],
            "observed_series": year_counts,
            "trend_series": year_counts,
            "stats": {
                "year_count": 0,
                "window_years": AVERAGE_AGE_TREND_WINDOW_YEARS,
                "mean_count": None,
                "variance_count": None,
                "pearson_dispersion": None,
                "rule_label": "中心 5年の moving average を trend とみなし、残差で Pearson dispersion を見ます。",
            },
        }

    observed = year_counts.astype("float64")
    trend = observed.rolling(
        window=AVERAGE_AGE_TREND_WINDOW_YEARS,
        center=True,
        min_periods=1,
    ).mean()
    valid = trend > 0
    pearson_terms = (
        ((observed[valid] - trend[valid]) ** 2) / trend[valid]
        if valid.any()
        else observed.iloc[0:0]
    )
    pearson_dispersion = (
        round(float(pearson_terms.mean()), 2) if len(pearson_terms) > 0 else None
    )

    return {
        "available": True,
        "row_labels": [str(index) for index in observed.index.tolist()],
        "observed_series": observed,
        "trend_series": trend,
        "stats": {
            "year_count": int(len(observed)),
            "window_years": AVERAGE_AGE_TREND_WINDOW_YEARS,
            "mean_count": round(float(observed.mean()), 2),
            "variance_count": round(float(observed.var(ddof=0)), 2),
            "pearson_dispersion": pearson_dispersion,
            "rule_label": "中心 5年の moving average を trend とみなし、残差で Pearson dispersion を見ます。",
        },
    }


def _year_count_distribution_analysis(year_counts) -> dict:
    rule_label = (
        "各年の往生件数を 1 年 = 1 観測として集計し、"
        "平均と標準偏差から正規分布、年平均 λ から Poisson 分布を重ねます。"
    )
    if len(year_counts) == 0:
        return {
            "available": False,
            "count_values": [],
            "frequency_values": [],
            "fit_x_values": [],
            "fit_y_values": [],
            "poisson_count_values": [],
            "poisson_frequency_values": [],
            "stats": {
                "year_count": 0,
                "mean_count": None,
                "std_count": None,
                "poisson_lambda": None,
                "min_count": None,
                "max_count": None,
                "rule_label": rule_label,
            },
        }

    observed = year_counts.astype("float64")
    observed_int = observed.astype("int64")
    frequency_series = observed_int.value_counts().sort_index()
    count_values = [int(index) for index in frequency_series.index.tolist()]
    frequency_values = [int(value) for value in frequency_series.tolist()]
    mean_count = float(observed.mean())
    std_count = float(observed.std(ddof=0))

    fit_x_values: list[float] = []
    fit_y_values: list[float] = []
    poisson_count_values: list[int] = []
    poisson_frequency_values: list[float] = []
    if std_count > 0 and count_values:
        lower_bound = max(0.0, float(min(count_values)) - 1.0)
        upper_bound = float(max(count_values)) + 1.0
        step_count = 240
        step = (upper_bound - lower_bound) / step_count if upper_bound > lower_bound else 0.05
        fit_x_values = [lower_bound + step * index for index in range(step_count + 1)]
        fit_y_values = [
            len(observed)
            * (1.0 / (std_count * math.sqrt(2.0 * math.pi)))
            * math.exp(-((value - mean_count) ** 2) / (2.0 * (std_count**2)))
            for value in fit_x_values
        ]
    if count_values:
        poisson_upper = max(
            max(count_values),
            int(math.ceil(mean_count + 4.0 * math.sqrt(mean_count))),
        )
        poisson_count_values = list(range(max(0, poisson_upper) + 1))
        poisson_frequency_values = [
            len(observed)
            * math.exp(-mean_count)
            * (mean_count**value)
            / math.factorial(value)
            for value in poisson_count_values
        ]

    return {
        "available": True,
        "count_values": count_values,
        "frequency_values": frequency_values,
        "fit_x_values": fit_x_values,
        "fit_y_values": fit_y_values,
        "poisson_count_values": poisson_count_values,
        "poisson_frequency_values": poisson_frequency_values,
        "stats": {
            "year_count": int(len(observed)),
            "mean_count": round(mean_count, 2),
            "std_count": round(std_count, 2),
            "poisson_lambda": round(mean_count, 2),
            "min_count": int(observed.min()),
            "max_count": int(observed.max()),
            "rule_label": rule_label,
        },
    }
