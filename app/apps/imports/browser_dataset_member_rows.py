from __future__ import annotations

from . import browser_dataset_display, household_profile_runtime, memorial_shared, runtime_shared
from .models import FAMILY_CATEGORY_CURRENT, FAMILY_CATEGORY_MEMORIAL

_display_pairs = browser_dataset_display._display_pairs
_non_empty_pairs = browser_dataset_display._non_empty_pairs
_DISPLAY_COLUMN_KAIMYO = browser_dataset_display._DISPLAY_COLUMN_KAIMYO


def _date_with_wareki_display(value: str | None) -> str:
    display_value = runtime_shared._display_value(value)
    parsed_date = runtime_shared._parse_iso_date(display_value)
    if parsed_date is None:
        return display_value
    wareki_year = memorial_shared._to_wareki_year_numeric(parsed_date.year)
    return f"{parsed_date.year}({wareki_year})年{parsed_date.month}月{parsed_date.day}日"


def _sorted_household_person_rows(
    persons_by_household: dict[str, list[dict]],
    household_key: str,
) -> list[dict]:
    return sorted(
        persons_by_household.get(household_key, []),
        key=lambda item: (
            runtime_shared._int_sort(item.get("行番号")),
            runtime_shared._sort_text(item.get("氏名")),
        ),
    )


def _member_type_labels(row: dict) -> tuple[str, str]:
    member_type = "memorial" if _is_memorial_person(row) else "current"
    member_type_label = "過去帳" if member_type == "memorial" else "現在帳"
    return member_type, member_type_label


def _same_name_source_member_summary(row: dict, household_name: str) -> dict:
    member_type, member_type_label = _member_type_labels(row)
    name = row.get("氏名", "")
    kana = row.get("ﾌﾘｶﾞﾅ", "")
    return {
        "person_id": row.get("家族ID", ""),
        "household_id": row.get("台帳ID", ""),
        "household_name": household_name,
        "name": name,
        "kana": kana,
        "relationship": row.get("続柄", ""),
        "member_type": member_type,
        "member_type_label": member_type_label,
        "death_date": runtime_shared._display_value(row.get("命日")),
        "kaimyo": row.get("戒名", ""),
        "note": runtime_shared._join_values(row.get("個人備考"), row.get("故人備考")),
        "same_name_key": runtime_shared._same_name_key(name, kana),
    }


def _sort_memorial_members(memorial_members: list[dict]) -> list[dict]:
    def sort_key(item: dict) -> tuple[int, int, str, int]:
        death_date = runtime_shared._parse_iso_date(item.get("death_date_iso"))
        return (
            1 if death_date is None else 0,
            -death_date.toordinal() if death_date is not None else 0,
            runtime_shared._sort_text(item.get("name")),
            runtime_shared._int_sort(item.get("person_id")),
        )

    return sorted(memorial_members, key=sort_key)


def _person_summary(row: dict) -> dict:
    family_category = runtime_shared._clean_value(row.get("家族区分"))
    memorial_notice_opt_out = household_profile_runtime._parse_legacy_boolish(row.get("年回案内不要", ""))
    kana_is_auto_generated = runtime_shared._clean_value(row.get("__kana_is_auto_generated")).lower() == "true"
    gender_display = runtime_shared._clean_value(row.get("性別")) or "未決定"
    death_date = runtime_shared._display_value(row.get("命日"))
    death_date_display = _date_with_wareki_display(row.get("命日"))
    return {
        "person_id": row.get("家族ID", ""),
        "household_id": row.get("台帳ID", ""),
        "name": row.get("氏名", ""),
        "kana": row.get("ﾌﾘｶﾞﾅ", ""),
        "kana_is_auto_generated": kana_is_auto_generated,
        "death_date": death_date,
        "death_date_display": death_date_display,
        "death_date_iso": death_date,
        "relationship": row.get("続柄", ""),
        "kaimyo": row.get("戒名", ""),
        "family_category": family_category,
        "family_category_label": runtime_shared._family_category_display(family_category),
        "age_at_death": runtime_shared._clean_value(row.get("享年")),
        "age_unit": runtime_shared._clean_value(row.get("享年単位")) or "歳",
        "note": runtime_shared._join_values(row.get("個人備考"), row.get("故人備考")),
        "legacy_hatsubon_flag": row.get("初盆", ""),
        "memorial_notice_opt_out": memorial_notice_opt_out,
        "display_fields": _display_pairs(
            {
                "家族ID": row.get("家族ID", ""),
                "氏名": row.get("氏名", ""),
                "ﾌﾘｶﾞﾅ": row.get("ﾌﾘｶﾞﾅ", ""),
                "かな補完": "自動" if kana_is_auto_generated else "",
                "家族区分": runtime_shared._family_category_display(family_category),
                "〒": row.get("〒", ""),
                "住所1": row.get("住所1", ""),
                "住所2": row.get("住所2", ""),
                "住所3": row.get("住所3", ""),
                "電話": row.get("電話", ""),
                "携帯": row.get("携帯", ""),
                "Email": row.get("Email", ""),
                "続柄": row.get("続柄", ""),
                "性別": gender_display,
                "生年月日": row.get("生年月日", ""),
                _DISPLAY_COLUMN_KAIMYO: row.get("戒名", ""),
                "命日": death_date_display,
                "享年": runtime_shared._join_values(row.get("享年"), row.get("享年単位")),
                "初盆": row.get("初盆", ""),
                "年回案内不要": "オン" if memorial_notice_opt_out else "",
                "個人備考": row.get("個人備考", ""),
                "故人備考": row.get("故人備考", ""),
            },
            [
                "家族ID",
                "氏名",
                "ﾌﾘｶﾞﾅ",
                "かな補完",
                "家族区分",
                "〒",
                "住所1",
                "住所2",
                "住所3",
                "電話",
                "携帯",
                "Email",
                "続柄",
                "性別",
                "生年月日",
                _DISPLAY_COLUMN_KAIMYO,
                "命日",
                "享年",
                "初盆",
                "年回案内不要",
                "個人備考",
                "故人備考",
            ],
        ),
        "raw_fields": _non_empty_pairs(row),
    }


def _is_placeholder_person_row(row: dict) -> bool:
    if any(
        runtime_shared._has_value(row.get(column))
        for column in ("氏名", "ﾌﾘｶﾞﾅ", "続柄", "命日", "戒名", "享年", "故人備考", "年回01", "中陰01")
    ):
        return False
    return runtime_shared._clean_value(row.get("家族区分")) == FAMILY_CATEGORY_MEMORIAL


def _is_memorial_person(row: dict) -> bool:
    family_category = runtime_shared._clean_value(row.get("家族区分"))
    if family_category == FAMILY_CATEGORY_MEMORIAL:
        return True
    if family_category == FAMILY_CATEGORY_CURRENT:
        return False
    return any(
        runtime_shared._has_value(row.get(column))
        for column in ("命日", "中陰01", "年回01", "享年", "故人備考", "初盆")
    )
