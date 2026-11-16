from __future__ import annotations

from .data_science_shared import (
    HOMYO_INGO_SUFFIXES,
    HOMYO_INGO_TYPE_LABELS,
    HOMYO_PREFIX_TOKENS,
    _display_value,
    _parse_iso_date,
)

__all__ = [
    "_homyo_character_analysis",
    "_normalize_homyo_for_character_analysis",
    "_homyo_order_issue",
    "_parse_homyo_parts",
    "_homyo_ingo_analysis",
    "_homyo_ingo_type_analysis",
    "_homyo_ingo_type_label",
]


def _homyo_character_analysis(memorial_members: list[dict]) -> dict:
    from collections import Counter

    import pandas as pd

    homyo_names = []
    for member in memorial_members:
        value = _display_value(member.get("kaimyo"))
        if value:
            homyo_names.append(value)

    counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for homyo in homyo_names:
        parts = _parse_homyo_parts(homyo)
        normalized = parts["homyo"]
        if not normalized:
            continue
        seen_chars: set[str] = set()
        for character in normalized:
            counter[character] += 1
            if character not in seen_chars:
                examples.setdefault(character, [])
                if len(examples[character]) < 3:
                    examples[character].append(homyo)
                seen_chars.add(character)

    rows = [
        {
            "character": character,
            "count": int(count),
            "examples": examples.get(character, []),
        }
        for character, count in counter.most_common(18)
    ]
    series = pd.Series(
        [row["count"] for row in rows],
        index=[row["character"] for row in rows],
        dtype="int64",
    )
    return {
        "rows": rows,
        "series": series,
        "stats": {
            "homyo_count": len(homyo_names),
            "with_ingo_count": sum(
                1 for value in homyo_names if _parse_homyo_parts(value)["has_ingo"]
            ),
            "without_ingo_count": sum(
                1 for value in homyo_names if not _parse_homyo_parts(value)["has_ingo"]
            ),
            "unique_character_count": len(counter),
        },
    }


def _normalize_homyo_for_character_analysis(value: str) -> str:
    return _parse_homyo_parts(value)["homyo"]


def _homyo_order_issue(member: dict) -> dict | None:
    raw_value = _display_value(member.get("kaimyo"))
    if not raw_value:
        return None
    normalized = raw_value.replace("（旧字）", "").replace("　", "").replace(" ", "")
    prefix = next((token for token in HOMYO_PREFIX_TOKENS if normalized.startswith(token)), "")
    if not prefix:
        return None
    parts = _parse_homyo_parts(raw_value)
    if not parts["has_ingo"] or not parts["homyo"]:
        return None
    suggested = f'{parts["ingo"]}{parts["prefix"]}{parts["homyo"]}'
    if suggested == parts["full"]:
        return None
    return {
        "person_id": member.get("person_id", ""),
        "household_id": member.get("household_id", ""),
        "household_name": member.get("household_name", ""),
        "name": member.get("name", ""),
        "relationship": member.get("relationship", ""),
        "kaimyo": raw_value,
        "suggested_kaimyo": suggested,
        "ingo": parts["ingo"],
        "prefix": parts["prefix"],
        "homyo": parts["homyo"],
    }


def _parse_homyo_parts(value: str) -> dict[str, str | bool]:
    normalized = _display_value(value).replace("（旧字）", "").replace("　", "").replace(" ", "")
    if not normalized:
        return {
            "full": "",
            "ingo": "",
            "has_ingo": False,
            "prefix": "",
            "homyo": "",
        }

    ingo = ""
    prefix = ""
    remainder = normalized
    for token in HOMYO_PREFIX_TOKENS:
        if remainder.startswith(token):
            prefix = token
            remainder = remainder[len(token) :]
            break
    if not prefix:
        prefix_positions = [
            (index, token)
            for token in HOMYO_PREFIX_TOKENS
            if (index := normalized.find(token)) > 0
        ]
        if prefix_positions:
            prefix_start, token = min(prefix_positions, key=lambda item: item[0])
            candidate = normalized[:prefix_start]
            if len(candidate) > 1 and candidate.endswith(HOMYO_INGO_SUFFIXES):
                ingo = candidate
                prefix = token
                remainder = normalized[prefix_start + len(token) :]
            else:
                remainder = normalized
    if not ingo:
        for index, character in enumerate(remainder[:-1]):
            if index > 0 and character in HOMYO_INGO_SUFFIXES:
                ingo = remainder[: index + 1]
                remainder = remainder[index + 1 :]
                break

    return {
        "full": normalized,
        "ingo": ingo,
        "has_ingo": bool(ingo),
        "prefix": prefix,
        "homyo": remainder,
    }


