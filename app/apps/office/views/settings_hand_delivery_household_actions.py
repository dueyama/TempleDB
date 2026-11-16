from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports import auxiliary_hand_delivery as hand_delivery_tools
from apps.imports import canonical_population
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HandDeliveryReviewResolution,
    Household,
    HouseholdProfile,
    RecordEditLog,
)
from apps.office import services
from apps.office.services.auxiliary_hand_delivery_households import (
    _create_household_from_hand_delivery_entry,
)
from apps.office.services.district_ops import (
    _assign_district_officer_to_person,
    _ensure_district_from_hand_delivery_entry,
)
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.views.common import _ensure_source_record
from apps.office.views.settings_auxiliary_shared import (
    _flash_record_action_message,
    _rollbackable_created_auxiliary_household,
    _serialize_household_record,
    _serialize_person_record,
    _with_optional_query,
)
from apps.office.views.settings_hand_delivery_review_views import (
    _find_hand_delivery_review_entry,
    _record_hand_delivery_review_resolution,
)
from apps.office.web_support import _request_actor_label


@require_POST
def create_hand_delivery_review_household(request: HttpRequest) -> HttpResponse:
    hand_delivery_folder = request.POST.get("hand_delivery_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    editor_label = _request_actor_label(request)
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    redirect_url = _with_optional_query(
        reverse("office:hand_delivery_review"),
        hand_delivery_folder=hand_delivery_folder,
    )

    if not row_number_text.isdigit():
        messages.error(request, "新しい家を作る対象の手配り行が不正です。")
        return redirect(redirect_url)

    analysis = hand_delivery_tools.analyze_hand_delivery_district_rows(
        active_source_id,
        folder_name=hand_delivery_folder or None,
    )
    row_number = int(row_number_text)
    entry = _find_hand_delivery_review_entry(analysis, row_number)
    if entry is None:
        messages.error(request, "手配り行が見つかりません。先に照合結果を更新してください。")
        return redirect(redirect_url)
    selected_folder_name = analysis["selected_folder_name"]
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        messages.error(request, "現行台帳が見つかりません。")
        return redirect(redirect_url)

    with transaction.atomic():
        household, head_person = _create_household_from_hand_delivery_entry(
            batch=provenance_batch,
            source_record=source_record,
            entry=entry,
        )
        household_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data={},
            after_data=_serialize_household_record(household),
            editor_label=editor_label,
            change_note=f"手配り名簿 {entry['head_name']} から新しい家を作成",
        )
        person_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=head_person,
            before_data={},
            after_data=_serialize_person_record(head_person),
            editor_label=editor_label,
            change_note=f"手配り名簿 {entry['head_name']} を新戸主 person として作成",
        )
        district = _ensure_district_from_hand_delivery_entry(
            entry,
            source_id=active_source_id,
            editor_label=editor_label,
            change_note=f"手配り名簿 {selected_folder_name} の新しい家作成に伴う地区情報",
        )
        HouseholdProfile.objects.update_or_create(
            source=source_record,
            household_uid=household.household_uid,
            defaults={
                "delivery_method": HOUSEHOLD_DELIVERY_DISTRICT,
                "district": district,
                "household_name_snapshot": household.display_head_name(),
                "household_name_kana_snapshot": household.display_head_name_kana(),
            },
        )
        if entry.get("is_officer"):
            _assign_district_officer_to_person(
                district, head_person,
                editor_label=editor_label,
                change_note="手配り名簿から新しい家の地区役員を設定",
            )
        _record_hand_delivery_review_resolution(
            source=source_record,
            folder_name=selected_folder_name,
            row_number=row_number,
            resolution_kind=HandDeliveryReviewResolution.ResolutionKind.CREATE_HOUSEHOLD,
            selected_household_uid=household.household_uid,
            entry_head_name=entry["head_name"],
            target_household_name_snapshot=household.display_head_name(),
            editor_label=editor_label,
            note=f"台帳ID {household.household_uid} の新しい家を作成",
        )

    _flash_record_action_message(
        request,
        household_log,
        f"手配り名簿 {entry['head_name']} から新しい家を作成しました。",
    )
    _flash_record_action_message(
        request,
        person_log,
        f"{head_person.name} を新戸主 person として作成しました。",
    )
    return redirect(redirect_url)


