from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports import auxiliary_postal as postal_tools
from apps.imports import canonical_population
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_POSTAL,
    Household,
    HouseholdProfile,
    LegacySource,
    PostalReviewResolution,
    RecordEditLog,
)
from apps.office.services.auxiliary_postal_households import (
    _ensure_postal_recipient_current_person,
)
from apps.office.services.household_editing_core import (
    _apply_household_contact_defaults_to_person,
)
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.views.common import _ensure_source_record
from apps.office.views.settings_auxiliary_shared import (
    _flash_record_action_message,
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
def assign_postal_override(request: HttpRequest) -> HttpResponse:
    postal_folder = request.POST.get("postal_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    legacy_household_id = (request.POST.get("household_id") or "").strip()
    editor_label = _request_actor_label(request)
    active_source_id = _ensure_source_record(None).source_id
    redirect_url = _with_optional_query(
        reverse("office:postal_review"),
        postal_folder=postal_folder,
    )

    if not row_number_text.isdigit() or not legacy_household_id:
        messages.error(request, "別郵送先登録対象の郵送行または戸主が不正です。")
        return redirect(redirect_url)

    analysis = postal_tools.analyze_postal_rows(
        active_source_id,
        folder_name=postal_folder or None,
    )
    row_number = int(row_number_text)
    entry = _find_postal_review_entry(analysis, row_number)
    if entry is None:
        messages.error(request, "対象の郵送行が見つかりません。先に照合結果を更新してください。")
        return redirect(redirect_url)
    selected_folder_name = analysis["selected_folder_name"]

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        messages.error(request, "現行台帳が見つかりません。")
        return redirect(redirect_url)

    household = get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=legacy_household_id,
        deleted_at__isnull=True,
    )
    source_record = LegacySource.objects.get(source_id=active_source_id)

    with transaction.atomic():
        before_household = _serialize_household_record(household)
        mailing_person, before_mailing_person, created = _ensure_postal_recipient_current_person(
            household=household,
            entry=entry,
        )
        _apply_household_contact_defaults_to_person(mailing_person, household)
        mailing_person.save(
            update_fields=[
                "name",
                "family_category",
                "is_deceased",
                "raw_record",
                "updated_at",
            ]
        )
        mailing_person_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=mailing_person,
            before_data=before_mailing_person,
            after_data=_serialize_person_record(mailing_person),
            editor_label=editor_label,
            change_note=(
                f"郵送名簿 {entry['head_name']} を別郵送先 person として設定"
                + ("（新規 person 作成）" if created else "")
            ),
        )
        profile, _created = HouseholdProfile.objects.update_or_create(
            source=source_record,
            household_uid=household.household_uid,
            defaults={
                "delivery_method": HOUSEHOLD_DELIVERY_POSTAL,
                "district": None,
                "mailing_person_uid": mailing_person.person_uid,
                "mailing_name": entry["head_name"],
                "mailing_postal_code": entry["postal_code"],
                "mailing_address_line1": entry["address_line1"],
                "mailing_address_line2": entry["address_line2"],
                "mailing_phone": entry["phone"],
                "household_name_snapshot": household.display_head_name(),
                "household_name_kana_snapshot": household.display_head_name_kana(),
            },
        )
        household_log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_household,
            after_data=_serialize_household_record(household),
            editor_label=editor_label,
            change_note=f"郵送名簿 {entry['head_name']} を別郵送先として設定",
        )
        _record_postal_review_resolution(
            source=source_record,
            folder_name=selected_folder_name,
            row_number=row_number,
            resolution_kind=PostalReviewResolution.ResolutionKind.MAILING_OVERRIDE,
            selected_household_uid=household.household_uid,
            entry_head_name=entry["head_name"],
            target_household_name_snapshot=household.display_head_name(),
            editor_label=editor_label,
            note=f"台帳ID {household.household_uid} に別郵送先 {profile.mailing_name} を設定",
        )

    if mailing_person_log is not None:
        _flash_record_action_message(
            request,
            mailing_person_log,
            f"{mailing_person.name} を現在帳 person として確保しました。",
        )
    _flash_record_action_message(
        request,
        household_log,
        f"台帳ID {household.household_uid} に別郵送先 {profile.mailing_name} を設定しました。",
    )
    return redirect(redirect_url)
