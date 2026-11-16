from __future__ import annotations

from .runtime_shared import _clean_value, _sort_text


def _runtime_module():
    from . import data_quality_runtime

    return data_quality_runtime


def _decorate_same_name_groups(dataset: dict) -> list[dict]:
    household_details = dataset.get("household_details", {})
    return sorted(
        (
            _decorate_same_name_group(group, household_details)
            for group in dataset.get("same_name_groups", {}).values()
        ),
        key=lambda item: (-item["count"], _sort_text(item["display_name"])),
    )


def _decorate_same_name_group(group: dict, household_details: dict[str, dict]) -> dict:
    members = [
        _decorate_same_name_member(
            member,
            household_details.get(_clean_value(member.get("household_id")), {}),
        )
        for member in group.get("members", [])
    ]
    return {
        **group,
        "members": members,
        "households": _decorate_same_name_group_households(members, household_details),
    }


def _decorate_same_name_member(member: dict, detail: dict) -> dict:
    if not isinstance(detail, dict):
        detail = {}
    summary = detail.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    current_members = detail.get("current_members")
    if not isinstance(current_members, list):
        current_members = []
    memorial_members = detail.get("memorial_members")
    if not isinstance(memorial_members, list):
        memorial_members = []

    head_person_id = _clean_value(detail.get("head_person_id"))
    head_name = _same_name_head_member_name(current_members, head_person_id)
    current_count = summary.get("current_count")
    if not isinstance(current_count, int):
        current_count = len(current_members)
    memorial_count = summary.get("memorial_count")
    if not isinstance(memorial_count, int):
        memorial_count = len(memorial_members)

    return {
        **member,
        "household_role_label": _same_name_household_role_label(
            member,
            head_person_id=head_person_id,
            head_name=head_name,
        ),
        "household_current_count": current_count,
        "household_memorial_count": memorial_count,
        "household_member_summary": f"現在帳 {current_count} 人 / 過去帳 {memorial_count} 人",
        "current_member_names_preview": _same_name_member_names_preview(
            current_members,
            head_person_id=head_person_id,
        ),
        "memorial_member_names_preview": _same_name_member_names_preview(
            memorial_members,
            head_person_id=head_person_id,
        ),
    }


def _decorate_same_name_group_households(
    members: list[dict],
    household_details: dict[str, dict],
) -> list[dict]:
    households = []
    seen_household_ids: set[str] = set()
    for member in members:
        household_id = _clean_value(member.get("household_id"))
        if not household_id or household_id in seen_household_ids:
            continue
        seen_household_ids.add(household_id)
        detail = household_details.get(household_id, {})
        households.append(
            _decorate_same_name_group_household(
                household_id=household_id,
                group_members=[
                    candidate for candidate in members if _clean_value(candidate.get("household_id")) == household_id
                ],
                detail=detail,
            )
        )
    return households


def _decorate_same_name_group_household(
    *,
    household_id: str,
    group_members: list[dict],
    detail: dict,
) -> dict:
    if not isinstance(detail, dict):
        detail = {}
    summary = detail.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    current_members = detail.get("current_members")
    if not isinstance(current_members, list):
        current_members = []
    memorial_members = detail.get("memorial_members")
    if not isinstance(memorial_members, list):
        memorial_members = []

    head_person_id = _clean_value(detail.get("head_person_id"))
    resolved_head_name = _same_name_head_member_name(current_members, head_person_id)
    summary_head_name = _clean_value(summary.get("name"))
    head_name = resolved_head_name or summary_head_name
    current_count = summary.get("current_count")
    if not isinstance(current_count, int):
        current_count = len(current_members)
    memorial_count = summary.get("memorial_count")
    if not isinstance(memorial_count, int):
        memorial_count = len(memorial_members)
    event_count = summary.get("event_count")
    if not isinstance(event_count, int):
        event_count = 0

    return {
        "household_id": household_id,
        "household_name": _clean_value(group_members[0].get("household_name")) or summary_head_name,
        "head_label": "現戸主" if resolved_head_name else "戸主表示",
        "head_name": head_name,
        "address": _clean_value(summary.get("address")),
        "phone": _clean_value(summary.get("phone")),
        "delivery_label": _clean_value(detail.get("household_delivery_label")),
        "yuen_label": _clean_value(detail.get("household_yuen_label")),
        "household_member_summary": f"現在帳 {current_count} 人 / 過去帳 {memorial_count} 人",
        "current_member_names_preview": _same_name_member_names_preview(
            current_members,
            head_person_id=head_person_id,
        ),
        "memorial_member_names_preview": _same_name_member_names_preview(
            memorial_members,
            head_person_id=head_person_id,
        ),
        "matching_members_preview": _same_name_group_household_matching_members_preview(
            group_members,
            head_person_id=head_person_id,
        ),
        "event_summary": f"予定 {event_count} 件",
    }