@require_POST
def rollback_created_hand_delivery_review_household(request: HttpRequest) -> HttpResponse:
    hand_delivery_folder = request.POST.get("hand_delivery_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    editor_label = _request_actor_label(request)
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    redirect_url = _with_optional_query(
        reverse("office:hand_delivery_review"),
        hand_delivery_folder=hand_delivery_folder,
    )

    if not row_number_text.isdigit():
        messages.error(request, "作成取消対象の手配り行が不正です。")
        return redirect(redirect_url)

    analysis = hand_delivery_tools.analyze_hand_delivery_district_rows(
        active_source_id,
        folder_name=hand_delivery_folder or None,
    )
    row_number = int(row_number_text)
    selected_folder_name = analysis["selected_folder_name"]
    resolution = HandDeliveryReviewResolution.objects.filter(
        source=source_record,
        folder_name=selected_folder_name,
        row_number=row_number,
        resolution_kind=HandDeliveryReviewResolution.ResolutionKind.CREATE_HOUSEHOLD,
    ).first()
    if resolution is None:
        messages.error(request, "この行の新しい家作成は見つかりませんでした。")
        return redirect(redirect_url)

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        messages.error(request, "現行台帳が見つかりません。")
        return redirect(redirect_url)
    household = Household.objects.filter(
        household_uid=resolution.selected_household_uid,
        deleted_at__isnull=True,
    ).first()
    if household is None:
        messages.error(request, "作成された家が見つかりません。")
        return redirect(redirect_url)

    can_rollback, blocked_reason, active_people = _rollbackable_created_auxiliary_household(
        source_record=source_record,
        household=household,
        expected_household_source_table="auxiliary_hand_delivery_household",
        expected_head_source_table="auxiliary_hand_delivery_household_head",
    )
    if not can_rollback:
        messages.error(request, blocked_reason)
        return redirect(redirect_url)

    with transaction.atomic():
        before_household = _serialize_household_record(household)
        profile = HouseholdProfile.objects.filter(
            source=source_record,
            household_uid=household.household_uid,
        ).first()
        services.clear_district_officer_flags_for_household(
            active_source_id, household,
            editor_label=editor_label,
            change_note="手配り名簿から作成した家の取り消しに伴う地区役員解除",
        )
        if profile is not None:
            profile.delete()
        person_logs: list[RecordEditLog] = []
        for person in active_people:
            person.refresh_from_db()
            before_person = _serialize_person_record(person)
            person.mark_deleted(
                editor_label=editor_label,
                note="手配り名簿 review の「新しい家を作成」を取り消し",
            )
            person.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
            person_logs.append(
                _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.PERSON,
                    record=person,
                    before_data=before_person,
                    after_data=_serialize_person_record(person),
                    editor_label=editor_label,
                    change_note="手配り名簿 review の「新しい家を作成」を取り消し",
                )
            )
        household.mark_deleted(
            editor_label=editor_label,
            note="手配り名簿 review の「新しい家を作成」を取り消し",
        )
        household.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
        household_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_household,
            after_data=_serialize_household_record(household),
            editor_label=editor_label,
            change_note="手配り名簿 review の「新しい家を作成」を取り消し",
        )
        resolution.delete()

    _flash_record_action_message(
        request,
        household_log,
        f"台帳ID {household.household_uid} の新しい家作成を取り消しました。",
    )
    for log in person_logs:
        _flash_record_action_message(request, log, "作成された戸主 person を非表示に戻しました。")
    return redirect(redirect_url)
