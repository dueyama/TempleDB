from __future__ import annotations

from . import household_head_runtime, runtime_shared, synthetic_household_runtime


def _household_head_ledger_status(
    household_name: str,
    head_person_fields: list[dict],
    current_members: list[dict],
    memorial_members: list[dict],
) -> dict:
    head_name = _normalize_head_status_name(household_name)
    field_name = next(
        (
            _normalize_head_status_name(item.get("value", ""))
            for item in head_person_fields
            if item.get("label") == "氏名"
        ),
        "",
    )
    target_name = field_name or head_name
    if not target_name:
        return {"label": "未判定", "person_id": "", "kind": "unknown"}
    current_matches = [
        member for member in current_members if _normalize_head_status_name(member.get("name")) == target_name
    ]
    memorial_matches = [
        member for member in memorial_members if _normalize_head_status_name(member.get("name")) == target_name
    ]
    matched_members = [*current_matches, *memorial_matches]
    if len(matched_members) > 1:
        return {"label": "同名候補が複数あります", "person_id": "", "kind": "ambiguous"}
    if current_matches:
        return {
            "label": "現在帳",
            "person_id": current_matches[0].get("person_id", ""),
            "kind": "current",
        }
    if memorial_matches:
        return {
            "label": "過去帳",
            "person_id": memorial_matches[0].get("person_id", ""),
            "kind": "memorial",
        }
    return {"label": "現在帳・過去帳に未作成", "person_id": "", "kind": "missing"}


def _exclude_head_person_from_member_list(members: list[dict], head_person_id: str | None) -> list[dict]:
    normalized_head_person_id = runtime_shared._clean_value(head_person_id)
    if not normalized_head_person_id:
        return list(members)
    return [
        member
        for member in members
        if runtime_shared._clean_value(member.get("person_id")) != normalized_head_person_id
    ]


def _normalize_head_status_name(value: str | None) -> str:
    if not value:
        return ""
    return "".join(str(value).strip().replace(" ", "").replace("\u3000", "").split())


def _household_browser_extinct_action(
    *,
    household_name: str,
    head_person_fields: list[dict],
    current_members: list[dict],
    head_ledger_status: dict,
) -> dict[str, object]:
    relationship_label = next(
        (
            runtime_shared._clean_value(field.get("value"))
            for field in head_person_fields
            if field.get("label") == "続柄"
        ),
        "",
    )
    already_extinct = bool(
        relationship_label == synthetic_household_runtime.EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL
        or runtime_shared._clean_value(household_name).endswith(
            synthetic_household_runtime.EXTINCT_HOUSEHOLD_NAME_SUFFIX
        )
    )
    is_virtual_head = bool(
        relationship_label == household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL
        or runtime_shared._clean_value(household_name).startswith(
            household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX
        )
    )
    has_living_current_people = bool(current_members)
    show_action = bool(
        not already_extinct
        and not has_living_current_people
        and (
            runtime_shared._clean_value(head_ledger_status.get("kind")) == "memorial"
            or is_virtual_head
        )
    )
    if already_extinct:
        message = "この家はすでに絶家保持です。"
    elif show_action:
        if is_virtual_head:
            message = "現在の戸主は仮戸主で、現在帳の生存者も残っていません。この家を絶家にできます。"
        else:
            message = "戸主が過去帳で、現在帳の生存者も残っていません。この家を絶家にできます。"
    elif runtime_shared._clean_value(head_ledger_status.get("kind")) == "memorial":
        message = "戸主が過去帳です。現在帳の生存者が残っているため、絶家ではなく次の戸主を設定してください。"
    else:
        message = ""
    return {
        "show_action": show_action,
        "already_extinct": already_extinct,
        "message": message,
    }


__all__ = [
    "_exclude_head_person_from_member_list",
    "_household_browser_extinct_action",
    "_household_head_ledger_status",
    "_normalize_head_status_name",
]
