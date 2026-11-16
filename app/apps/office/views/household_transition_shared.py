from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest

from apps.imports import synthetic_household_runtime
from apps.imports.models import FAMILY_CATEGORY_MEMORIAL, Household, RecordEditLog
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.household_head_editing import _is_extinct_household_head_person
from apps.office.services.record_history_mutations import record_action_message_text
from apps.office.web_support import _record_action_return_label


def _flash_record_action_message(
    request: HttpRequest,
    log_entry: RecordEditLog | None,
    message_text: str,
) -> None:
    messages.success(request, record_action_message_text(log_entry, message_text))


def _household_extinct_action_state(
    *,
    household: Household,
    resolved_head_person,
    head_person_is_virtual: bool,
) -> dict[str, object]:
    living_current_people = synthetic_household_runtime.active_real_current_people(household)
    already_extinct = _is_extinct_household_head_person(resolved_head_person)
    head_is_memorial = bool(
        resolved_head_person is not None
        and not head_person_is_virtual
        and (
            resolved_head_person.family_category == FAMILY_CATEGORY_MEMORIAL
            or resolved_head_person.is_deceased
        )
    )
    show_action = bool(
        not already_extinct
        and not living_current_people
        and (head_is_memorial or head_person_is_virtual)
    )
    if already_extinct:
        message = "この家はすでに絶家保持です。"
    elif show_action:
        if head_person_is_virtual:
            message = "現在の戸主は仮戸主で、現在帳の生存者も残っていません。この家を絶家にできます。"
        else:
            message = "戸主が過去帳で、現在帳の生存者も残っていません。この家を絶家にできます。"
    elif head_is_memorial:
        message = "戸主が過去帳です。現在帳の生存者が残っているため、絶家ではなく次の戸主を設定してください。"
    else:
        message = ""
    return {
        "show_action": show_action,
        "already_extinct": already_extinct,
        "message": message,
        "living_current_people": living_current_people,
    }


def _household_transition_result_context(
    *,
    household: Household,
    household_id: str,
    target_label: str,
    safe_return_url: str,
    result_meta_lines: list[str],
) -> dict[str, object]:
    return {
        "eyebrow": "Transition",
        "title": f"戸主を{target_label}に移動",
        "subtitle": f"{_household_display_head_name(household)} / 台帳ID {household_id}",
        "result_heading": f"戸主を{target_label}に移動しました。",
        "result_message": f"戸主の家族区分を {target_label} に更新しました。",
        "result_meta_lines": result_meta_lines,
        "return_url": safe_return_url,
        "return_label": _record_action_return_label(
            safe_return_url,
            household_id=household_id,
        ),
    }


__all__ = [
    "_flash_record_action_message",
    "_household_extinct_action_state",
    "_household_transition_result_context",
]
