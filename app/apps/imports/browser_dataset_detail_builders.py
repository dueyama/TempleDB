from __future__ import annotations

from . import (
    browser_dataset_display,
    browser_dataset_same_name,
    household_profile_runtime,
    runtime_shared,
)
from .browser_dataset_rows import (
    _event_summary,
    _household_summary_sort_key,
    _is_placeholder_person_row,
    _is_yuen_household_row,
    _member_type_labels,
    _person_summary,
    _sort_date,
    _sort_memorial_members,
    _sorted_household_person_rows,
)

HOUSEHOLD_KANA_GROUP_LABELS = runtime_shared.HOUSEHOLD_KANA_GROUP_LABELS
_display_pairs = browser_dataset_display._display_pairs
_non_empty_pairs = browser_dataset_display._non_empty_pairs
_build_same_name_groups = browser_dataset_same_name._build_same_name_groups
_attach_same_name_metadata = browser_dataset_same_name._attach_same_name_metadata
_household_same_name_groups = browser_dataset_same_name._household_same_name_groups


def _build_household_browser_detail_from_summary_dataset(dataset: dict, household_id: str) -> dict | None:
    household_row = dataset.get("household_rows", {}).get(household_id)
    if household_row is None:
        return None

    household_name = household_row.get("氏名", "")
    current_members = []
    memorial_members_unsorted = []
    for item in _sorted_household_person_rows(dataset.get("persons_by_household", {}), household_id):
        if _is_placeholder_person_row(item):
            continue
        person = _person_summary(item)
        member_type, member_type_label = _member_type_labels(item)
        person["household_name"] = household_name
        person["member_type"] = member_type
        person["member_type_label"] = member_type_label
        person["same_name_key"] = runtime_shared._same_name_key(person.get("name"), person.get("kana"))
        if member_type == "memorial":
            memorial_members_unsorted.append(person)
        else:
            current_members.append(person)

    same_name_groups = dataset.get("same_name_groups", {})
    memorial_members = _sort_memorial_members(memorial_members_unsorted)
    current_members = _attach_same_name_metadata(current_members, same_name_groups)
    memorial_members = _attach_same_name_metadata(memorial_members, same_name_groups)
    summary = dataset.get("households_by_id", {}).get(household_id)
    if summary is None:
        summary = next(
            (row for row in dataset.get("households", []) if row.get("household_id") == household_id),
            {
                "household_id": household_id,
                "name": household_name,
            },
        )

    profile_general_notice_opt_out = household_profile_runtime._parse_household_profile_notice_opt_out(
        household_row.get("__household_profile_general_notice_opt_out")
    )
    profile_memorial_notice_opt_out = household_profile_runtime._parse_household_profile_notice_opt_out(
        household_row.get("__household_profile_memorial_notice_opt_out")
    )
    household_general_notice_opt_out = bool(profile_general_notice_opt_out)
    household_general_notice_label = household_profile_runtime._household_general_notice_display_value(
        profile_value=profile_general_notice_opt_out
    )
    household_memorial_notice_opt_out = household_profile_runtime._effective_household_memorial_notice_opt_out(
        profile_value=profile_memorial_notice_opt_out,
        raw_value=None,
    )
    household_memorial_notice_label = household_profile_runtime._household_memorial_notice_display_value(
        profile_value=profile_memorial_notice_opt_out,
        raw_value=None,
    )

    detail = {
        "summary": summary,
        "head_person_id": household_row.get("__head_person_legacy_person_id", ""),
        "head_person_is_virtual": bool(household_row.get("__virtual_head_browser", {}).get("is_virtual")),
        "household_delivery_label": runtime_shared._clean_value(
            household_row.get("__household_profile_delivery_label")
        ),
        "household_yuen_label": runtime_shared._clean_value(household_row.get("__household_yuen_label")),
        "household_general_notice_opt_out": household_general_notice_opt_out,
        "household_general_notice_label": household_general_notice_label,
        "household_memorial_notice_opt_out": household_memorial_notice_opt_out,
        "household_memorial_notice_label": household_memorial_notice_label,
        "household_fields": _display_pairs(
            household_row,
            [
                "台帳ID",
                "氏名",
                "ﾌﾘｶﾞﾅ",
                "〒",
                "住所1",
                "住所2",
                "住所3",
                "電話",
                "ＦＡＸ",
                "携帯",
                "Email",
                "屋号",
                "世話人",
                "世話人ID",
                "台帳区分",
                "地区ID",
                "案内要否",
                "年回要否",
                "月忌要否",
                "備考",
                "新規登録日",
            ],
        ),
        "raw_household_fields": _non_empty_pairs(household_row.get("__raw_record", household_row)),
        "head_person_fields": _display_pairs(
            household_row,
            [
                "氏名",
                "ﾌﾘｶﾞﾅ",
                "かな補完",
                "性別",
                "生年月日",
                "続柄",
                "電話",
                "携帯",
                "Email",
                "備考",
            ],
        ),
        "current_members": current_members,
        "memorial_members": memorial_members,
        "events": list(dataset.get("events_by_household", {}).get(household_id, [])),
    }
    detail["same_name_groups"] = _household_same_name_groups(
        current_members + memorial_members,
        same_name_groups,
        household_id,
    )
    detail["same_name_group_count"] = len(detail["same_name_groups"])
    return detail


