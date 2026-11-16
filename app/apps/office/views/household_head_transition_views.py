from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from apps.imports.forms import HouseholdHeadTransitionForm
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    RecordEditLog,
)
from apps.office.services.household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _matching_household_head_people,
    _person_for_edit,
)
from apps.office.services.household_head_editing import (
    _apply_household_head_transition_successor,
    _household_head_successor_choices,
    _prepare_household_head_person_move,
    move_household_head_person,
)
from apps.office.services.household_person_lifecycle import (
    _household_head_memorial_transition_initial,
    _register_person_memorial_transition,
)
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_person_record
from apps.office.views.common import _resolve_household_edit_context
from apps.office.web_support import (
    _normalized_request_url,
    _request_actor_label,
    _safe_household_action_return_url,
)

from .household_transition_shared import _household_transition_result_context


def _move_household_head(
    request: HttpRequest,
    household_id: str,
    target_category: str,
) -> HttpResponse:
    transition_result_mode = (request.GET.get("transition_result") or "").strip() in {
        "1",
        "true",
        "on",
    }
    if request.method != "POST" and not (
        request.method == "GET" and transition_result_mode
    ):
        return HttpResponseNotAllowed(["POST"])

    _active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    safe_return_url = _safe_household_action_return_url(
        next_url,
        household_id=household_id,
        stale_view_names=(
            "office:move_household_head_to_current",
            "office:move_household_head_to_memorial",
            "office:household_head_transition",
        ),
    )
    target_label = "過去帳" if target_category == FAMILY_CATEGORY_MEMORIAL else "現在帳"
    created_person = (request.GET.get("created_person") or "").strip() in {"1", "true", "on"}
    if request.method == "GET" and transition_result_mode:
        result_meta_lines = ["家族レコードを新規作成しています。"] if created_person else []
        return render(
            request,
            "office/record_action_result.html",
            _household_transition_result_context(
                household=household,
                household_id=household_id,
                target_label=target_label,
                safe_return_url=safe_return_url,
                result_meta_lines=result_meta_lines,
            ),
        )
    try:
        outcome = move_household_head_person(
            household=household,
            target_category=target_category,
            editor_label=_request_actor_label(request),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(next_url)
    result_view_name = (
        "office:move_household_head_to_memorial"
        if target_category == FAMILY_CATEGORY_MEMORIAL
        else "office:move_household_head_to_current"
    )
    return redirect(
        _edit_url(
            result_view_name,
            household_id,
            source_id="",
            next_url=safe_return_url,
            extra_query={
                "transition_result": "1",
                "created_person": "1" if outcome.created_person else "",
            },
        )
    )


def move_household_head_to_current(request: HttpRequest, household_id: str) -> HttpResponse:
    return _move_household_head(request, household_id, FAMILY_CATEGORY_CURRENT)


def move_household_head_to_memorial(request: HttpRequest, household_id: str) -> HttpResponse:
    return _move_household_head(request, household_id, FAMILY_CATEGORY_MEMORIAL)


def household_head_transition(request: HttpRequest, household_id: str) -> HttpResponse:
    active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    target = request.GET.get("target") or request.POST.get("target")
    normalized_target = (
        FAMILY_CATEGORY_MEMORIAL if target == FAMILY_CATEGORY_MEMORIAL else FAMILY_CATEGORY_CURRENT
    )
    target_label = "過去帳" if normalized_target == FAMILY_CATEGORY_MEMORIAL else "現在帳"
    safe_return_url = _safe_household_action_return_url(
        next_url,
        household_id=household_id,
        stale_view_names=(
            "office:household_head_transition",
            "office:move_household_head_to_current",
            "office:move_household_head_to_memorial",
        ),
    )
    transition_result_mode = (request.GET.get("transition_result") or "").strip() in {
        "1",
        "true",
        "on",
    }
    created_person = (request.GET.get("created_person") or "").strip() in {"1", "true", "on"}
    successor_updated = (request.GET.get("successor_updated") or "").strip() in {
        "1",
        "true",
        "on",
    }
    funeral_created = (request.GET.get("funeral_created") or "").strip() in {
        "1",
        "true",
        "on",
    }
    if request.method == "GET" and transition_result_mode:
        result_meta_lines: list[str] = []
        if created_person:
            result_meta_lines.append("家族レコードを新規作成しています。")
        if successor_updated:
            result_meta_lines.append("次の戸主情報を更新しました。")
        if funeral_created:
            result_meta_lines.append("葬儀予定を作成しました。")
        return render(
            request,
            "office/record_action_result.html",
            _household_transition_result_context(
                household=household,
                household_id=household_id,
                target_label=target_label,
                safe_return_url=safe_return_url,
                result_meta_lines=result_meta_lines,
            ),
        )
    matched_head_people = _matching_household_head_people(household)
    excluded_person_ids = {person.pk for person in matched_head_people}
    successor_choices = _household_head_successor_choices(
        household,
        exclude_person_ids=excluded_person_ids,
    )
    memorial_initial = _household_head_memorial_transition_initial(household)
    if request.method == "POST":
        form = HouseholdHeadTransitionForm(
            request.POST,
            target_category=normalized_target,
            successor_choices=successor_choices,
            include_successor_fields=normalized_target == FAMILY_CATEGORY_MEMORIAL,
        )
        if form.is_valid():
            with transaction.atomic():
                try:
                    person, before_data, created = _prepare_household_head_person_move(household)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect(next_url)
                funeral_log = None
                if normalized_target == FAMILY_CATEGORY_MEMORIAL:
                    person, _, funeral_log = _register_person_memorial_transition(
                        person=person,
                        household=household,
                        form_data=form.cleaned_data,
                        editor_label=_request_actor_label(request),
                        change_note=(
                            "戸主ブラウザで戸主を往生登録"
                            + ("（新規 person 作成）" if created else "")
                        ),
                    )
                else:
                    _apply_household_contact_defaults_to_person(person, household)
                    person.family_category = normalized_target
                    person.is_deceased = normalized_target == FAMILY_CATEGORY_MEMORIAL
                    person.relationship_label = "本人"
                    person.save()
                if normalized_target == FAMILY_CATEGORY_CURRENT:
                    person.clear_memorial_fields()
                    person.save()
                    person.sync_legacy_deceased_profile()
                if normalized_target == FAMILY_CATEGORY_CURRENT:
                    person = _person_for_edit(person.pk)
                    _create_record_edit_log(
                        record_type=RecordEditLog.RecordType.PERSON,
                        record=person,
                        before_data=before_data,
                        after_data=_serialize_person_record(person),
                        editor_label=_request_actor_label(request),
                        change_note=(
                            f"戸主ブラウザで戸主を{target_label}に移動"
                            + ("（新規 person 作成）" if created else "")
                        ),
                    )
                household_log = None
                if normalized_target == FAMILY_CATEGORY_MEMORIAL:
                    household_log = _apply_household_head_transition_successor(
                        household=household,
                        successor_mode=(form.cleaned_data.get("successor_mode") or "").strip(),
                        successor_person_id=(form.cleaned_data.get("successor_person_id") or "").strip(),
                        manual_head_name=(form.cleaned_data.get("manual_head_name") or "").strip(),
                        manual_head_name_kana=(form.cleaned_data.get("manual_head_name_kana") or "").strip(),
                        editor_label=_request_actor_label(request),
                    )
            return redirect(
                _edit_url(
                    "office:household_head_transition",
                    household_id,
                    source_id=active_source_id,
                    next_url=safe_return_url,
                    extra_query={
                        "target": normalized_target,
                        "transition_result": "1",
                        "created_person": "1" if created else "",
                        "successor_updated": "1" if household_log is not None else "",
                        "funeral_created": "1" if funeral_log is not None else "",
                    },
                )
            )
    else:
        form = HouseholdHeadTransitionForm(
            initial=memorial_initial,
            target_category=normalized_target,
            successor_choices=successor_choices,
            include_successor_fields=normalized_target == FAMILY_CATEGORY_MEMORIAL,
        )

    return render(
        request,
        "office/household_head_transition.html",
        {
            "title": f"戸主を{target_label}に移動",
            "household": household,
            "target_category": normalized_target,
            "target_label": target_label,
            "next_url": next_url,
            "form": form,
            "current_url": _normalized_request_url(request),
            "successor_choices_available": bool(successor_choices),
        },
    )


__all__ = [
    "_move_household_head",
    "household_head_transition",
    "move_household_head_to_current",
    "move_household_head_to_memorial",
]
