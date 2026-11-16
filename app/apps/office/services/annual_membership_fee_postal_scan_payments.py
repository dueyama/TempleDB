from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

import apps.office.services.annual_membership_fee_postal_scan_receipts as receipt_services
from apps.imports import canonical_population
from apps.imports.household_profile_runtime import _household_profile_for_display
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_NONE,
    AnnualMembershipFeePayment,
    AnnualMembershipFeePostalScan,
    Household,
    HouseholdProfile,
    LegacySource,
)
from apps.office.services.annual_membership_fee_context import (
    ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON,
    _annual_membership_fee_exclusion_reason,
)
from apps.office.services.household_editing_core import _household_display_head_name

POSTAL_SCAN_PAYMENT_NOTE = "郵便振込PDF照合"
POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE = "郵便振込PDF照合（案内不要設定時の実入金）"
POSTAL_SCAN_UNKNOWN_PAYMENT_LABEL = "不明入金"


@dataclass(slots=True)
class PostalScanPaymentSaveResult:
    """Internal DB outcome; the public service adds PDF movement and UI messages."""

    success: bool
    message: str = ""
    scan: AnnualMembershipFeePostalScan | None = None
    was_checked: bool = False
    household_name: str = ""
    receipt_warning: str = ""


def active_canonical_households(*, source_id: str):
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    return Household.objects.filter(deleted_at__isnull=True)


def postal_scan_receipt_policy(
    *,
    profile: HouseholdProfile | None,
    exclusion_reason: str,
) -> tuple[bool, str]:
    if not exclusion_reason:
        return True, ""
    if (
        exclusion_reason == ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON
        and profile is not None
        and (profile.delivery_method or "").strip() == HOUSEHOLD_DELIVERY_NONE
    ):
        return (
            True,
            "案内不要（送付しない設定）の家です。通常の請求対象外ですが、"
            "実際の振込として受領できます。",
        )
    return False, ""


def append_postal_scan_revision(
    payload: dict,
    *,
    scan: AnnualMembershipFeePostalScan,
    payment: AnnualMembershipFeePayment | None,
    actor_label: str,
) -> dict:
    revised_payload = dict(payload)
    history = list(revised_payload.get("revision_history") or [])
    unknown_payment = revised_payload.get("unknown_payment") or {}
    history.append(
        {
            "changed_at": timezone.now().isoformat(),
            "changed_by": actor_label,
            "previous": {
                "selected_household_uid": scan.selected_household_uid,
                "selected_household_name_snapshot": scan.selected_household_name_snapshot,
                "payment_id": payment.id if payment is not None else None,
                "received_on": (
                    payment.received_on.isoformat()
                    if payment is not None and payment.received_on
                    else ""
                ),
                "amount": str(payment.amount) if payment is not None else "",
                "is_exception": payment.is_exception if payment is not None else False,
                "received_by": payment.received_by if payment is not None else "",
                "note": payment.note if payment is not None else "",
                "unknown_payment_note": str(unknown_payment.get("note") or ""),
                "confirmed_at": scan.confirmed_at.isoformat() if scan.confirmed_at else "",
                "confirmed_by": scan.confirmed_by,
            },
        }
    )
    revised_payload["revision_history"] = history
    return revised_payload


