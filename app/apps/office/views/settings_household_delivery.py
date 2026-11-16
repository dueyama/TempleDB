from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports import canonical_population
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_CHOICES,
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    HOUSEHOLD_DELIVERY_NONE,
    HOUSEHOLD_DELIVERY_POSTAL,
    District,
    Household,
    HouseholdProfile,
    LegacySource,
    RecordEditLog,
)
from apps.office import services
from apps.office.services.household_editing_core import (
    _household_display_head_name,
    _household_display_head_name_kana,
)
from apps.office.services.household_profile_editing import (
    _apply_household_delivery_profile_from_form,
)
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_household_record
from apps.office.views.common import _ensure_source_record
from apps.office.web_support import (
    _household_districts_url,
    _normalized_request_url,
    _request_actor_label,
)


@transaction.atomic
def household_districts(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    query = (request.GET.get("q") or request.POST.get("q") or "").strip()
    filter_district_id = (
        request.GET.get("filter_district_id") or request.POST.get("filter_district_id") or ""
    ).strip()
    source_record = LegacySource.objects.filter(source_id=active_source_id).first()
    if source_record is None:
        source_record = _ensure_source_record(active_source_id)
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    districts = list(District.objects.order_by("sort_order", "name"))
    selected_district = next(
        (district for district in districts if str(district.id) == filter_district_id),
        None,
    )
    filter_district_id = str(selected_district.id) if selected_district is not None else ""

    if request.method == "POST":
        household_id = (request.POST.get("household_id") or "").strip()
        delivery_method = (request.POST.get("delivery_method") or "").strip()
        district_id = (request.POST.get("district_id") or "").strip()
        household = None
        if provenance_batch is not None and household_id:
            household = Household.objects.filter(
                household_uid=household_id,
                deleted_at__isnull=True,
            ).first()
        if household is None:
            messages.warning(request, "対象の戸主が見つかりませんでした。")
            return redirect(_household_districts_url(q=query, filter_district_id=filter_district_id))

        if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT and not district_id:
            messages.warning(request, "地区所属を選ぶ場合は、地区も選択してください。")
            return redirect(_household_districts_url(q=query, filter_district_id=filter_district_id))

        before_household = _serialize_household_record(household)
        address_fields = ("postal_code", "address_line1", "address_line2", "address_line3")
        changed_address_fields: list[str] = []
        for field_name in address_fields:
            if field_name not in request.POST:
                continue
            value = (request.POST.get(field_name) or "").strip()
            if getattr(household, field_name) != value:
                setattr(household, field_name, value)
                changed_address_fields.append(field_name)
        if changed_address_fields:
            household.save(update_fields=[*changed_address_fields, "updated_at"])

        if delivery_method:
            district = None
            if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
                district = get_object_or_404(District, pk=district_id)
            existing_profile = HouseholdProfile.objects.filter(
                source=source_record,
                household_uid=household.household_uid,
            ).first()
            _apply_household_delivery_profile_from_form(
                source_record=source_record,
                household=household,
                delivery_method=delivery_method,
                district_id=str(district.id) if district is not None else "",
                editor_label=_request_actor_label(request),
                change_note="戸主地区・送付区分設定から更新",
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
            messages.success(
                request,
                (
                    f"{_household_display_head_name(household)} を "
                    f"{district.name if district is not None else delivery_label} に設定しました。"
                ),
            )
        else:
            existing_profile = HouseholdProfile.objects.filter(
                source=source_record,
                household_uid=household.household_uid,
            ).first()
            _apply_household_delivery_profile_from_form(
                source_record=source_record,
                household=household,
                delivery_method="",
                district_id="",
                editor_label=_request_actor_label(request),
                change_note="戸主地区・送付区分設定から解除",
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
            messages.success(
                request,
                f"{_household_display_head_name(household)} の地区割当を外しました。",
            )
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_household,
            after_data=_serialize_household_record(household),
            editor_label=_request_actor_label(request),
            change_note=request.POST.get("change_note", "") or "戸主地区・送付区分設定から更新",
        )
        return redirect(_household_districts_url(q=query, filter_district_id=filter_district_id))

    households: list[dict] = []
    district_household_count = 0
    postal_household_count = 0
    no_delivery_household_count = 0
    total_count = 0
    if provenance_batch is not None:
        rows = list(
            Household.objects.filter(deleted_at__isnull=True).select_related("head_person")
        )
        rows.sort(
            key=lambda row: (
                (_household_display_head_name_kana(row) or "").lower(),
                (_household_display_head_name(row) or "").lower(),
                row.legacy_household_id,
            )
        )
        profile_map = {
            profile.household_uid: profile
            for profile in HouseholdProfile.objects.select_related("district").filter(
                source__source_id=active_source_id
            )
        }
        total_count = len(rows)
        district_household_count = sum(
            1
            for row in rows
            if row.legacy_household_id in profile_map
            and profile_map[row.legacy_household_id].district_id is not None
            and profile_map[row.legacy_household_id].delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
        )
        postal_household_count = sum(
            1
            for row in rows
            if row.legacy_household_id in profile_map
            and profile_map[row.legacy_household_id].delivery_method == HOUSEHOLD_DELIVERY_POSTAL
        )
        no_delivery_household_count = sum(
            1
            for row in rows
            if row.legacy_household_id in profile_map
            and profile_map[row.legacy_household_id].delivery_method == HOUSEHOLD_DELIVERY_NONE
        )
        if selected_district is not None:
            rows = [
                row
                for row in rows
                if row.legacy_household_id in profile_map
                and profile_map[row.legacy_household_id].delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
                and profile_map[row.legacy_household_id].district_id == selected_district.id
            ]
        if query:
            lowered_query = query.lower()
            rows = [
                row
                for row in rows
                if lowered_query in (_household_display_head_name(row) or "").lower()
                or lowered_query in (_household_display_head_name_kana(row) or "").lower()
                or lowered_query in row.legacy_household_id.lower()
            ]
        for row in rows:
            profile = profile_map.get(row.legacy_household_id)
            households.append(
                {
                    "household_id": row.legacy_household_id,
                    "head_name": _household_display_head_name(row),
                    "head_name_kana": _household_display_head_name_kana(row),
                    "delivery_method": profile.delivery_method if profile else "",
                    "delivery_label": HOUSEHOLD_DELIVERY_LABELS.get(
                        profile.delivery_method if profile else "",
                        "未設定",
                    ),
                    "district_id": str(profile.district_id) if profile and profile.district_id else "",
                    "district_name": profile.district.name if profile and profile.district_id else "",
                    "postal_code": row.postal_code,
                    "address_line1": row.address_line1,
                    "address_line2": row.address_line2,
                    "address_line3": row.address_line3,
                    "phone": row.phone,
                }
            )

    context = {
        "selected_source_id": active_source_id,
        "query": query,
        "filter_district_id": filter_district_id,
        "selected_district": selected_district,
        "districts": districts,
        "households": households,
        "latest_household_batch_id": (
            provenance_batch.prepared_snapshot_id if provenance_batch else ""
        ),
        "total_household_count": total_count,
        "delivery_choices": HOUSEHOLD_DELIVERY_CHOICES,
        "district_household_count": district_household_count,
        "postal_household_count": postal_household_count,
        "no_delivery_household_count": no_delivery_household_count,
        "unassigned_household_count": max(
            total_count - district_household_count - postal_household_count - no_delivery_household_count,
            0,
        ),
        "current_url": _normalized_request_url(request),
    }
    return render(request, "office/household_districts.html", context)


__all__ = ["household_districts"]
