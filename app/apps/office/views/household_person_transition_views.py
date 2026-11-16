from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.forms import (
    HouseholdHeadTransitionForm,
    NewCurrentPersonForm,
    NewMemorialRegistrationForm,
)
from apps.imports.models import FAMILY_CATEGORY_MEMORIAL, Household, Person, RecordEditLog
from apps.office.services.household_person_lifecycle import (
    _create_new_household_current_person,
    _create_new_household_memorial_person,
    _person_memorial_transition_initial,
    _register_person_memorial_transition,
)
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_person_record
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _normalized_request_url,
    _record_action_return_label,
    _request_actor_label,
    _resolve_next_url,
    _safe_household_action_return_url,
)

from .household_transition_shared import _flash_record_action_message


def person_memorial_transition(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
        deleted_at__isnull=True,
    )
    active_source_id = person.batch.source.source_id
    household = person.household
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    safe_return_url = _safe_household_action_return_url(
        next_url,
        household_id=household_id,
        stale_view_names=("office:person_memorial_transition",),
    )
    transition_result_mode = (request.GET.get("transition_result") or "").strip() in {
        "1",
        "true",
        "on",
    }
    funeral_created = (request.GET.get("funeral_created") or "").strip() in {"1", "true", "on"}
    if request.method == "GET" and transition_result_mode:
        result_meta_lines = ["葬儀予定を作成しました。"] if funeral_created else []
        return render(
            request,
            "office/record_action_result.html",
            {
                "eyebrow": "Transition",
                "title": "往生登録",
                "subtitle": f"{person.name or person.person_uid} / 台帳ID {household_id}",
                "result_heading": "往生登録しました。",
                "result_message": (
                    f"{person.name or person.person_uid} を過去帳へ移しました。"
                ),
                "result_meta_lines": result_meta_lines,
                "return_url": safe_return_url,
                "return_label": _record_action_return_label(
                    safe_return_url,
                    household_id=household_id,
                ),
            },
        )
    initial = _person_memorial_transition_initial(person)
    if request.method == "POST":
        form = HouseholdHeadTransitionForm(
            request.POST,
            target_category=FAMILY_CATEGORY_MEMORIAL,
            include_successor_fields=False,
        )
        if form.is_valid():
            with transaction.atomic():
                _, _, funeral_log = _register_person_memorial_transition(
                    person=person,
                    household=household,
                    form_data=form.cleaned_data,
                    editor_label=_request_actor_label(request),
                    change_note="戸主ブラウザで現在帳を往生登録",
                )
            return redirect(
                _edit_url(
                    "office:person_memorial_transition",
                    household_id,
                    person_id,
                    source_id=active_source_id,
                    next_url=safe_return_url,
                    extra_query={
                        "transition_result": "1",
                        "funeral_created": "1" if funeral_log is not None else "",
                    },
                )
            )
    else:
        form = HouseholdHeadTransitionForm(
            initial=initial,
            target_category=FAMILY_CATEGORY_MEMORIAL,
            include_successor_fields=False,
        )

    return render(
        request,
        "office/person_memorial_transition.html",
        {
            "title": "往生登録",
            "household": household,
            "person": person,
            "next_url": next_url,
            "form": form,
            "current_url": _normalized_request_url(request),
        },
    )


def create_household_memorial_person(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    household = get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=household_id,
    )
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    initial = {
        "registration_mode": HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL,
        "gender": "未決定",
        "age_unit": "歳",
        "funeral_scheduled_time": "10:00",
    }
    if request.method == "POST":
        form = NewMemorialRegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                person = _create_new_household_memorial_person(
                    household=household,
                    form_data=form.cleaned_data,
                )
                person, log_entry, funeral_log = _register_person_memorial_transition(
                    person=person,
                    household=household,
                    form_data=form.cleaned_data,
                    editor_label=_request_actor_label(request),
                    change_note="戸主ブラウザで新しい故人を往生登録",
                )
            _flash_record_action_message(
                request,
                log_entry,
                f"新しい故人 {person.name or person.person_uid} を登録しました。",
            )
            if funeral_log is not None:
                messages.success(request, "葬儀予定を作成しました。")
            return redirect(next_url)
    else:
        form = NewMemorialRegistrationForm(initial=initial)

    return render(
        request,
        "office/new_memorial_person.html",
        {
            "title": "新しい故人を往生登録",
            "household": household,
            "next_url": next_url,
            "form": form,
            "current_url": _normalized_request_url(request),
        },
    )


def create_household_current_person(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    household = get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=household_id,
    )
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    initial = {
        "gender": "未決定",
    }
    if request.method == "POST":
        form = NewCurrentPersonForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                person = _create_new_household_current_person(
                    household=household,
                    form_data=form.cleaned_data,
                )
                log_entry = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.PERSON,
                    record=person,
                    before_data={},
                    after_data=_serialize_person_record(person),
                    editor_label=_request_actor_label(request),
                    change_note="戸主ブラウザで新しい現在帳を追加",
                )
            _flash_record_action_message(
                request,
                log_entry,
                f"新しい現在帳 {person.name or person.person_uid} を登録しました。",
            )
            return redirect(next_url)
    else:
        form = NewCurrentPersonForm(initial=initial)

    return render(
        request,
        "office/new_current_person.html",
        {
            "title": "新しい現在帳を追加",
            "household": household,
            "next_url": next_url,
            "form": form,
            "current_url": _normalized_request_url(request),
        },
    )
__all__ = [
    "create_household_current_person",
    "create_household_memorial_person",
    "person_memorial_transition",
]