def save_postal_scan_payment(
    *,
    active_source_id: str,
    source_record: LegacySource,
    scan: AnnualMembershipFeePostalScan,
    selected_household_id: str,
    year: int,
    received_on: date | None,
    default_amount: Decimal | None,
    actor_label: str = "",
    receipt_details_loader: Callable[[AnnualMembershipFeePostalScan], dict],
    allow_reedit: bool = False,
) -> PostalScanPaymentSaveResult:
    if scan.source_id != source_record.id or scan.year != year:
        return PostalScanPaymentSaveResult(
            success=False, message="この年度の郵便振込PDFではありません。"
        )
    household = (
        active_canonical_households(source_id=source_record.source_id)
        .select_related("head_person")
        .filter(
            household_uid=selected_household_id,
        )
        .first()
    )
    if household is None:
        return PostalScanPaymentSaveResult(
            success=False, message="選択した家が現在の戸主に見つかりません。"
        )
    profile = _household_profile_for_display(active_source_id, household.household_uid)
    exclusion_reason = _annual_membership_fee_exclusion_reason(household=household, profile=profile)
    household_name = _household_display_head_name(household) or household.household_uid
    can_receive_payment, receipt_warning = postal_scan_receipt_policy(
        profile=profile,
        exclusion_reason=exclusion_reason,
    )
    if not can_receive_payment:
        return PostalScanPaymentSaveResult(
            success=False, message=f"{household_name} は {exclusion_reason}"
        )

    with transaction.atomic():
        locked_scan = AnnualMembershipFeePostalScan.objects.select_for_update().get(pk=scan.pk)
        if locked_scan.source_id != source_record.id or locked_scan.year != year:
            return PostalScanPaymentSaveResult(
                success=False, message="この年度の郵便振込PDFではありません。"
            )
        was_checked = locked_scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
        if was_checked and not allow_reedit:
            return PostalScanPaymentSaveResult(success=False, message="このPDFは処理済みです。")
        if locked_scan.payment_id and not was_checked:
            return PostalScanPaymentSaveResult(
                success=False,
                message="入金は保存済みです。先にPDF移動を再実行してください。",
            )

        old_payment = None
        if locked_scan.payment_id:
            old_payment = AnnualMembershipFeePayment.objects.select_for_update().get(
                pk=locked_scan.payment_id
            )
            if old_payment.source_id != source_record.id or old_payment.year != year:
                return PostalScanPaymentSaveResult(
                    success=False,
                    message="確定済み入金の年度またはデータ元が一致しないため、この画面では変更できません。",
                )

        if not was_checked:
            existing_payment = (
                AnnualMembershipFeePayment.objects.select_for_update()
                .filter(
                    source=source_record,
                    household_uid=household.household_uid,
                    year=year,
                )
                .first()
            )
            if existing_payment is not None:
                return PostalScanPaymentSaveResult(
                    success=False,
                    message=f"{household_name} には同年度の入金が既にあるため、自動更新しません。",
                )

        receipt_details = receipt_details_loader(locked_scan)
        receipt_amount = receipt_services.net_amount_from_receipt_details(receipt_details)
        payment_amount = (
            old_payment.amount
            if was_checked and old_payment is not None
            else receipt_amount
            if receipt_amount is not None
            else default_amount
        )
        if payment_amount is None or payment_amount <= Decimal("0"):
            return PostalScanPaymentSaveResult(
                success=False,
                message="PDFの払込金額、または今年の既定額を確認してください。",
            )
        payment_received_on = (
            old_payment.received_on
            if was_checked and old_payment is not None
            else received_on or locked_scan.statement_date or timezone.localdate()
        )
        payment_household_defaults = {
            "household_name_snapshot": household_name,
            "delivery_method_snapshot": profile.delivery_method if profile is not None else "",
            "district_name_snapshot": (
                profile.district.name if profile is not None and profile.district_id else ""
            ),
        }
        payment_defaults = {
            **payment_household_defaults,
            "received_on": payment_received_on,
            "amount": payment_amount,
            "is_exception": False,
            "received_by": actor_label,
            "note": (
                POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE if receipt_warning else POSTAL_SCAN_PAYMENT_NOTE
            ),
        }

        payload = receipt_services.with_receipt_details(
            locked_scan.candidate_payload or {},
            receipt_details,
        )
        if was_checked:
            payload = append_postal_scan_revision(
                payload,
                scan=locked_scan,
                payment=old_payment,
                actor_label=actor_label,
            )
        payload.pop("unknown_payment", None)

        if was_checked:
            if (
                old_payment is not None
                and old_payment.postal_scans.exclude(pk=locked_scan.pk).exists()
            ):
                return PostalScanPaymentSaveResult(
                    success=False,
                    message="この入金には複数のPDFが結び付いているため、この画面では変更できません。",
                )
            destination_payments = AnnualMembershipFeePayment.objects.select_for_update().filter(
                source=source_record,
                household_uid=household.household_uid,
                year=year,
            )
            if old_payment is not None:
                destination_payments = destination_payments.exclude(pk=old_payment.pk)
            destination_payment = destination_payments.first()
            if destination_payment is not None:
                return PostalScanPaymentSaveResult(
                    success=False,
                    message=f"{household_name} には同年度の入金が既にあるため、自動変更しません。",
                )
            if old_payment is None:
                payment = AnnualMembershipFeePayment.objects.create(
                    source=source_record,
                    household_uid=household.household_uid,
                    year=year,
                    **payment_defaults,
                )
            else:
                payment = old_payment
                payment.household_uid = household.household_uid
                payment_update_defaults = dict(payment_household_defaults)
                if payment.note in {
                    POSTAL_SCAN_PAYMENT_NOTE,
                    POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE,
                }:
                    payment_update_defaults["note"] = payment_defaults["note"]
                for field_name, value in payment_update_defaults.items():
                    setattr(payment, field_name, value)
                payment.save(
                    update_fields=[
                        "household_uid",
                        *payment_update_defaults.keys(),
                        "updated_at",
                    ]
                )
        else:
            try:
                with transaction.atomic():
                    payment = AnnualMembershipFeePayment.objects.create(
                        source=source_record,
                        household_uid=household.household_uid,
                        year=year,
                        **payment_defaults,
                    )
            except IntegrityError:
                return PostalScanPaymentSaveResult(
                    success=False,
                    message=f"{household_name} には同年度の入金が既にあるため、自動更新しません。",
                )

        locked_scan.selected_household_uid = household.household_uid
        locked_scan.selected_household_name_snapshot = household_name
        locked_scan.payment = payment
        locked_scan.confirmed_by = actor_label
        locked_scan.confirmed_at = timezone.now()
        locked_scan.status = AnnualMembershipFeePostalScan.Status.CHECKED
        locked_scan.move_error = ""
        locked_scan.candidate_payload = payload
        locked_scan.save(
            update_fields=[
                "selected_household_uid",
                "selected_household_name_snapshot",
                "payment",
                "confirmed_by",
                "confirmed_at",
                "status",
                "move_error",
                "candidate_payload",
                "updated_at",
            ]
        )
        scan = locked_scan

    return PostalScanPaymentSaveResult(
        success=True,
        scan=scan,
        was_checked=was_checked,
        household_name=household_name,
        receipt_warning=receipt_warning,
    )


