from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    Person,
    RecordEditLog,
)
from apps.office import services
from apps.office.forms_person_calendar import PersonCalendarEditForm
from apps.office.services import google_calendar_sync
from apps.office.services.household_editing_core import (
    _household_display_head_name,
    _person_for_edit,
)
from apps.office.services.memorial_person_household_move import (
    memorial_person_move_is_available,
)
from apps.office.services.person_schedule_names import update_person_schedule_names
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    perform_record_delete_action,
)
from apps.office.services.record_history_snapshot import (
    _deleted_meta,
    _serialize_person_record,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options,
    _recent_record_history,
)
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _deleted_record_return_label,
    _normalize_time_machine_mode,
    _normalized_request_url,
    _request_actor_label,
    _resolve_next_url,
    _safe_deleted_record_return_url,
    _time_machine_toggle_url,
)

from .household_transition_shared import _flash_record_action_message
from .service_schedule_view_shared import _flash_google_calendar_sync_messages


def _person_can_become_district_officer(
    *,
    source_id: str,
    person: Person,
    family_category: str,
) -> bool:
    if family_category != FAMILY_CATEGORY_CURRENT or person.deleted_at is not None:
        return False
    profile = services.district_profile_for_person(source_id, person)
    return bool(
        profile is not None
        and profile.delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
        and profile.district_id is not None
    )


def edit_person(request: HttpRequest, household_id: str, person_id: str) -> HttpResponse:
    time_machine_mode = _normalize_time_machine_mode(
        request.GET.get("time_machine") or request.POST.get("time_machine")
    )
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("batch__source", "household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    active_source_id = person.batch.source.source_id
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    safe_return_url = _safe_deleted_record_return_url(
        next_url,
        household_id=household_id,
        deleted_record_type="person",
    )
    delete_result_mode = (request.GET.get("delete_result") or "").strip() in {"1", "true", "on"}
    relationship_choices = services.relationship_label_choices(
        active_source_id,
        current_value=person.relationship_label,
    )
    action = request.POST.get("action") or "save"
    if request.method == "POST":
        if action in {"delete", "restore"}:
            delete_outcome = perform_record_delete_action(
                action=action,
                record_type=RecordEditLog.RecordType.PERSON,
                record=person,
                serializer=_serialize_person_record,
                refresh=_person_for_edit,
                editor_label=_request_actor_label(request),
                change_note=request.POST.get("change_note", ""),
                deleted_message=f"家族レコード {person.person_uid} を削除済みにしました。",
                restored_message=f"家族レコード {person.person_uid} を復元しました。",
            )
            if delete_outcome is not None:
                if action == "restore":
                    messages.success(request, delete_outcome.user_message)
                    return redirect(
                        _edit_url(
                            "office:edit_person",
                            household_id,
                            person_id,
                            source_id=active_source_id,
                            next_url=safe_return_url,
                        )
                    )
                return redirect(
                    _edit_url(
                        "office:edit_person",
                        household_id,
                        person_id,
                        source_id=active_source_id,
                        next_url=safe_return_url,
                        extra_query={"delete_result": "1"},
                    )
                )
        before_data = _serialize_person_record(person, include_district_officer_context=True)
        form = PersonCalendarEditForm(
            request.POST,
            instance=person,
            relationship_choices=relationship_choices,
        )
        if form.is_valid():
            wants_district_officer = bool(form.cleaned_data.get("is_district_officer"))
            intended_family_category = (form.cleaned_data.get("family_category") or "").strip()
            if wants_district_officer and not _person_can_become_district_officer(
                source_id=active_source_id,
                person=person,
                family_category=intended_family_category,
            ):
                form.add_error(
                    "is_district_officer",
                    "地区役員は、地区所属の現在帳 person にだけ付けられます。",
                )
        if form.is_valid():
            with transaction.atomic():
                form.save()
                person = _person_for_edit(person.pk)
                if person.is_district_officer:
                    services.assign_district_officer_to_person(
                        active_source_id, person,
                        editor_label=_request_actor_label(request),
                        change_note=request.POST.get("change_note", "") or "家族編集から地区役員を保存",
                    )
                log_entry = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.PERSON,
                    record=person,
                    before_data=before_data,
                    after_data=_serialize_person_record(person, include_district_officer_context=True),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", ""),
                )
                if "sync_google_calendar" in form.fields:
                    sync_keys = update_person_schedule_names(
                        person, previous_name=before_data.get("name", ""),
                        editor_label=_request_actor_label(request),
                    )
                    if form.cleaned_data.get("sync_google_calendar") and sync_keys:
                        def sync_after_commit():
                            try:
                                results = google_calendar_sync.sync_google_calendar_for_sync_keys(sync_keys)
                                _flash_google_calendar_sync_messages(request, results, show_success=True)
                            except Exception:
                                messages.warning(request, "過去帳は保存しましたが、Googleカレンダーの同期に失敗しました。設定画面から再同期してください。")
                        transaction.on_commit(sync_after_commit)
            _flash_record_action_message(
                request,
                log_entry,
                f"家族レコード {person.person_uid} を更新しました。",
            )
            return redirect(next_url)
    else:
        form = PersonCalendarEditForm(
            instance=person,
            relationship_choices=relationship_choices,
        )
    if person.is_deleted and delete_result_mode:
        return render(
            request,
            "office/record_delete_confirm.html",
            {
                "title": "家族レコードを削除",
                "subtitle": f"{person.name or person.person_uid} / 台帳ID {household_id}",
                "delete_result_heading": "家族レコードを削除しました。",
                "delete_result_message": (
                    f"{person.name or person.person_uid} は非表示になりました。"
                ),
                "deleted_meta": _deleted_meta(person),
                "next_url": safe_return_url,
                "return_url": safe_return_url,
                "return_label": _deleted_record_return_label(
                    safe_return_url,
                    household_id=household_id,
                ),
            },
        )
    time_machine_field_options = (
        _build_time_machine_field_options(
            record_type=RecordEditLog.RecordType.PERSON,
            record_id=person.pk,
            form=form,
        )
        if time_machine_mode
        else {}
    )

    return render(
        request,
        "office/record_edit.html",
        {
            "title": "家族レコードを編集",
            "subtitle": f"{person.name or person.person_uid} / 台帳ID {household_id}",
            "form": form,
            "next_url": safe_return_url if person.is_deleted else next_url,
            "editor_label": _request_actor_label(request),
            "change_note": request.POST.get("change_note", ""),
            "record_deleted": person.is_deleted,
            "deleted_meta": _deleted_meta(person),
            "history_entries": _recent_record_history(
                RecordEditLog.RecordType.PERSON,
                person.pk,
            ),
            "can_delete": True,
            "move_memorial_person_url": (
                f"{_edit_url('office:move_memorial_person_household', household_id, person_id, source_id=active_source_id, next_url=_normalized_request_url(request))}"
                if memorial_person_move_is_available(person)
                else ""
            ),
            "relationship_anchor_name": _household_display_head_name(person.household) if person.household_id else "",
            "time_machine_mode": time_machine_mode,
            "time_machine_toggle_url": _time_machine_toggle_url(
                request,
                enabled=not time_machine_mode,
            ),
            "time_machine_field_options": time_machine_field_options,
        },
    )


__all__ = [
    "_person_can_become_district_officer",
    "edit_person",
]
