from __future__ import annotations

from apps.imports.models import AnnualMembershipFeePayment, AnnualMembershipFeeSetting


def serialize_annual_membership_fee_payment(
    payment: AnnualMembershipFeePayment | None,
) -> dict:
    if payment is None:
        return {}
    return {
        "id": payment.pk,
        "source_id": payment.source.source_id,
        "household_uid": payment.household_uid,
        "household_name_snapshot": payment.household_name_snapshot,
        "delivery_method_snapshot": payment.delivery_method_snapshot,
        "district_name_snapshot": payment.district_name_snapshot,
        "year": payment.year,
        "received_on": payment.received_on,
        "amount": payment.amount,
        "is_exception": payment.is_exception,
        "received_by": payment.received_by,
        "note": payment.note,
    }


def serialize_annual_membership_fee_setting(
    setting: AnnualMembershipFeeSetting | None,
) -> dict:
    if setting is None:
        return {}
    return {
        "id": setting.pk,
        "source_id": setting.source.source_id,
        "year": setting.year,
        "default_amount": setting.default_amount,
        "note": setting.note,
    }
