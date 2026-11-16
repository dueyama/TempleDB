from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from .models import FAMILY_CATEGORY_CURRENT, FAMILY_CATEGORY_MEMORIAL

ERA_BASE_YEARS = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
    "大正": 1911,
    "明治": 1867,
}


@dataclass
class ParsedDate:
    value: date | None
    error: str = ""


def _parse_legacy_date(value: str | None) -> ParsedDate:
    cleaned = _clean_text(value)
    if not cleaned:
        return ParsedDate(value=None)
    normalized = unicodedata.normalize("NFKC", cleaned).strip()
    compact = re.sub(r"\s+", "", normalized)
    try:
        return ParsedDate(value=date.fromisoformat(compact[:10]))
    except ValueError:
        pass

    western_match = re.fullmatch(
        r"(?P<year>\d{4})[./-年](?P<month>\d{1,2})[./-月](?P<day>\d{1,2})日?",
        compact,
    )
    if western_match:
        try:
            return ParsedDate(
                value=date(
                    int(western_match.group("year")),
                    int(western_match.group("month")),
                    int(western_match.group("day")),
                )
            )
        except ValueError:
            return ParsedDate(value=None, error=f"Could not parse date '{cleaned}'.")

    era_match = re.fullmatch(
        r"(?P<era>令和|平成|昭和|大正|明治)(?P<year>元|\d+)(?:年|[./-])(?P<month>\d{1,2})(?:月|[./-])(?P<day>\d{1,2})日?",
        compact,
    )
    if era_match:
        era_name = era_match.group("era")
        year_text = era_match.group("year")
        month = int(era_match.group("month"))
        day = int(era_match.group("day"))
        era_year = 1 if year_text == "元" else int(year_text)
        try:
            return ParsedDate(
                value=date(
                    ERA_BASE_YEARS[era_name] + era_year,
                    month,
                    day,
                )
            )
        except ValueError:
            return ParsedDate(value=None, error=f"Could not parse date '{cleaned}'.")

    return ParsedDate(value=None, error=f"Could not parse date '{cleaned}'.")


def _parse_int(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_boolean(value: str | None) -> bool | None:
    cleaned = _clean_text(value).lower()
    if cleaned in {"", "none"}:
        return None
    if cleaned in {"1", "-1", "true", "yes"}:
        return True
    if cleaned in {"0", "false", "no"}:
        return False
    return None


def _parse_legacy_household_notice_opt_out(value: str | None) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or cleaned == "__MDB_NULL__":
        return False
    lowered = cleaned.lower()
    return cleaned in {"×", "✕", "☓", "ｘ", "Ｘ", "x", "X"} or lowered in {
        "0",
        "false",
        "off",
        "no",
        "不要",
    }


def _is_deceased(values: dict) -> bool:
    family_category = _clean_text(values.get("家族区分"))
    if family_category == FAMILY_CATEGORY_MEMORIAL:
        return True
    if family_category == FAMILY_CATEGORY_CURRENT:
        return False
    return any(
        _has_memorial_value(values.get(column))
        for column in ("命日", "故人備考", "享年", "初盆", "年回01", "中陰01")
    )


def _join_notes(*values: str | None) -> str:
    return " / ".join(text for text in (_clean_text(value) for value in values) if text)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _has_memorial_value(value: object) -> bool:
    cleaned = _clean_text(value)
    return cleaned not in {"", "0"}


def _has_deceased_profile_data(values: dict) -> bool:
    return any(
        _has_memorial_value(values.get(column))
        for column in ("命日", "戒名", "故人備考", "享年", "初盆", "年回01", "中陰01")
    )
