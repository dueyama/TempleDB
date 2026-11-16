from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports import auxiliary_postal as postal_tools
from apps.imports import canonical_population
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_POSTAL,
    Household,
    HouseholdProfile,
    PostalReviewResolution,
    RecordEditLog,
)
from apps.office.services.auxiliary_postal_households import (
    _create_household_from_postal_entry,
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
from apps.office.views.settings_postal_review_views import (
    _find_postal_review_entry,
    _record_postal_review_resolution,
)
from apps.office.web_support import _request_actor_label


@require_POST
def create_postal_review_household(request: HttpRequest) -> HttpResponse:
    postal_folder = request.POST.get("postal_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    editor_label = _request_actor_label(request)
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    redirect_url = _with_optional_query(
        reverse("office:postal_review"),
        postal_folder=postal_folder,
    )

    if not row_number_text.isdigit():
        messages.error(request, "新しい家を作る対象の郵送行が不正です。")
        return redirect(redirect_url)

    analysis = postal_tools.analyze_postal_rows(
        active_source_id,
        folder_name=postal_folder or None,
    )
    row_number = int(row_number_text)
    entry = _find_postal_review_entry(analysis, row_number)
    if entry is None:
        messages.error(request, "郵送行が見つかりません。先に照合結果を更新してください。")
        return redirect(redirect_url)
    selected_folder_name = analysis["selected_folder_name"]

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        messages.error(request, "現行台帳が見つかりません。")
        return redirect(redirect_url)

    with transaction.atomic():
        household, head_person = _create_household_from_postal_entry(
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
            change_note=f"郵送名簿 {entry['head_name']} から新しい家を作成",
        )
        person_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=head_person,
            before_data={},
            after_data=_serialize_person_record(head_person),
            editor_label=editor_label,
            change_note=f"郵送名簿 {entry['head_name']} を新戸主 person として作成",
        )
        HouseholdProfile.objects.update_or_create(
            source=source_record,
            household_uid=household.household_uid,
            defaults={
                "delivery_method": HOUSEHOLD_DELIVERY_POSTAL,
                "district": None,
                "household_name_snapshot": household.display_head_name(),
                "household_name_kana_snapshot": household.display_head_name_kana(),
                "mailing_person_uid": "",
                "mailing_name": "",
                "mailing_postal_code": "",
                "mailing_address_line1": "",
                "mailing_address_line2": "",
                "mailing_phone": "",
            },
        )
        _record_postal_review_resolution(
            source=source_record,
            folder_name=selected_folder_name,
            row_number=row_number,
            resolution_kind=PostalReviewResolution.ResolutionKind.CREATE_HOUSEHOLD,
            selected_household_uid=household.household_uid,
            entry_head_name=entry["head_name"],
            target_household_name_snapshot=household.display_head_name(),
            editor_label=editor_label,
            note=f"台帳ID {household.household_uid} の新しい家を作成",
        )

    if household_log is not None:
        _flash_record_action_message(
            request,
            household_log,
            f"郵送名簿 {entry['head_name']} から新しい家を作成しました。",
        )
    if person_log is not None:
        _flash_record_action_message(
            request,
            person_log,
            f"{head_person.name} を新戸主 person として作成しました。",
        )
    return redirect(redirect_url)


@require_POST
def rollback_created_postal_review_household(request: HttpRequest) -> HttpResponse:
    postal_folder = request.POST.get("postal_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    editor_label = _request_actor_label(request)
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    redirect_url = _with_optional_query(
        reverse("office:postal_review"),
        postal_folder=postal_folder,
    )

    if not row_number_text.isdigit():
        messages.error(request, "作成取消対象の郵送行が不正です。")
        return redirect(redirect_url)

    analysis = postal_tools.analyze_postal_rows(
        active_source_id,
        folder_name=postal_folder or None,
    )
    row_number = int(row_number_text)
    selected_folder_name = analysis["selected_folder_name"]
    resolution = PostalReviewResolution.objects.filter(
        source=source_record,
        folder_name=selected_folder_name,
        row_number=row_number,
        resolution_kind=PostalReviewResolution.ResolutionKind.CREATE_HOUSEHOLD,
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
        expected_household_source_table="auxiliary_postal_household",
        expected_head_source_table="auxiliary_postal_household_head",
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
        if profile is not None:
            profile.delete()
        person_logs: list[RecordEditLog] = []
        for person in active_people:
            before_person = _serialize_person_record(person)
            person.mark_deleted(
                editor_label=editor_label,
                note="郵送名簿 review の「新しい家を作成」を取り消し",
            )
            person.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
            person_logs.append(
                _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.PERSON,
                    record=person,
                    before_data=before_person,
                    after_data=_serialize_person_record(person),
                    editor_label=editor_label,
                    change_note="郵送名簿 review の「新しい家を作成」を取り消し",
                )
            )
        household.mark_deleted(
            editor_label=editor_label,
            note="郵送名簿 review の「新しい家を作成」を取り消し",
        )
        household.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
        household_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_household,
            after_data=_serialize_household_record(household),
            editor_label=editor_label,
            change_note="郵送名簿 review の「新しい家を作成」を取り消し",
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