def _homyo_ingo_analysis(
    memorial_members: list[dict],
    *,
    start_year: int | None,
    end_year: int | None,
) -> dict:
    import pandas as pd

    rows = []
    for member in memorial_members:
        homyo_value = _display_value(member.get("kaimyo"))
        death_date = _parse_iso_date(member.get("death_date_iso"))
        if not homyo_value or death_date is None:
            continue
        rows.append(
            {
                "death_year": death_date.year,
                "has_ingo": bool(_parse_homyo_parts(homyo_value)["has_ingo"]),
            }
        )

    if start_year is None or end_year is None or not rows:
        return {
            "series": pd.Series(dtype="float64"),
            "rows": [],
            "stats": {
                "start_decade": None,
                "end_decade": None,
                "with_ingo_count": 0,
                "without_ingo_count": 0,
                "homyo_count": 0,
            },
        }

    dataframe = pd.DataFrame(rows)
    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        return {
            "series": pd.Series(dtype="float64"),
            "rows": [],
            "stats": {
                "start_decade": (start_year // 10) * 10,
                "end_decade": (end_year // 10) * 10,
                "with_ingo_count": 0,
                "without_ingo_count": 0,
                "homyo_count": 0,
            },
        }

    filtered["death_decade"] = filtered["death_year"].apply(lambda year: int(year) // 10 * 10)
    grouped = (
        filtered.groupby("death_decade")
        .agg(total_count=("has_ingo", "size"), with_ingo_count=("has_ingo", "sum"))
        .sort_index()
    )
    grouped["without_ingo_count"] = grouped["total_count"] - grouped["with_ingo_count"]
    grouped["ingo_rate"] = grouped["with_ingo_count"] / grouped["total_count"] * 100.0
    series = pd.Series(
        grouped["ingo_rate"].tolist(),
        index=[f"{int(index)}年代" for index in grouped.index.tolist()],
        dtype="float64",
    )
    rows = [
        {
            "decade_label": f"{int(index)}年代",
            "with_ingo_count": int(row["with_ingo_count"]),
            "without_ingo_count": int(row["without_ingo_count"]),
            "total_count": int(row["total_count"]),
            "ingo_rate": round(float(row["ingo_rate"]), 1),
        }
        for index, row in grouped.iterrows()
    ]
    return {
        "series": series,
        "rows": rows,
        "stats": {
            "start_decade": int(grouped.index.min()),
            "end_decade": int(grouped.index.max()),
            "with_ingo_count": int(filtered["has_ingo"].sum()),
            "without_ingo_count": int((~filtered["has_ingo"]).sum()),
            "homyo_count": int(len(filtered)),
        },
    }


def _homyo_ingo_type_analysis(
    memorial_members: list[dict],
    *,
    start_year: int | None,
    end_year: int | None,
) -> dict:
    import pandas as pd

    rows = []
    for member in memorial_members:
        homyo_value = _display_value(member.get("kaimyo"))
        death_date = _parse_iso_date(member.get("death_date_iso"))
        if not homyo_value or death_date is None:
            continue
        parts = _parse_homyo_parts(homyo_value)
        rows.append(
            {
                "death_year": death_date.year,
                "ingo_type": _homyo_ingo_type_label(parts),
            }
        )

    empty_series_map = {
        label: pd.Series(dtype="float64")
        for label in HOMYO_INGO_TYPE_LABELS
    }
    if start_year is None or end_year is None or not rows:
        return {
            "series_map": empty_series_map,
            "column_labels": [],
            "rows": [],
        }

    dataframe = pd.DataFrame(rows)
    filtered = dataframe[
        (dataframe["death_year"] >= start_year) & (dataframe["death_year"] <= end_year)
    ].copy()
    if filtered.empty:
        return {
            "series_map": empty_series_map,
            "column_labels": [],
            "rows": [],
        }

    filtered["death_decade"] = filtered["death_year"].apply(lambda year: int(year) // 10 * 10)
    grouped = (
        filtered.groupby(["death_decade", "ingo_type"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=HOMYO_INGO_TYPE_LABELS, fill_value=0)
        .sort_index()
    )
    decade_labels = [f"{int(index)}年代" for index in grouped.index.tolist()]
    totals = grouped.sum(axis=1)
    share_grouped = grouped.div(totals.where(totals > 0, 1), axis=0) * 100.0
    series_map = {
        label: pd.Series(share_grouped[label].tolist(), index=decade_labels, dtype="float64")
        for label in HOMYO_INGO_TYPE_LABELS
    }
    rows = [
        {
            "decade_label": f"{int(index)}年代",
            "in_count": int(grouped.loc[index, "院"]),
            "an_count": int(grouped.loc[index, "庵"]),
            "ken_count": int(grouped.loc[index, "軒"]),
            "none_count": int(grouped.loc[index, "院号なし"]),
            "in_share": round(float(share_grouped.loc[index, "院"]), 1),
            "an_share": round(float(share_grouped.loc[index, "庵"]), 1),
            "ken_share": round(float(share_grouped.loc[index, "軒"]), 1),
            "none_share": round(float(share_grouped.loc[index, "院号なし"]), 1),
            "total_count": int(totals.loc[index]),
        }
        for index in grouped.index.tolist()
    ]
    return {
        "series_map": series_map,
        "column_labels": decade_labels,
        "rows": rows,
    }


def _homyo_ingo_type_label(parts: dict[str, str | bool]) -> str:
    ingo = str(parts.get("ingo", ""))
    if not ingo:
        return "院号なし"
    suffix = ingo[-1]
    if suffix in HOMYO_INGO_SUFFIXES:
        return suffix
    return "院号なし"


__all__ = [
    "_homyo_character_analysis",
    "_normalize_homyo_for_character_analysis",
    "_homyo_order_issue",
    "_parse_homyo_parts",
    "_homyo_ingo_analysis",
    "_homyo_ingo_type_analysis",
    "_homyo_ingo_type_label",
]
