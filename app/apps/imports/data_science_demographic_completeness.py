from __future__ import annotations

from .data_science_shared import (
    GENDER_LABELS,
    WEEKDAYS_JA,
    _clean_value,
    _display_value,
    completeness_labels,
)

__all__ = [
    "_completeness_by_decade_analysis",
    "_series_rows",
    "_member_field_value",
    "_normalize_gender",
    "_weekday_label_from_monday_index",
    "_group_counts_by_gender",
    "_parse_positive_int",
    "_age_bucket_label",
    "_age_bucket_labels",
]


def _completeness_by_decade_analysis(dataframe, *, start_year: int | None, end_year: int | None) -> dict:
    import pandas as pd

    active_completeness_labels = completeness_labels()
    empty_float_series = pd.Series(dtype="float64")
    empty_series_map = {label: empty_float_series for label in active_completeness_labels}
    if start_year is None or end_year is None or dataframe.empty:
        return {
            "available": False,
            "series_map": empty_series_map,
            "rows": [],
            "stats": {
                "start_decade": None,
                "end_decade": None,
            },
        }

    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        return {
            "available": False,
            "series_map": empty_series_map,
            "rows": [],
            "stats": {
                "start_decade": None,
                "end_decade": None,
            },
        }

    filtered["death_decade"] = filtered["death_year"].apply(lambda year: int(year) // 10 * 10)
    grouped = (
        filtered.groupby("death_decade")
        .agg(
            total_count=("person_id", "size"),
            age_rate=("age_at_death", lambda values: float(values.notna().mean() * 100.0)),
            homyo_rate=("has_homyo", lambda values: float(values.astype(bool).mean() * 100.0)),
            gender_rate=("has_gender_value", lambda values: float(values.astype(bool).mean() * 100.0)),
        )
        .sort_index()
    )
    decade_labels = [f"{int(index)}年代" for index in grouped.index.tolist()]
    series_map = {
        active_completeness_labels[0]: pd.Series(
            grouped["age_rate"].tolist(),
            index=decade_labels,
            dtype="float64",
        ),
        active_completeness_labels[1]: pd.Series(
            grouped["homyo_rate"].tolist(),
            index=decade_labels,
            dtype="float64",
        ),
        active_completeness_labels[2]: pd.Series(
            grouped["gender_rate"].tolist(),
            index=decade_labels,
            dtype="float64",
        ),
    }

    return {
        "available": True,
        "series_map": series_map,
        "rows": [
            {
                "decade_label": f"{int(index)}年代",
                "total_count": int(grouped.loc[index, "total_count"]),
                "age_rate": round(float(grouped.loc[index, "age_rate"]), 1),
                "homyo_rate": round(float(grouped.loc[index, "homyo_rate"]), 1),
                "gender_rate": round(float(grouped.loc[index, "gender_rate"]), 1),
            }
            for index in grouped.index.tolist()
        ],
        "stats": {
            "start_decade": int(grouped.index.min()),
            "end_decade": int(grouped.index.max()),
        },
    }


def _series_rows(series) -> list[dict]:
    return [
        {
            "label": str(index),
            "count": int(value),
        }
        for index, value in series.items()
    ]


def _member_field_value(member: dict, label: str) -> str:
    for pair in member.get("display_fields") or []:
        if pair.get("label") == label:
            return _display_value(pair.get("value"))
    for pair in member.get("raw_fields") or []:
        if pair.get("label") == label:
            return _display_value(pair.get("value"))
    return ""


def _normalize_gender(value: str) -> str:
    normalized = _display_value(value)
    if normalized in {"男", "女"}:
        return normalized
    return "不明"


def _weekday_label_from_monday_index(index: int | float) -> str | None:
    if index != index:
        return None
    numeric = int(index)
    return WEEKDAYS_JA[(numeric + 1) % 7]


def _group_counts_by_gender(dataframe, column_name: str, categories, *, label_fn=str):
    import pandas as pd

    labels = [label_fn(category) for category in categories]
    series_map: dict[str, pd.Series] = {}
    for gender in GENDER_LABELS:
        counts = (
            dataframe[dataframe["gender"] == gender][column_name]
            .value_counts()
            .reindex(categories, fill_value=0)
        )
        counts.index = labels
        series_map[gender] = counts
    return series_map


def _parse_positive_int(value: str | None) -> int | None:
    cleaned = _clean_value(value)
    if not cleaned.isdigit():
        return None
    parsed = int(cleaned)
    if parsed < 0:
        return None
    return parsed


def _age_bucket_label(age: int | None) -> str | None:
    if age is None:
        return None
    numeric = int(age)
    if numeric < 10:
        return "10歳未満"
    if numeric >= 100:
        return "100歳以上"
    decade = (numeric // 10) * 10
    return f"{decade}代"


def _age_bucket_labels() -> list[str]:
    return ["10歳未満"] + [f"{bucket}代" for bucket in range(10, 100, 10)] + ["100歳以上"]
