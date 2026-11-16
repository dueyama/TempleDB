from __future__ import annotations

import csv
import unicodedata
from datetime import date
from pathlib import Path

from .kana import normalize_kana_for_match
from .models import FAMILY_CATEGORY_LABELS

NULL_TOKEN = "__MDB_NULL__"

HOUSEHOLD_KANA_GROUPS = [
    {"key": "all", "label": "全", "description": "すべて"},
    {"key": "a", "label": "あ", "description": "あ行"},
    {"key": "ka", "label": "か", "description": "か行"},
    {"key": "sa", "label": "さ", "description": "さ行"},
    {"key": "ta", "label": "た", "description": "た行"},
    {"key": "na", "label": "な", "description": "な行"},
    {"key": "ha", "label": "は", "description": "は行"},
    {"key": "ma", "label": "ま", "description": "ま行"},
    {"key": "ya", "label": "や", "description": "や行"},
    {"key": "ra", "label": "ら", "description": "ら行"},
    {"key": "wa", "label": "わ", "description": "わ行"},
    {"key": "digit", "label": "0-9", "description": "数字"},
    {"key": "other", "label": "他", "description": "その他"},
]
HOUSEHOLD_KANA_GROUP_LABELS = {
    item["key"]: item["description"] for item in HOUSEHOLD_KANA_GROUPS
}
HOUSEHOLD_KANA_GROUP_KEYS = {item["key"] for item in HOUSEHOLD_KANA_GROUPS}


def _clean_value(value: str | None) -> str:
    if value is None or value == NULL_TOKEN:
        return ""
    return value.strip()


def _looks_like_datetime(value: str) -> bool:
    if len(value) < 10 or value[4] != "-" or value[7] != "-":
        return False
    date_part = value[:10]
    if not (
        date_part[:4].isdigit()
        and date_part[5:7].isdigit()
        and date_part[8:10].isdigit()
    ):
        return False
    if len(value) == 10:
        return True
    return value[10] in {" ", "T"}


def _display_value(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    if _looks_like_datetime(cleaned):
        return cleaned[:10]
    return cleaned


def _normalize_household_browse_text(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    converted = []
    for char in normalized:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            converted.append(chr(code - 0x60))
        elif char in {" ", "　", "-", "ｰ", "－", "―"}:
            continue
        else:
            converted.append(char.lower())
    return "".join(converted)


def _search_text(value: str | None) -> str:
    normalized = _normalize_household_browse_text(value)
    if normalized:
        return normalized
    return _clean_value(value).replace(" ", "").replace("　", "").lower()


def _sort_text(value: str | None) -> str:
    return _search_text(value)


def _int_sort(value: str | None) -> int:
    try:
        return int(_clean_value(value))
    except ValueError:
        return 0


def _sort_date(value: str | None) -> str:
    cleaned = _display_value(value)
    return cleaned or "9999-99-99"


def _parse_iso_date(value: str | None) -> date | None:
    cleaned = _display_value(value)
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return None


def _read_csv_rows(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({key: _clean_value(value) for key, value in row.items()})
    return rows


def _clean_row_record(raw_record: dict | None) -> dict[str, str]:
    if not raw_record:
        return {}
    return {str(key): _clean_value(value) for key, value in raw_record.items()}


def _has_value(value: str | None) -> bool:
    cleaned = _clean_value(value)
    return cleaned not in {"", "0"}


def _join_values(*values: str | None) -> str:
    return " ".join(_display_value(value) for value in values if _display_value(value))


def _normalize_same_name_text(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    return "".join(char for char in normalized if char not in {" ", "　"})


def _same_name_key(name: str | None, kana: str | None = None) -> str:
    normalized_name = _normalize_same_name_text(name)
    if normalized_name:
        return normalized_name
    return normalize_kana_for_match(kana)


def _household_group_key(kana: str | None, name: str | None = None) -> str:
    normalized = _normalize_household_browse_text(kana)
    if not normalized:
        normalized = _normalize_household_browse_text(name)
    if not normalized:
        return "other"

    first = normalized[0]
    if first.isdigit():
        return "digit"
    if first in {"ぁ", "あ", "ぃ", "い", "ぅ", "う", "ぇ", "え", "ぉ", "お", "ゔ"}:
        return "a"
    if first in {"か", "が", "き", "ぎ", "く", "ぐ", "け", "げ", "こ", "ご"}:
        return "ka"
    if first in {"さ", "ざ", "し", "じ", "す", "ず", "せ", "ぜ", "そ", "ぞ"}:
        return "sa"
    if first in {"た", "だ", "ち", "ぢ", "っ", "つ", "づ", "て", "で", "と", "ど"}:
        return "ta"
    if first in {"な", "に", "ぬ", "ね", "の"}:
        return "na"
    if first in {"は", "ば", "ぱ", "ひ", "び", "ぴ", "ふ", "ぶ", "ぷ", "へ", "べ", "ぺ", "ほ", "ぼ", "ぽ"}:
        return "ha"
    if first in {"ま", "み", "む", "め", "も"}:
        return "ma"
    if first in {"や", "ゃ", "ゆ", "ゅ", "よ", "ょ"}:
        return "ya"
    if first in {"ら", "り", "る", "れ", "ろ"}:
        return "ra"
    if first in {"わ", "ゎ", "を", "ん"}:
        return "wa"
    return "other"


def _family_category_display(value: str | None) -> str:
    cleaned = _clean_value(value)
    return FAMILY_CATEGORY_LABELS.get(cleaned, cleaned)