def _same_name_head_member_name(current_members: list[dict], head_person_id: str) -> str:
    if not head_person_id:
        return ""
    for member in current_members:
        if _clean_value(member.get("person_id")) == head_person_id:
            return _clean_value(member.get("name"))
    return ""


def _same_name_household_role_label(
    member: dict,
    *,
    head_person_id: str,
    head_name: str,
) -> str:
    person_id = _clean_value(member.get("person_id"))
    member_type_label = _clean_value(member.get("member_type_label"))
    if head_person_id and person_id == head_person_id:
        return "この人が現戸主"
    if head_name and member_type_label:
        return f"{member_type_label}。現戸主は {head_name}"
    if head_name:
        return f"現戸主は {head_name}"
    if member_type_label:
        return f"{member_type_label}。現戸主未解決"
    return "現戸主未解決"


def _same_name_member_names_preview(
    members: list[dict],
    *,
    head_person_id: str,
) -> str:
    runtime = _runtime_module()
    preview_items = [
        item
        for item in (
            _same_name_member_preview_item(member, head_person_id=head_person_id)
            for member in members
        )
        if item
    ]
    if not preview_items:
        return ""
    visible_items = preview_items[:runtime._SAME_NAME_PREVIEW_MEMBER_LIMIT]
    preview = " / ".join(visible_items)
    if len(preview_items) <= runtime._SAME_NAME_PREVIEW_MEMBER_LIMIT:
        return preview
    return f"{preview} ほか{len(preview_items) - runtime._SAME_NAME_PREVIEW_MEMBER_LIMIT}人"


def _same_name_group_household_matching_members_preview(
    members: list[dict],
    *,
    head_person_id: str,
) -> str:
    preview_items = [
        item
        for item in (
            _same_name_group_household_matching_member_item(member, head_person_id=head_person_id) for member in members
        )
        if item
    ]
    return " / ".join(preview_items)


def _same_name_group_household_matching_member_item(member: dict, *, head_person_id: str) -> str:
    name = _clean_value(member.get("name"))
    if not name:
        return ""
    badges = []
    member_type_label = _clean_value(member.get("member_type_label"))
    if member_type_label:
        badges.append(member_type_label)
    person_id = _clean_value(member.get("person_id"))
    if head_person_id and person_id == head_person_id:
        badges.append("現戸主")
    elif _clean_value(member.get("relationship")):
        badges.append(_clean_value(member.get("relationship")))
    if not badges:
        return name
    return f"{name}（{'・'.join(badges)}）"


def _same_name_member_preview_item(member: dict, *, head_person_id: str) -> str:
    name = _clean_value(member.get("name"))
    if not name:
        return ""
    person_id = _clean_value(member.get("person_id"))
    if head_person_id and person_id == head_person_id:
        return f"{name}（現戸主）"
    relationship = _clean_value(member.get("relationship"))
    if relationship:
        return f"{name}（{relationship}）"
    return name