def save_postal_scan_unknown_payment(
    *,
    source_record: LegacySource,
    scan: AnnualMembershipFeePostalScan,
    year: int,
    note: str = "",
    actor_label: str = "",
    allow_reedit: bool = False,
) -> PostalScanPaymentSaveResult:
    if scan.source_id != source_record.id or scan.year != year:
        return PostalScanPaymentSaveResult(
            success=False, message="この年度の郵便振込PDFではありません。"
        )
    with transaction.atomic():
        locked_scan = AnnualMembershipFeePostalScan.objects.select_for_update().get(pk=scan.pk)
        if locked_scan.source_id != source_record.id or locked_scan.year != year:
            return PostalScanPaymentSaveResult(
                success=False, message="この年度の郵便振込PDFではありません。"
            )
        was_checked = locked_scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
        if was_checked and not allow_reedit:
            return PostalScanPaymentSaveResult(success=False, message="このPDFは処理済みです。")
        if locked_scan.payment_id and not was_checked:
            return PostalScanPaymentSaveResult(
                success=False,
                message="入金は保存済みです。先にPDF移動を再実行してください。",
            )
        old_payment = None
        if locked_scan.payment_id:
            old_payment = AnnualMembershipFeePayment.objects.select_for_update().get(
                pk=locked_scan.payment_id
            )
            if old_payment.source_id != source_record.id or old_payment.year != year:
                return PostalScanPaymentSaveResult(
                    success=False,
                    message="確定済み入金の年度またはデータ元が一致しないため、この画面では変更できません。",
                )
            if old_payment.postal_scans.exclude(pk=locked_scan.pk).exists():
                return PostalScanPaymentSaveResult(
                    success=False,
                    message="この入金には複数のPDFが結び付いているため、この画面では変更できません。",
                )

        payload = dict(locked_scan.candidate_payload or {})
        if was_checked:
            payload = append_postal_scan_revision(
                payload,
                scan=locked_scan,
                payment=old_payment,
                actor_label=actor_label,
            )
        payload["unknown_payment"] = {
            "marked_at": timezone.now().isoformat(),
            "marked_by": actor_label,
            "note": (note or "").strip(),
        }
        locked_scan.selected_household_uid = ""
        locked_scan.selected_household_name_snapshot = POSTAL_SCAN_UNKNOWN_PAYMENT_LABEL
        locked_scan.payment = None
        locked_scan.confirmed_by = actor_label
        locked_scan.confirmed_at = timezone.now()
        locked_scan.status = AnnualMembershipFeePostalScan.Status.CHECKED
        locked_scan.move_error = ""
        locked_scan.candidate_payload = payload
        locked_scan.save(
            update_fields=[
                "selected_household_uid",
                "selected_household_name_snapshot",
                "payment",
                "confirmed_by",
                "confirmed_at",
                "status",
                "move_error",
                "candidate_payload",
                "updated_at",
            ]
        )
        if old_payment is not None:
            old_payment.delete()
        scan = locked_scan

    return PostalScanPaymentSaveResult(success=True, scan=scan, was_checked=was_checked)


__all__ = [
    "POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE",
    "POSTAL_SCAN_PAYMENT_NOTE",
    "POSTAL_SCAN_UNKNOWN_PAYMENT_LABEL",
    "PostalScanPaymentSaveResult",
    "active_canonical_households",
    "append_postal_scan_revision",
    "postal_scan_receipt_policy",
    "save_postal_scan_payment",
    "save_postal_scan_unknown_payment",
]
