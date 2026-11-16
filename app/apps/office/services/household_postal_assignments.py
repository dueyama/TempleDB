from __future__ import annotations

from django.db import transaction

from apps.imports.ledger_categories import normalize_ledger_category_code
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_POSTAL,
    Household,
    HouseholdProfile,
    LegacySource,
    RecordEditLog,
)

from .household_profile_editing import _apply_household_delivery_profile_from_form
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_household_record, _serialize_person_record

POSTAL_CONTACT_FIELDS = ("postal_code", "address_line1", "address_line2", "phone")


@transaction.atomic
def apply_household_postal_assignment(
    *,
    household: Household,
    source_record: LegacySource,
    contact_values: dict[str, str],
    ledger_category: str = "",
    raw_record_updates: dict[str, str] | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> bool:
    """Save contacts, postal delivery and their audit; preserve notice/recipient settings."""
    household = Household.objects.select_for_update(of=("self",)).select_related("batch__source", "head_person").get(
        pk=household.pk,
    )
    before_data = _serialize_household_record(household)
    editor_label = (editor_label or "").strip() or "system"
    change_note = (change_note or "").strip() or "郵送名簿から住所・送付区分を更新"
    update_fields = []
    for field in POSTAL_CONTACT_FIELDS:
        value = contact_values.get(field, "")
        if value and getattr(household, field) != value:
            setattr(household, field, value)
            update_fields.append(field)
    contacts_changed = bool(update_fields)
    if ledger_category and normalize_ledger_category_code(household.ledger_category) != ledger_category:
        household.ledger_category = ledger_category
        update_fields.append("ledger_category")
    raw_record = {**(household.raw_record or {}), **(raw_record_updates or {})}
    if raw_record != household.raw_record:
        household.raw_record = raw_record
        update_fields.append("raw_record")
    if update_fields:
        household.save(update_fields=[*update_fields, "updated_at"])

    profile = HouseholdProfile.objects.select_for_update().filter(
        source=source_record, household_uid=household.household_uid,
    ).first()
    _apply_household_delivery_profile_from_form(
        source_record=source_record,
        household=household,
        delivery_method=HOUSEHOLD_DELIVERY_POSTAL,
        district_id="",
        general_notice_opt_out=profile.general_notice_opt_out if profile is not None else None,
        memorial_notice_opt_out=profile.memorial_notice_opt_out if profile is not None else None,
        editor_label=editor_label,
        change_note=change_note,
    )
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD,
        record=household,
        source_id=source_record.source_id,
        before_data=before_data,
        after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note=change_note,
    )
    return contacts_changed


@transaction.atomic
def record_postal_household_creation(
    *,
    household: Household,
    source_record: LegacySource,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    """Record the initialized household and its head in the caller's creation transaction."""
    editor_label = (editor_label or "").strip() or "system"
    change_note = (change_note or "").strip() or "郵送名簿から新しい家を作成"
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD,
        record=household,
        source_id=source_record.source_id,
        before_data={},
        after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note=change_note,
    )
    head_person = household.require_head_person()
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=head_person,
        source_id=source_record.source_id,
        before_data={},
        after_data=_serialize_person_record(head_person),
        editor_label=editor_label,
        change_note=f"{change_note}（戸主 person を作成）",
    )
