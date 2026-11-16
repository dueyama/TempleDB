from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.imports.forms import HouseholdEditForm
from apps.imports.models import District, Household, RecordEditLog
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.household_head_editing import (
    _is_virtual_household_head_person,
    _sync_household_head_person_identity_from_form,
)
from apps.office.services.household_profile_editing import (
    _apply_household_delivery_profile_from_form,
    _apply_household_head_gender_from_form,
    _household_profile_initial_values,
    _resolved_household_general_notice_opt_out,
    _resolved_household_head_gender,
    _resolved_household_memorial_notice_opt_out,
)
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    perform_record_delete_action,
)
from apps.office.services.record_history_snapshot import (
    _deleted_meta,
    _serialize_household_record,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options,
    _recent_record_history,
)
from apps.office.views.common import _ensure_source_record
from apps.office.web_support import (
    _deleted_record_return_label,
    _normalize_time_machine_mode,
    _normalized_request_url,
    _request_actor_label,
    _resolve_household_edit_context,
    _safe_deleted_record_return_url,
    _time_machine_toggle_url,
)

from .household_transition_shared import (
    _flash_record_action_message,
    _household_extinct_action_state,
)


def _build_deleted_household_context(
    *,
    household: Household,
    household_id: str,
    safe_return_url: str,
) -> dict[str, object]:
    return {
        "title": "戸主レコードを削除",
        "subtitle": f"{_household_display_head_name(household)} / 台帳ID {household.household_uid}",
        "delete_result_heading": "戸主レコードを削除しました。",
        "delete_result_message": f"台帳ID {household.household_uid} は一覧から外れました。",
        "deleted_meta": _deleted_meta(household),
        "next_url": safe_return_url,
        "return_url": safe_return_url,
        "return_label": _deleted_record_return_label(
            safe_return_url,
            household_id=household_id,
        ),
    }


def _build_household_edit_context(
    *,
    request: HttpRequest,
    household: Household,
    household_id: str,
    form: HouseholdEditForm,
    next_url: str,
    safe_return_url: str,
    time_machine_mode: bool,
    time_machine_field_options: dict[str, object],
    resolved_head_person,
    head_person_is_virtual: bool,
    extinct_action_state: dict[str, object],
) -> dict[str, object]:
    head_person_edit_url = (
        _edit_url(
            "office:edit_person",
            household.household_uid,
            resolved_head_person.person_uid,
            source_id="",
            next_url=_normalized_request_url(request),
        )
        if resolved_head_person is not None and not head_person_is_virtual
        else ""
    )
    replace_virtual_head_url = (
        _edit_url(
            "office:replace_virtual_head",
            household.household_uid,
            source_id="",
            next_url=_normalized_request_url(request),
        )
        if head_person_is_virtual
        else ""
    )
    mark_household_extinct_url = (
        _edit_url(
            "office:mark_household_extinct",
            household.household_uid,
            source_id="",
            next_url=_normalized_request_url(request),
        )
        if bool(extinct_action_state["show_action"])
        else ""
    )
    return {
        "title": "戸主レコードを編集",
        "subtitle": f"{_household_display_head_name(household)} / 台帳ID {household.household_uid}",
        "form": form,
        "next_url": safe_return_url if household.is_deleted else next_url,
        "editor_label": _request_actor_label(request),
        "change_note": request.POST.get("change_note", ""),
        "record_deleted": household.is_deleted,
        "deleted_meta": _deleted_meta(household),
        "history_entries": _recent_record_history(
            RecordEditLog.RecordType.HOUSEHOLD,
            household.pk,
        ),
        "can_delete": True,
        "time_machine_mode": time_machine_mode,
        "time_machine_toggle_url": _time_machine_toggle_url(
            request,
            enabled=not time_machine_mode,
        ),
        "time_machine_field_options": time_machine_field_options,
        "head_person_edit_url": head_person_edit_url,
        "replace_virtual_head_url": replace_virtual_head_url,
        "head_person_is_virtual": head_person_is_virtual,
        "household_extinct_message": str(extinct_action_state["message"] or ""),
        "mark_household_extinct_url": mark_household_extinct_url,
    }


