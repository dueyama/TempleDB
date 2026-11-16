from __future__ import annotations

from . import browser_dataset_same_name, runtime_shared
from .browser_dataset_rows import (
    _event_summary,
    _household_summary_sort_key,
    _is_placeholder_person_row,
    _is_yuen_household_row,
    _same_name_source_member_summary,
    _sort_date,
    _sorted_household_person_rows,
)

HOUSEHOLD_KANA_GROUP_LABELS = runtime_shared.HOUSEHOLD_KANA_GROUP_LABELS
_build_same_name_groups = browser_dataset_same_name._build_same_name_groups


def _build_household_browser_summary_dataset_from_rows(
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
    households_by_id: dict[str, dict] = {}
    household_rows_by_id: dict[str, dict] = {}
    memorial_search_index: dict[str, tuple[str, ...]] = {}
    same_name_source_members: list[dict] = []

    for row in household_rows:
        household_key = row.get("台帳ID", "")
        household_name = row.get("氏名", "")
        household_rows_by_id[household_key] = row
        head_person_role_badges = row.get("__head_person_role_badges")
        if not isinstance(head_person_role_badges, list):
            head_person_role_badges = []

        current_count = 0
        memorial_count = 0
        memorial_search_values: list[str] = []
        for item in _sorted_household_person_rows(persons_by_household, household_key):
            if _is_placeholder_person_row(item):
                continue
            member_summary = _same_name_source_member_summary(item, household_name)
            same_name_source_members.append(member_summary)
            memorial_search_values.extend(
                [
                    member_summary.get("person_id", ""),
                    member_summary.get("name", ""),
                    member_summary.get("kana", ""),
                    member_summary.get("relationship", ""),
                    member_summary.get("kaimyo", ""),
                    member_summary.get("death_date", ""),
                ]
            )
            if member_summary["member_type"] == "memorial":
                memorial_count += 1
            else:
                current_count += 1

        related_events = sorted(
            events_by_household.get(household_key, []),
            key=lambda item: (
                _sort_date(item.get("scheduled_date")),
                runtime_shared._int_sort(item.get("event_id")),
                runtime_shared._sort_text(item.get("subject_name")),
            ),
        )
        events_by_household[household_key] = related_events
        summary = {
            "household_id": household_key,
            "name": row.get("__virtual_head_browser", {}).get("label") or household_name,
            "kana": row.get("__virtual_head_browser", {}).get("kana") or row.get("ﾌﾘｶﾞﾅ", ""),
            "search_aliases": row.get("__virtual_head_browser", {}).get("search_terms", []),
            "address": runtime_shared._join_values(row.get("住所1"), row.get("住所2"), row.get("住所3")),
            "phone": row.get("電話") or row.get("携帯") or "",
            "current_count": current_count,
            "memorial_count": memorial_count,
            "event_count": len(related_events),
            "role_badges": head_person_role_badges,
            "is_yuen_household": _is_yuen_household_row(row),
            "browse_group_key": runtime_shared._household_group_key(
                row.get("__virtual_head_browser", {}).get("kana") or row.get("ﾌﾘｶﾞﾅ", ""), household_name,
            ),
        }
        summary["browse_group_label"] = HOUSEHOLD_KANA_GROUP_LABELS[summary["browse_group_key"]]
        household_summaries.append(summary)
        households_by_id[household_key] = summary
        memorial_search_index[household_key] = tuple(value for value in memorial_search_values if value)

    same_name_groups = _build_same_name_groups(same_name_source_members)
    household_summaries.sort(key=_household_summary_sort_key)
    return {
        "households": household_summaries,
        "household_rows": household_rows_by_id,
        "households_by_id": households_by_id,
        "persons_by_household": persons_by_household,
        "events_by_household": events_by_household,
        "memorial_search_index": memorial_search_index,
        "memorial_rules": memorial_rules,
        "same_name_groups": same_name_groups,
        "same_name_group_total": len(same_name_groups),
    }
