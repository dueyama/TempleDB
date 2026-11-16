from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.models import Household, Person
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.memorial_person_household_move import (
    memorial_person_move_blocker_message,
    memorial_person_move_is_available,
    move_memorial_person_to_household,
    resolve_memorial_person_move_target,
    search_memorial_person_move_households,
)
from apps.office.services.record_history_feed import _edit_url
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _deleted_record_return_label,
    _normalized_request_url,
    _request_actor_label,
    _resolve_next_url,
    _safe_memorial_person_move_return_url,
)


def move_memorial_person_household(request: HttpRequest, household_id: str, person_id: str) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
        deleted_at__isnull=True,
    )
    active_source_id = person.batch.source.source_id
    back_url = _resolve_next_url(
        request,
        _edit_url(
            "office:edit_person",
            household_id,
            person_id,
            source_id=active_source_id,
            next_url=_default_household_browser_url(household_id),
        ),
    )
    move_result_mode = (request.GET.get("move_result") or "").strip() in {"1", "true", "on"}
    undo_household_id = (request.POST.get("undo_household_id") or request.GET.get("undo_household_id") or "").strip()
    if not memorial_person_move_is_available(person):
        messages.error(request, "過去帳 person だけ移動できます。")
        return redirect(back_url)

    query = (request.GET.get("q") or request.POST.get("q") or "").strip()
    search_results = search_memorial_person_move_households(
        query=query,
        exclude_household_id=household_id,
    )
    move_error = ""
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "undo_move":
            try:
                source_household = resolve_memorial_person_move_target(
                    target_household_id=undo_household_id,
                    source_household_id=household_id,
                )
                change_note = (
                    (request.POST.get("change_note") or "").strip()
                    or f"故人の家移動を取り消し: 台帳ID {household_id} -> {source_household.household_uid}"
                )
                outcome = move_memorial_person_to_household(
                    person=person,
                    target_household=source_household,
                    editor_label=_request_actor_label(request),
                    change_note=change_note,
                )
            except ValueError as exc:
                move_error = str(exc)
            else:
                undo_return_url = _safe_memorial_person_move_return_url(
                    back_url,
                    source_household_id=household_id,
                    target_household_id=outcome.target_household.household_uid,
                )
                messages.success(
                    request,
                    f"故人 {outcome.person.name or outcome.person.person_uid} の家移動を取り消しました。"
                    + (
                        f" 履歴 {outcome.log_entry.created_at:%Y-%m-%d %H:%M:%S} を記録しました。"
                        if outcome.log_entry is not None
                        else ""
                    ),
                )
                return redirect(
                    _edit_url(
                        "office:edit_person",
                        outcome.target_household.household_uid,
                        outcome.person.person_uid,
                        source_id=active_source_id,
                        next_url=undo_return_url,
                    )
                )
        target_household_id = (request.POST.get("target_household_id") or "").strip()
        try:
            target_household = resolve_memorial_person_move_target(
                target_household_id=target_household_id,
                source_household_id=household_id,
            )
            change_note = (
                (request.POST.get("change_note") or "").strip()
                or f"故人の家移動: 台帳ID {household_id} -> {target_household.household_uid}"
            )
            outcome = move_memorial_person_to_household(
                person=person,
                target_household=target_household,
                editor_label=_request_actor_label(request),
                change_note=change_note,
            )
        except ValueError as exc:
            move_error = str(exc)
        else:
            move_return_url = _safe_memorial_person_move_return_url(
                back_url,
                source_household_id=household_id,
                target_household_id=outcome.target_household.household_uid,
            )
            return redirect(
                _edit_url(
                    "office:move_memorial_person_household",
                    outcome.target_household.household_uid,
                    outcome.person.person_uid,
                    source_id=active_source_id,
                    next_url=move_return_url,
                    extra_query={"move_result": "1", "undo_household_id": household_id},
                )
            )

    if move_result_mode:
        source_household = (
            Household.objects.filter(household_uid=undo_household_id)
            .select_related("head_person")
            .first()
        )
        return render(
            request,
            "office/move_memorial_person_confirm.html",
            {
                "title": "故人を別の家へ移す",
                "person": person,
                "target_household_id": household_id,
                "target_household_label": _household_display_head_name(person.household),
                "source_household_id": undo_household_id,
                "source_household_label": _household_display_head_name(source_household) if source_household is not None else "",
                "change_note": (
                    f"故人の家移動: 台帳ID {undo_household_id} -> {household_id}"
                    if undo_household_id
                    else ""
                ),
                "undo_change_note": (
                    f"故人の家移動を取り消し: 台帳ID {household_id} -> {undo_household_id}"
                    if undo_household_id
                    else ""
                ),
                "next_url": back_url,
                "return_url": back_url,
                "return_label": _deleted_record_return_label(back_url, household_id=household_id),
            },
        )

    return render(
        request,
        "office/move_memorial_person_household.html",
        {
            "title": "故人を別の家へ移す",
            "person": person,
            "household": person.household,
            "next_url": back_url,
            "current_url": _normalized_request_url(request),
            "query": query,
            "search_results": search_results,
            "move_error": move_error,
            "move_blocker_message": memorial_person_move_blocker_message(person),
        },
    )


__all__ = ["move_memorial_person_household"]
