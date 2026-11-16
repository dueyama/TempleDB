from __future__ import annotations

from datetime import date, timedelta

from apps.core.services import tenant_policy as tenant_policy_services

NULL_TOKEN = "__MDB_NULL__"
ERA_STARTS = [
    {"name": "令和", "start": date(2019, 5, 1)},
    {"name": "平成", "start": date(1989, 1, 8)},
    {"name": "昭和", "start": date(1926, 12, 25)},
    {"name": "大正", "start": date(1912, 7, 30)},
    {"name": "明治", "start": date(1868, 1, 25)},
]
KANJI_DIGITS = {
    0: "",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}
MEMORIAL_RANKS = [1, 3, 7, 13, 17, 25, 33, 50]
KIJITSU_STEPS = [
    {"label": "初七日", "offset_days": 6},
    {"label": "二七日", "offset_days": 13},
    {"label": "三七日", "offset_days": 20},
    {"label": "四七日", "offset_days": 27},
    {"label": "五七日", "offset_days": 34},
    {"label": "六七日", "offset_days": 41},
    {"label": "満中陰（四十九日）", "offset_days": 48},
    {"label": "百ヶ日", "offset_days": 99},
]
WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"]


def _clean_value(value: str | None) -> str:
    if value is None or value == NULL_TOKEN:
        return ""
    return value.strip()


def _memorial_offset_years(memorial_rank: int) -> int:
    return 1 if memorial_rank == 1 else max(memorial_rank - 1, 0)


def _replace_year_clamped(original: date, target_year: int) -> date:
    try:
        return original.replace(year=target_year)
    except ValueError:
        return original.replace(year=target_year, day=28)


def _add_memorial_years(death_date: date, memorial_years: int) -> date:
    year_offset = _memorial_offset_years(memorial_years)
    return _replace_year_clamped(death_date, death_date.year + year_offset)


def _add_memorial_offset_years(death_date: date, offset_years: int) -> date:
    return _replace_year_clamped(death_date, death_date.year + max(offset_years, 0))


def _first_obon_date(death_date: date) -> date:
    same_year_obon = date(death_date.year, 8, 13)
    manchuin_date = death_date + timedelta(days=48)
    if same_year_obon >= manchuin_date:
        return same_year_obon
    return date(death_date.year + 1, 8, 13)


def _to_kanji_number(value: int) -> str:
    if not isinstance(value, int) or value <= 0:
        return str(value)
    if value > 9999:
        return str(value)

    thousands = value // 1000
    hundreds = (value % 1000) // 100
    tens = (value % 100) // 10
    ones = value % 10

    def with_unit(digit: int, unit: str) -> str:
        if digit == 0:
            return ""
        if digit == 1:
            return unit
        return f"{KANJI_DIGITS[digit]}{unit}"

    return (
        f"{with_unit(thousands, '千')}"
        f"{with_unit(hundreds, '百')}"
        f"{with_unit(tens, '十')}"
        f"{KANJI_DIGITS[ones]}"
    )


def _to_zenkaku_digits(value: int | str) -> str:
    return str(value).translate(str.maketrans("0123456789", "０１２３４５６７８９"))


def _to_kanji_year_digits(value: int | str) -> str:
    return str(value).translate(str.maketrans("0123456789", "〇一二三四五六七八九"))


def _to_memorial_label(rank: int) -> str:
    return "一周忌" if rank == 1 else f"{_to_kanji_number(rank)}回忌"


def _to_memorial_label_from_offset(offset_years: int) -> str:
    if offset_years == 1:
        return "一周忌"
    return f"{_to_kanji_number(offset_years + 1)}回忌"


def _to_wareki_date(target: date) -> str:
    for era in ERA_STARTS:
        if target >= era["start"]:
            year_in_era = target.year - era["start"].year + 1
            era_year = "元" if year_in_era == 1 else _to_kanji_number(year_in_era)
            return (
                f"{era['name']}{era_year}年"
                f"{_to_kanji_number(target.month)}月"
                f"{_to_kanji_number(target.day)}日"
            )
    return f"{target.year}年{target.month}月{target.day}日"


def _to_wareki_date_numeric(target: date) -> str:
    for era in ERA_STARTS:
        if target >= era["start"]:
            year_in_era = target.year - era["start"].year + 1
            return f"{era['name']}{year_in_era}年{target.month}月{target.day}日"
    return f"{target.year}年{target.month}月{target.day}日"


def _to_wareki_year_numeric(year: int) -> str:
    target = date(year, 1, 1)
    for era in ERA_STARTS:
        if target >= era["start"]:
            year_in_era = target.year - era["start"].year + 1
            return f"{era['name']}{year_in_era}"
    return str(year)


def _kijitsu_offset_days_from_label(label: str | None) -> int | None:
    normalized_label = _clean_value(label)
    if not normalized_label:
        return None
    normalized_without_paren = normalized_label.split("（", 1)[0].strip()
    for step in KIJITSU_STEPS:
        step_label = _clean_value(step["label"])
        if not step_label:
            continue
        if normalized_label == step_label:
            return step["offset_days"]
        if normalized_without_paren and normalized_without_paren == step_label.split("（", 1)[0].strip():
            return step["offset_days"]
    return None


def _effective_memorial_rules(memorial_rules: list[dict]) -> list[dict]:
    if memorial_rules:
        return tenant_policy_services.normalize_memorial_rules(
            memorial_rules,
            context="memorial rules",
        )
    return tenant_policy_services.get_memorial_rules(
        fallback_rules=_hardcoded_default_memorial_rules(),
    )


def _hardcoded_default_memorial_rules() -> list[dict]:
    return [
        {
            "years": _memorial_offset_years(rank),
            "label": _to_memorial_label(rank),
            "seq": index,
        }
        for index, rank in enumerate(MEMORIAL_RANKS, start=1)
    ]


def _memorial_offset_years_from_label(label: str | None) -> int | None:
    cleaned = _clean_value(label)
    if not cleaned:
        return None
    for rank in range(1, 101):
        if _to_memorial_label(rank) == cleaned:
            return _memorial_offset_years(rank)
    for rule in _effective_memorial_rules([]):
        if _clean_value(rule.get("label")) == cleaned:
            try:
                return max(int(rule["years"]), 0)
            except (TypeError, ValueError, KeyError):
                return None
    return None


def _format_month_day_kanji(target: date) -> str:
    month_kanji = _to_kanji_number(target.month)
    day_kanji = _to_kanji_number(target.day)
    total_width = 7
    day_padding = "　" * max(0, total_width - (len(month_kanji) + 1 + len(day_kanji) + 1))
    return f"{month_kanji}月{day_padding}{day_kanji}日"


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]