def edit_household(request: HttpRequest, household_id: str) -> HttpResponse:
    time_machine_mode = _normalize_time_machine_mode(
        request.GET.get("time_machine") or request.POST.get("time_machine")
    )
    active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    safe_return_url = _safe_deleted_record_return_url(
        next_url,
        household_id=household_id,
        deleted_record_type="household",
    )
    delete_result_mode = (request.GET.get("delete_result") or "").strip() in {"1", "true", "on"}
    source_record = _ensure_source_record(active_source_id)
    districts = list(District.objects.order_by("sort_order", "name"))
    (
        initial_delivery_method,
        initial_district_id,
        initial_household_general_notice_opt_out,
        initial_household_memorial_notice_opt_out,
    ) = _household_profile_initial_values(
        active_source_id,
        household.household_uid,
    )
    initial_household_general_notice_opt_out = _resolved_household_general_notice_opt_out(
        source_id=active_source_id,
        household=household,
    )
    initial_household_memorial_notice_opt_out = _resolved_household_memorial_notice_opt_out(
        source_id=active_source_id,
        household=household,
    )
    initial_head_gender = _resolved_household_head_gender(household) or "未決定"
    resolved_head_person = household.resolve_head_person()
    head_person_is_virtual = _is_virtual_household_head_person(resolved_head_person)
    extinct_action_state = _household_extinct_action_state(
        household=household,
        resolved_head_person=resolved_head_person,
        head_person_is_virtual=head_person_is_virtual,
    )
    action = request.POST.get("action") or "save"
    if request.method == "POST":
        if action in {"delete", "restore"}:
            delete_outcome = perform_record_delete_action(
                action=action,
                record_type=RecordEditLog.RecordType.HOUSEHOLD,
                record=household,
                serializer=_serialize_household_record,
                refresh=lambda record_id: Household.objects.get(pk=record_id),
                editor_label=_request_actor_label(request),
                change_note=request.POST.get("change_note", ""),
                deleted_message=f"戸主レコード {household.household_uid} を削除済みにしました。",
                restored_message=f"戸主レコード {household.household_uid} を復元しました。",
            )
            if delete_outcome is not None:
                if action == "restore":
                    messages.success(request, delete_outcome.user_message)
                    return redirect(
                        _edit_url(
                            "office:edit_household",
                            household.household_uid,
                            source_id=active_source_id,
                            next_url=safe_return_url,
                        )
                    )
                return redirect(
                    _edit_url(
                        "office:edit_household",
                        household.household_uid,
                        source_id=active_source_id,
                        next_url=safe_return_url,
                        extra_query={"delete_result": "1"},
                    )
                )
        before_data = _serialize_household_record(household)
        form = HouseholdEditForm(
            request.POST,
            instance=household,
            districts=districts,
            initial_delivery_method=initial_delivery_method,
            initial_district_id=initial_district_id,
            initial_household_general_notice_opt_out=initial_household_general_notice_opt_out,
            initial_household_memorial_notice_opt_out=initial_household_memorial_notice_opt_out,
            initial_head_gender=initial_head_gender,
            disable_head_identity_fields=head_person_is_virtual,
        )
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _sync_household_head_person_identity_from_form(
                    household=household,
                    head_name=(form.cleaned_data.get("head_person_name") or "").strip(),
                    head_name_kana=(form.cleaned_data.get("head_person_kana") or "").strip(),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", "") or "戸主レコード編集で戸主名を同期",
                )
                _apply_household_delivery_profile_from_form(
                    source_record=source_record,
                    household=household,
                    delivery_method=(form.cleaned_data.get("delivery_method") or "").strip(),
                    district_id=(form.cleaned_data.get("district_id") or "").strip(),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", "") or "戸主編集で地区・送付区分を更新",
                    general_notice_opt_out=bool(
                        form.cleaned_data.get("household_general_notice_opt_out")
                    ),
                    memorial_notice_opt_out=bool(
                        form.cleaned_data.get("household_memorial_notice_opt_out")
                    ),
                )
                _apply_household_head_gender_from_form(
                    household=household,
                    head_gender=(form.cleaned_data.get("head_gender") or "未決定").strip() or "未決定",
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", "") or "戸主レコード編集で戸主の性別を更新",
                )
                household = Household.objects.select_related("head_person").get(pk=household.pk)
                log_entry = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.HOUSEHOLD,
                    record=household,
                    before_data=before_data,
                    after_data=_serialize_household_record(household),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", ""),
                )
            _flash_record_action_message(
                request,
                log_entry,
                f"戸主レコード {household.household_uid} を更新しました。",
            )
            return redirect(next_url)
    else:
        form = HouseholdEditForm(
            instance=household,
            districts=districts,
            initial_delivery_method=initial_delivery_method,
            initial_district_id=initial_district_id,
            initial_household_general_notice_opt_out=initial_household_general_notice_opt_out,
            initial_household_memorial_notice_opt_out=initial_household_memorial_notice_opt_out,
            initial_head_gender=initial_head_gender,
            disable_head_identity_fields=head_person_is_virtual,
        )
    if household.is_deleted and delete_result_mode:
        return render(
            request,
            "office/record_delete_confirm.html",
            _build_deleted_household_context(
                household=household,
                household_id=household_id,
                safe_return_url=safe_return_url,
            ),
        )
    time_machine_field_options = (
        _build_time_machine_field_options(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record_id=household.pk,
            form=form,
        )
        if time_machine_mode
        else {}
    )

    return render(
        request,
        "office/record_edit.html",
        _build_household_edit_context(
            request=request,
            household=household,
            household_id=household_id,
            form=form,
            next_url=next_url,
            safe_return_url=safe_return_url,
            time_machine_mode=time_machine_mode,
            time_machine_field_options=time_machine_field_options,
            resolved_head_person=resolved_head_person,
            head_person_is_virtual=head_person_is_virtual,
            extinct_action_state=extinct_action_state,
        ),
    )
