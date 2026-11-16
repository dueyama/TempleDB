from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.imports.browser_virtual_heads import virtual_head_browser_metadata
from apps.imports.forms import VirtualHeadReplacementForm
from apps.office.services.household_head_editing import (
    _household_head_successor_choices,
    _is_virtual_household_head_person,
    _replace_virtual_household_head,
)
from apps.office.services.record_history_feed import _edit_url
from apps.office.views.common import _resolve_household_edit_context
from apps.office.web_support import _request_actor_label

from .household_transition_shared import _flash_record_action_message


def replace_virtual_head(request: HttpRequest, household_id: str) -> HttpResponse:
    active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    resolved_head_person = household.resolve_head_person()
    if not _is_virtual_household_head_person(resolved_head_person):
        messages.error(request, "現在の戸主は仮戸主ではありません。")
        return redirect(
            _edit_url(
                "office:edit_household",
                household.household_uid,
                source_id=active_source_id,
                next_url=next_url,
            )
        )

    successor_choices = _household_head_successor_choices(
        household,
        exclude_person_ids={resolved_head_person.pk},
    )
    if request.method == "POST":
        form = VirtualHeadReplacementForm(request.POST, successor_choices=successor_choices)
        if form.is_valid():
            with transaction.atomic():
                log_entry = _replace_virtual_household_head(
                    household=household,
                    successor_mode=(form.cleaned_data.get("successor_mode") or "").strip(),
                    successor_person_id=(form.cleaned_data.get("successor_person_id") or "").strip(),
                    manual_head_name=(form.cleaned_data.get("manual_head_name") or "").strip(),
                    manual_head_name_kana=(form.cleaned_data.get("manual_head_name_kana") or "").strip(),
                    editor_label=_request_actor_label(request),
                )
            _flash_record_action_message(
                request,
                log_entry,
                f"戸主レコード {household.household_uid} の実戸主を設定しました。",
            )
            return redirect(next_url)
    else:
        form = VirtualHeadReplacementForm(successor_choices=successor_choices)

    virtual_label = virtual_head_browser_metadata([household]).get(household.household_uid, {}).get("label") or resolved_head_person.name
    return render(
        request,
        "office/virtual_head_replace.html",
        {
            "title": "実戸主を設定",
            "subtitle": f"{virtual_label} / 台帳ID {household.household_uid}",
            "household": household,
            "virtual_head": resolved_head_person,
            "virtual_head_display_name": virtual_label,
            "form": form,
            "next_url": next_url,
        },
    )
