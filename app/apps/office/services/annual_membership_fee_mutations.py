from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from django.db import transaction
from django.utils import timezone

from apps.imports import canonical_population
from apps.imports.forms import AnnualMembershipFeeEntryForm, AnnualMembershipFeeSettingForm
from apps.imports.household_profile_runtime import _household_profile_for_display
from apps.imports.models import (
    AnnualMembershipFeePayment,
    AnnualMembershipFeeSetting,
    Household,
    ImportBatch,
    LegacySource,
    RecordEditLog,
)
from apps.office.services.annual_membership_fee_context import (
    _annual_membership_fee_exclusion_reason,
)
from apps.office.services.household_editing_core import _household_display_head_name

from .annual_membership_fee_history import (
    serialize_annual_membership_fee_payment,
    serialize_annual_membership_fee_setting,
)
from .record_history_mutations import _create_record_edit_log


@dataclass(slots=True)
class AnnualMembershipFeeRowMutationResult:
    should_redirect: bool
    message_level: Literal["success", "error"] | None = None
    message: str = ""


@dataclass(slots=True)
class AnnualMembershipFeeBulkReceiveResult:
    saved_count: int
    skipped_count: int
    error_messages: list[str]


@transaction.atomic
def save_annual_membership_fee_setting(
    *,
    setting_form: AnnualMembershipFeeSettingForm,
    source_record: LegacySource,
    year: int,
    editor_label: str = "",
    change_note: str = "",
) -> str:
    previous = (
        AnnualMembershipFeeSetting.objects.select_for_update()
        .filter(source=source_record, year=year)
        .first()
    )
    before_data = serialize_annual_membership_fee_setting(previous)
    saved = setting_form.save(commit=False)
    saved.source = source_record
    saved.year = year
    saved.save()
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_SETTING,
        record=saved,
        before_data=before_data,
        after_data=serialize_annual_membership_fee_setting(saved),
        editor_label=(editor_label or "").strip() or "system",
        change_note=(change_note or "").strip() or "護持会費の年既定額を保存",
        source_id=source_record.source_id,
        household_uid="",
        record_label=f"{year}年護持会費既定額",
    )
    return f"{year}年の護持会費既定額を保存しました。"


@transaction.atomic
def apply_annual_membership_fee_row_action(
    *,
    active_source_id: str,
    source_record: LegacySource,
    year: int,
    household: Household,
    row_action: str,
    row_form: AnnualMembershipFeeEntryForm,
    default_amount: Decimal | None,
    editor_label: str = "",
    change_note: str = "",
) -> AnnualMembershipFeeRowMutationResult:
    profile = _household_profile_for_display(active_source_id, household.household_uid)
    exclusion_reason = _annual_membership_fee_exclusion_reason(
        household=household,
        profile=profile,
    )
    household_name = _household_display_head_name(household)
    if exclusion_reason and row_action != "clear":
        return AnnualMembershipFeeRowMutationResult(
            should_redirect=True,
            message_level="error",
            message=f"{household_name} は {exclusion_reason}",
        )

    payment = AnnualMembershipFeePayment.objects.select_for_update().filter(
        source=source_record,
        household_uid=household.household_uid,
        year=year,
    ).first()
    before_data = serialize_annual_membership_fee_payment(payment)
    if not row_form.cleaned_data["paid"]:
        if payment is not None:
            payment.delete()
            _create_record_edit_log(
                record_type=RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT,
                record=payment,
                before_data=before_data,
                after_data={},
                editor_label=(editor_label or "").strip() or "system",
                change_note=(change_note or "").strip() or "護持会費を未納扱いへ戻す",
                source_id=source_record.source_id,
                household_uid=household.household_uid,
                record_label=f"{household_name} / {year}年護持会費",
                action_kind=RecordEditLog.ActionKind.DELETE,
            )
        return AnnualMembershipFeeRowMutationResult(
            should_redirect=True,
            message_level="success",
            message=f"{household_name} を未納扱いへ戻しました。",
        )

    is_exception = bool(row_form.cleaned_data["is_exception"])
    amount = row_form.cleaned_data.get("amount_override") if is_exception else default_amount
    if amount in {None, Decimal("0"), 0}:
        row_form.add_error(
            "amount_override" if is_exception else None,
            "先に今年の既定額を入れるか、例外金額を指定してください。",
        )
        return AnnualMembershipFeeRowMutationResult(should_redirect=False)

    payment_defaults = {
        "household_name_snapshot": household_name,
        "delivery_method_snapshot": profile.delivery_method if profile is not None else "",
        "district_name_snapshot": (
            profile.district.name if profile is not None and profile.district_id else ""
        ),
        "received_on": row_form.cleaned_data.get("received_on") or timezone.localdate(),
        "amount": amount,
        "is_exception": is_exception,
        "note": (row_form.cleaned_data.get("note") or "").strip(),
    }
    saved, _created = AnnualMembershipFeePayment.objects.update_or_create(
        source=source_record,
        household_uid=household.household_uid,
        year=year,
        defaults=payment_defaults,
    )
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT,
        record=saved,
        before_data=before_data,
        after_data=serialize_annual_membership_fee_payment(saved),
        editor_label=(editor_label or "").strip() or "system",
        change_note=(change_note or "").strip() or "護持会費の受領・金額を保存",
        source_id=source_record.source_id,
        household_uid=household.household_uid,
        record_label=f"{household_name} / {year}年護持会費",
    )
    return AnnualMembershipFeeRowMutationResult(
        should_redirect=True,
        message_level="success",
        message=f"{household_name} の護持会費を保存しました。",
    )