def _build_household_browser_dataset_from_rows(
    *,
    household_rows: list[dict],
    person_rows: list[dict],
    schedule_rows: list[dict],
    bon_rows: list[dict],
    memorial_rules: list[dict],
    schedule_type_labels: dict[str, str],
) -> dict:
    persons_by_household: dict[str, list[dict]] = {}
    for row in person_rows:
        persons_by_household.setdefault(row.get("台帳ID", ""), []).append(row)

    events_by_household: dict[str, list[dict]] = {}
    for row in schedule_rows:
        household_key = row.get("台帳ID", "")
        if household_key:
            events_by_household.setdefault(household_key, []).append(
                _event_summary(row, row.get("__source_table") or "UTM010_予定明細", schedule_type_labels)
            )
    for row in bon_rows:
        household_key = row.get("台帳ID", "")
        if household_key:
            events_by_household.setdefault(household_key, []).append(
                _event_summary(row, "UTY020_初盆予定作成", schedule_type_labels)
            )

    household_summaries: list[dict] = []
    household_details: dict[str, dict] = {}
    same_name_source_members: list[dict] = []
    for row in household_rows:
        household_key = row.get("台帳ID", "")
        head_person_role_badges = row.get("__head_person_role_badges")
        if not isinstance(head_person_role_badges, list):
            head_person_role_badges = []
        profile_general_notice_opt_out = household_profile_runtime._parse_household_profile_notice_opt_out(
            row.get("__household_profile_general_notice_opt_out")
        )
        profile_memorial_notice_opt_out = household_profile_runtime._parse_household_profile_notice_opt_out(
            row.get("__household_profile_memorial_notice_opt_out")
        )
        household_general_notice_opt_out = bool(profile_general_notice_opt_out)
        household_general_notice_label = household_profile_runtime._household_general_notice_display_value(
            profile_value=profile_general_notice_opt_out
        )
        household_memorial_notice_opt_out = (
            household_profile_runtime._effective_household_memorial_notice_opt_out(
                profile_value=profile_memorial_notice_opt_out,
                raw_value=None,
            )
        )
        household_memorial_notice_label = household_profile_runtime._household_memorial_notice_display_value(
            profile_value=profile_memorial_notice_opt_out,
            raw_value=None,
        )
        related_persons = _sorted_household_person_rows(persons_by_household, household_key)
        current_members = []
        memorial_members_unsorted = []
        for item in related_persons:
            if _is_placeholder_person_row(item):
                continue
            person = _person_summary(item)
            person["household_name"] = row.get("氏名", "")
            member_type, member_type_label = _member_type_labels(item)
            person["member_type"] = member_type
            person["member_type_label"] = member_type_label
            person["same_name_key"] = runtime_shared._same_name_key(person.get("name"), person.get("kana"))
            same_name_source_members.append(person)
            if person["member_type"] == "memorial":
                memorial_members_unsorted.append(person)
            else:
                current_members.append(person)
        memorial_members = _sort_memorial_members(memorial_members_unsorted)
        related_events = sorted(
            events_by_household.get(household_key, []),
            key=lambda item: (
                _sort_date(item.get("scheduled_date")),
                runtime_shared._int_sort(item.get("event_id")),
                runtime_shared._sort_text(item.get("subject_name")),
            ),
        )
        household_summaries.append(
            {
                "household_id": household_key,
                "name": row.get("氏名", ""),
                "kana": row.get("ﾌﾘｶﾞﾅ", ""),
                "address": runtime_shared._join_values(row.get("住所1"), row.get("住所2"), row.get("住所3")),
                "phone": row.get("電話") or row.get("携帯") or "",
                "current_count": len(current_members),
                "memorial_count": len(memorial_members),
                "event_count": len(related_events),
                "role_badges": head_person_role_badges,
                "is_yuen_household": _is_yuen_household_row(row),
                "browse_group_key": runtime_shared._household_group_key(row.get("ﾌﾘｶﾞﾅ", ""), row.get("氏名", "")),
            }
        )
        household_summaries[-1]["browse_group_label"] = HOUSEHOLD_KANA_GROUP_LABELS[
            household_summaries[-1]["browse_group_key"]
        ]
        household_details[household_key] = {
            "summary": household_summaries[-1],
            "head_person_id": row.get("__head_person_legacy_person_id", ""),
            "household_delivery_label": runtime_shared._clean_value(
                row.get("__household_profile_delivery_label")
            ),
            "household_yuen_label": runtime_shared._clean_value(row.get("__household_yuen_label")),
            "household_general_notice_opt_out": household_general_notice_opt_out,
            "household_general_notice_label": household_general_notice_label,
            "household_memorial_notice_opt_out": household_memorial_notice_opt_out,
            "household_memorial_notice_label": household_memorial_notice_label,
            "household_fields": _display_pairs(
                row,
                [
                    "台帳ID",
                    "氏名",
                    "ﾌﾘｶﾞﾅ",
                    "〒",
                    "住所1",
                    "住所2",
                    "住所3",
                    "電話",
                    "ＦＡＸ",
                    "携帯",
                    "Email",
                    "屋号",
                    "世話人",
                    "世話人ID",
                    "台帳区分",
                    "地区ID",
                    "案内要否",
                    "年回要否",
                    "月忌要否",
                    "備考",
                    "新規登録日",
                ],
            ),
            "raw_household_fields": _non_empty_pairs(row.get("__raw_record", row)),
            "head_person_fields": _display_pairs(
                row,
                [
                    "氏名",
                    "ﾌﾘｶﾞﾅ",
                    "かな補完",
                    "性別",
                    "生年月日",
                    "続柄",
                    "電話",
                    "携帯",
                    "Email",
                    "備考",
                ],
            ),
            "current_members": current_members,
            "memorial_members": memorial_members,
            "events": related_events,
        }

    same_name_groups = _build_same_name_groups(same_name_source_members)
    for household_key, detail in household_details.items():
        detail["current_members"] = _attach_same_name_metadata(
            detail["current_members"],
            same_name_groups,
        )
        detail["memorial_members"] = _attach_same_name_metadata(
            detail["memorial_members"],
            same_name_groups,
        )
        detail["same_name_groups"] = _household_same_name_groups(
            detail["current_members"] + detail["memorial_members"],
            same_name_groups,
            household_key,
        )
        detail["same_name_group_count"] = len(detail["same_name_groups"])

    household_summaries.sort(key=_household_summary_sort_key)
    return {
        "households": household_summaries,
        "household_details": household_details,
        "memorial_rules": memorial_rules,
        "same_name_groups": same_name_groups,
        "same_name_group_total": len(same_name_groups),
    }
