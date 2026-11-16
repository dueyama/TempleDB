from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.imports.models import (
    HOUSEHOLD_DELIVERY_CHOICES,
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    District,
    Household,
    HouseholdProfile,
    RecordEditLog,
)
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.household_profile_editing import (
    _apply_household_delivery_profile_from_form,
)
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_household_record
from apps.office.views.common import _canonical_ledger_context, _ensure_source_record
from apps.office.web_support import (
    _request_actor_label,
    _resolve_household_edit_context,
    _resolve_next_url,
)

from .household_transition_shared import _flash_record_action_message


def update_household_delivery_assignment(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    source_record = _ensure_source_record(active_source_id)
    delivery_method = (request.POST.get("delivery_method") or "").strip()
    district_id = (request.POST.get("district_id") or "").strip()
    valid_delivery_methods = {choice[0] for choice in HOUSEHOLD_DELIVERY_CHOICES}
    if delivery_method not in valid_delivery_methods:
        messages.warning(request, "送付区分の指定が不正です。")
        return redirect(next_url)
    if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT and not district_id:
        messages.warning(request, "地区所属を選ぶ場合は、地区も選択してください。")
        return redirect(next_url)

    before_data = _serialize_household_record(household)
    with transaction.atomic():
        existing_profile = HouseholdProfile.objects.filter(
            source=source_record,
            household_uid=household.household_uid,
        ).first()
        if delivery_method:
            district = None
            if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
                district = get_object_or_404(District, pk=district_id)
            _apply_household_delivery_profile_from_form(
                source_record=source_record,
                household=household,
                delivery_method=delivery_method,
                district_id=str(district.id) if district is not None else "",
                editor_label=_request_actor_label(request),
                change_note="戸主ブラウザで地区・送付区分を更新",
                general_notice_opt_out=(
                    existing_profile.general_notice_opt_out
                    if existing_profile is not None
                    else None
                ),
                memorial_notice_opt_out=(
                    existing_profile.memorial_notice_opt_out
                    if existing_profile is not None
                    else None
                ),
            )
            delivery_label = HOUSEHOLD_DELIVERY_LABELS.get(delivery_method, delivery_method)
            message_text = (
                f"{_household_display_head_name(household)} の送付区分を "
                f"{district.name if district is not None else delivery_label} に更新しました。"
            )
        else:
            _apply_household_delivery_profile_from_form(
                source_record=source_record,
                household=household,
                delivery_method="",
                district_id="",
                editor_label=_request_actor_label(request),
                change_note="戸主ブラウザで地区・送付区分を解除",
                general_notice_opt_out=(
                    existing_profile.general_notice_opt_out
                    if existing_profile is not None
                    else None
                ),
                memorial_notice_opt_out=(
                    existing_profile.memorial_notice_opt_out
                    if existing_profile is not None
                    else None
                ),
            )
            message_text = f"{_household_display_head_name(household)} の地区・送付区分を解除しました。"
        household = Household.objects.get(pk=household.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_data,
            after_data=_serialize_household_record(household),
            editor_label=_request_actor_label(request),
            change_note="戸主ブラウザで地区・送付区分を更新",
        )
    _flash_record_action_message(request, log_entry, message_text)
    return redirect(next_url)


def clear_household_address_line2(
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
        reverse("office:data_quality"),
    )
    before_data = _serialize_household_record(household)
    change_note = (request.POST.get("change_note") or "").strip() or "データ問題点一覧で住所2重複を解消"
    with transaction.atomic():
        household.address_line2 = ""
        raw_record = dict(household.raw_record or {})
        raw_record["住所2"] = ""
        household.raw_record = raw_record
        household.save(update_fields=["address_line2", "raw_record", "updated_at"])
        household = Household.objects.select_related("head_person").get(pk=household.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_data,
            after_data=_serialize_household_record(household),
            editor_label=_request_actor_label(request),
            change_note=change_note,
        )
    _flash_record_action_message(
        request,
        log_entry,
        f"戸主レコード {household.household_uid} の住所2を空欄にしました。",
    )
    return redirect(next_url)