@transaction.atomic
def apply_annual_membership_fee_bulk_receive(
    *,
    active_source_id: str,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    household_ids: list[str],
    received_on: date | None,
    default_amount: Decimal | None,
    note: str = "受領チェックシート読取",
    editor_label: str = "",
    change_note: str = "",
) -> AnnualMembershipFeeBulkReceiveResult:
    del batch
    canonical_population.canonical_provenance_import_batch(
        source_id=source_record.source_id,
    )
    requested_ids = [household_id for household_id in household_ids if household_id]
    if not requested_ids:
        return AnnualMembershipFeeBulkReceiveResult(
            saved_count=0,
            skipped_count=0,
            error_messages=["受領にする候補がありません。"],
        )
    if default_amount in {None, Decimal("0"), 0}:
        return AnnualMembershipFeeBulkReceiveResult(
            saved_count=0,
            skipped_count=len(requested_ids),
            error_messages=["先に今年の既定額を入れてください。"],
        )

    households = {
        household.household_uid: household
        for household in Household.objects.select_related("head_person").filter(
            household_uid__in=requested_ids,
            deleted_at__isnull=True,
        )
    }
    saved_count = 0
    skipped_count = 0
    error_messages: list[str] = []
    for household_id in requested_ids:
        household = households.get(household_id)
        if household is None:
            skipped_count += 1
            error_messages.append(f"{household_id} は現在の戸主に見つかりません。")
            continue
        profile = _household_profile_for_display(active_source_id, household.household_uid)
        exclusion_reason = _annual_membership_fee_exclusion_reason(
            household=household,
            profile=profile,
        )
        household_name = _household_display_head_name(household)
        if exclusion_reason:
            skipped_count += 1
            error_messages.append(f"{household_name} は {exclusion_reason}")
            continue
        previous = (
            AnnualMembershipFeePayment.objects.select_for_update()
            .filter(source=source_record, household_uid=household.household_uid, year=year)
            .first()
        )
        before_data = serialize_annual_membership_fee_payment(previous)
        saved, _created = AnnualMembershipFeePayment.objects.update_or_create(
            source=source_record,
            household_uid=household.household_uid,
            year=year,
            defaults={
                "household_name_snapshot": household_name,
                "delivery_method_snapshot": profile.delivery_method if profile is not None else "",
                "district_name_snapshot": (
                    profile.district.name if profile is not None and profile.district_id else ""
                ),
                "received_on": received_on or timezone.localdate(),
                "amount": default_amount,
                "is_exception": False,
                "note": note.strip(),
            },
        )
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT,
            record=saved,
            before_data=before_data,
            after_data=serialize_annual_membership_fee_payment(saved),
            editor_label=(editor_label or "").strip() or "system",
            change_note=(change_note or "").strip() or "受領チェックシートから護持会費を一括受領",
            source_id=source_record.source_id,
            household_uid=household.household_uid,
            record_label=f"{household_name} / {year}年護持会費",
        )
        saved_count += 1
    return AnnualMembershipFeeBulkReceiveResult(
        saved_count=saved_count,
        skipped_count=skipped_count,
        error_messages=error_messages,
    )


__all__ = [
    "apply_annual_membership_fee_row_action",
    "apply_annual_membership_fee_bulk_receive",
    "save_annual_membership_fee_setting",
]
