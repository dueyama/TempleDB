from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.imports import synthetic_household_runtime
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.household_head_editing import (
    _is_virtual_household_head_person,
    mark_household_extinct,
)
from apps.office.views.common import _resolve_household_edit_context
from apps.office.web_support import (
    _record_action_return_label,
    _request_actor_label,
    _safe_household_action_return_url,
)

from .household_transition_shared import (
    _flash_record_action_message,
    _household_extinct_action_state,
)


def mark_household_extinct_view(request: HttpRequest, household_id: str) -> HttpResponse:
    _active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    safe_return_url = _safe_household_action_return_url(
        next_url,
        household_id=household_id,
        stale_view_names=("office:mark_household_extinct",),
    )
    resolved_head_person = household.resolve_head_person()
    head_person_is_virtual = _is_virtual_household_head_person(resolved_head_person)
    extinct_action_state = _household_extinct_action_state(
        household=household,
        resolved_head_person=resolved_head_person,
        head_person_is_virtual=head_person_is_virtual,
    )
    extinct_identity = synthetic_household_runtime.resolve_extinct_household_identity(household)
    if request.method == "POST":
        if not bool(extinct_action_state["show_action"]):
            messages.error(request, str(extinct_action_state["message"] or "この家は絶家にできません。"))
            return redirect(safe_return_url)
        with transaction.atomic():
            outcome = mark_household_extinct(
                household=household,
                editor_label=_request_actor_label(request),
            )
        _flash_record_action_message(
            request,
            outcome.log_entry,
            f"戸主レコード {household.household_uid} を絶家にしました。",
        )
        return redirect(safe_return_url)

    return render(
        request,
        "office/household_extinct_confirm.html",
        {
            "title": "この家を絶家にする",
            "subtitle": f"{_household_display_head_name(household)} / 台帳ID {household.household_uid}",
            "household": household,
            "resolved_head_person": resolved_head_person,
            "extinct_action_state": extinct_action_state,
            "extinct_identity": extinct_identity,
            "head_person_is_virtual": head_person_is_virtual,
            "next_url": safe_return_url,
            "return_label": _record_action_return_label(
                safe_return_url,
                household_id=household_id,
            ),
        },
    )
