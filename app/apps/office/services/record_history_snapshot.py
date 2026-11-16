from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from apps.imports.models import (
    Household,
    HouseholdHeadResolutionError,
    HouseholdProfile,
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
)

from .household_editing_core import (
    _household_display_head_name,
    _household_display_head_name_kana,
)


def _safe_household_display_head_name(household: Household | None) -> str:
    if household is None:
        return ""
    try:
        return _household_display_head_name(household)
    except HouseholdHeadResolutionError:
        return (household.snapshot_head_name() or household.household_uid or "").strip()


def _safe_household_display_head_name_kana(household: Household | None) -> str:
    if household is None:
        return ""
    try:
        return _household_display_head_name_kana(household)
    except HouseholdHeadResolutionError:
        return (household.snapshot_head_name_kana() or "").strip()


def _serialize_household_record(household: Household) -> dict:
    from .household_profile_editing import _resolved_household_head_gender

    source_id = household.legacy_source_id or (
        household.batch.source.source_id if getattr(household, "batch_id", None) and household.batch_id else ""
    )
    profile = None
    if source_id and household.household_uid:
        profile = (
            HouseholdProfile.objects.select_related("district")
            .filter(source__source_id=source_id, household_uid=household.household_uid)
            .first()
        )
    return _normalize_snapshot_value(
        {
            "id": household.id,
            "legacy_source_id": household.legacy_source_id,
            "legacy_household_id": household.household_uid,
            "head_person_id": household.head_person_id,
            "head_name": _safe_household_display_head_name(household),
            "head_name_kana": _safe_household_display_head_name_kana(household),
            "resolved_head_name": _safe_household_display_head_name(household),
            "resolved_head_name_kana": _safe_household_display_head_name_kana(household),
            "head_gender": _resolved_household_head_gender(household),
            "postal_code": household.postal_code,
            "address_line1": household.address_line1,
            "address_line2": household.address_line2,
            "address_line3": household.address_line3,
            "phone": household.phone,
            "fax": household.fax,
            "mobile": household.mobile,
            "email": household.email,
            "steward_legacy_id": household.steward_legacy_id,
            "ledger_category": household.ledger_category,
            "notes": household.notes,
            "source_table": household.source_table,
            "source_row_number": household.source_row_number,
            "source_export_batch": household.source_export_batch,
            "legacy_pk_text": household.legacy_pk_text,
            "deleted_at": household.deleted_at,
            "deleted_by": household.deleted_by,
            "deletion_note": household.deletion_note,
            "household_profile": {
                "delivery_method": profile.delivery_method if profile is not None else "",
                "general_notice_opt_out": (
                    profile.general_notice_opt_out if profile is not None else None
                ),
                "memorial_notice_opt_out": (
                    profile.memorial_notice_opt_out if profile is not None else None
                ),
                "district_id": profile.district_id if profile is not None else None,
                "district_name": profile.district.name if profile is not None and profile.district_id else "",
                "mailing_person_legacy_person_id": (
                    profile.mailing_person_uid if profile is not None else ""
                ),
                "mailing_name": profile.mailing_name if profile is not None else "",
                "mailing_postal_code": profile.mailing_postal_code if profile is not None else "",
                "mailing_address_line1": profile.mailing_address_line1 if profile is not None else "",
                "mailing_address_line2": profile.mailing_address_line2 if profile is not None else "",
                "mailing_phone": profile.mailing_phone if profile is not None else "",
            },
            "raw_record": household.raw_record,
        }
    )


def _serialize_person_record(
    person: Person, *, include_district_officer_context: bool = False,
) -> dict:
    snapshot = _normalize_snapshot_value(
        {
            "id": person.id,
            "legacy_source_id": person.legacy_source_id,
            "legacy_household_id": person.household.household_uid,
            "legacy_person_id": person.person_uid,
            "household_name": _safe_household_display_head_name(person.household) if person.household_id else "",
            "name": person.name,
            "kana": person.kana,
            "relationship_label": person.relationship_label,
            "family_category": person.family_category,
            "gender": person.gender,
            "is_district_officer": person.is_district_officer,
            "is_responsible_officer": person.is_responsible_officer,
            "is_monto_sodai": person.is_monto_sodai,
            "birth_date": person.birth_date,
            "birth_date_raw": person.birth_date_raw,
            "birth_date_parse_error": person.birth_date_parse_error,
            "person_note": person.person_note,
            "is_deceased": person.is_deceased,
            "source_table": person.source_table,
            "source_row_number": person.source_row_number,
            "source_export_batch": person.source_export_batch,
            "legacy_pk_text": person.legacy_pk_text,
            "deleted_at": person.deleted_at,
            "deleted_by": person.deleted_by,
            "deletion_note": person.deletion_note,
            "raw_record": person.raw_record,
            "deceased_profile": (
                {
                    "death_date": person.death_date,
                    "death_date_raw": person.death_date_raw,
                    "death_date_parse_error": person.death_date_parse_error,
                    "kaimyo": person.kaimyo,
                    "kaimyo_kana": person.kaimyo_kana,
                    "age_at_death": person.age_at_death,
                    "age_at_death_raw": person.age_at_death_raw,
                    "age_unit": person.age_unit,
                    "hatsubon_flag": person.hatsubon_flag,
                    "legacy_hatsubon_flag": person.legacy_hatsubon_flag,
                    "memorial_notice_opt_out": person.memorial_notice_opt_out,
                    "deceased_note": person.deceased_note,
                    "memorial_payload": person.memorial_payload,
                }
                if person.has_memorial_details() or person.is_deceased
                else None
            ),
        }
    )
    if include_district_officer_context:
        source_id = person.legacy_source_id or person.batch.source.source_id
        profile = (
            HouseholdProfile.objects.select_related("district")
            .filter(source__source_id=source_id, household_uid=person.household.household_uid)
            .first()
        )
        snapshot["district_officer_context"] = {
            "district_id": profile.district_id if profile is not None else None,
            "district_name": profile.district.name if profile is not None and profile.district_id else "",
        }
    return snapshot


def _serialize_service_schedule_record(schedule: ServiceSchedule) -> dict:
    return _normalize_snapshot_value(
        {
            "id": schedule.id,
            "household_id": schedule.household_id,
            "person_id": schedule.person_id,
            "legacy_source_id": schedule.legacy_source_id,
            "legacy_household_id": schedule.household_uid,
            "legacy_person_id": schedule.person_uid,
            "legacy_schedule_id": schedule.schedule_uid,
            "legacy_schedule_type_id": schedule.legacy_schedule_type_id,
            "household_name_snapshot": schedule.household_name_snapshot,
            "person_name_snapshot": schedule.person_name_snapshot,
            "record_origin": schedule.record_origin,
            "event_scope": schedule.event_scope,
            "category": schedule.category,
            "service_label": schedule.service_label,
            "subject_name": schedule.subject_name,
            "link_group_key": schedule.link_group_key,
            "target_date": schedule.target_date,
            "scheduled_date": schedule.scheduled_date,
            "scheduled_time": schedule.scheduled_time,
            "completed_on": schedule.completed_on,
            "location": schedule.location,
            "status": schedule.status,
            "notes": schedule.notes,
            "external_calendar_ref": schedule.external_calendar_ref,
            "source_table": schedule.source_table,
            "source_row_number": schedule.source_row_number,
            "source_export_batch": schedule.source_export_batch,
            "legacy_pk_text": schedule.legacy_pk_text,
            "deleted_at": schedule.deleted_at,
            "deleted_by": schedule.deleted_by,
            "deletion_note": schedule.deletion_note,
            "raw_record": schedule.raw_record,
        }
    )


def _serialize_offering_payment_record(payment: OfferingPayment) -> dict:
    schedule = payment.service_schedule if payment.service_schedule_id else None
    return _normalize_snapshot_value(
        {
            "id": payment.id,
            "household_id": payment.household_id,
            "person_id": payment.person_id,
            "legacy_source_id": payment.legacy_source_id,
            "legacy_household_id": payment.household_uid,
            "legacy_person_id": payment.person_uid,
            "legacy_schedule_id": schedule.schedule_uid if schedule is not None else "",
            "household_name_snapshot": payment.household_name_snapshot,
            "person_name_snapshot": payment.person_name_snapshot,
            "service_schedule_id": payment.service_schedule_id,
            "service_event_scope": schedule.event_scope if schedule is not None else "",
            "service_label": (
                schedule.service_label
                if schedule is not None and schedule.event_scope == ServiceSchedule.EventScope.TEMPLE
                else ""
            ),
            "service_source_table": schedule.source_table if schedule is not None else "",
            "received_on": payment.received_on,
            "amount": payment.amount,
            "payment_category": payment.payment_category,
            "payment_method": payment.payment_method,
            "received_by": payment.received_by,
            "payer_name": payment.payer_name,
            "notes": payment.notes,
        }
    )


def _normalize_snapshot_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize_snapshot_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_snapshot_value(inner) for inner in value]
    return value


def _history_log_event_scope(log: RecordEditLog) -> str:
    """Only an explicit snapshot marker identifies the new temple-event scope."""
    if log.record_type not in {
        RecordEditLog.RecordType.SERVICE_SCHEDULE,
        RecordEditLog.RecordType.OFFERING_PAYMENT,
    }:
        return ServiceSchedule.EventScope.HOUSEHOLD
    field = (
        "service_event_scope"
        if log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT
        else "event_scope"
    )
    for snapshot in (log.after_data, log.before_data):
        if field in snapshot:
            return snapshot[field] or ServiceSchedule.EventScope.HOUSEHOLD
    return ServiceSchedule.EventScope.HOUSEHOLD


def _changed_snapshot_fields(before_data: dict, after_data: dict, prefix: str = "") -> list[str]:
    changed_fields: list[str] = []
    keys = sorted(set(before_data.keys()) | set(after_data.keys()))
    for key in keys:
        field_path = f"{prefix}.{key}" if prefix else key
        before_value = before_data.get(key)
        after_value = after_data.get(key)
        if isinstance(before_value, dict) or isinstance(after_value, dict):
            nested_before = before_value if isinstance(before_value, dict) else {}
            nested_after = after_value if isinstance(after_value, dict) else {}
            nested_changes = _changed_snapshot_fields(nested_before, nested_after, field_path)
            if nested_changes:
                changed_fields.extend(nested_changes)
            elif before_value != after_value:
                changed_fields.append(field_path)
            continue
        if before_value != after_value:
            changed_fields.append(field_path)
    return changed_fields


def _infer_record_edit_action_kind(before_data: dict, after_data: dict) -> str:
    before_deleted = bool(before_data.get("deleted_at"))
    after_deleted = bool(after_data.get("deleted_at"))
    if not before_deleted and after_deleted:
        return RecordEditLog.ActionKind.DELETE
    if before_deleted and not after_deleted:
        return RecordEditLog.ActionKind.RESTORE
    return RecordEditLog.ActionKind.UPDATE


def _write_record_field_changes(
    *,
    log_entry: RecordEditLog,
    before_data: dict,
    after_data: dict,
    changed_fields: list[str],
) -> None:
    from apps.imports.models import RecordFieldChange

    for sort_order, field_path in enumerate(changed_fields):
        RecordFieldChange.objects.update_or_create(
            record_edit_log=log_entry,
            field_path=field_path,
            defaults={
                "before_value": _snapshot_value(before_data, field_path),
                "after_value": _snapshot_value(after_data, field_path),
                "sort_order": sort_order,
            },
        )


def _record_label(record: Household | Person | ServiceSchedule | OfferingPayment) -> str:
    if isinstance(record, Household):
        return _household_display_head_name(record)
    if isinstance(record, Person):
        return record.name or record.person_uid
    if isinstance(record, OfferingPayment):
        category_label = record.get_payment_category_display() or "入金"
        amount_label = f"{record.amount}円" if record.amount is not None else "金額未設定"
        if record.service_schedule_id and (
            record.service_schedule.event_scope == ServiceSchedule.EventScope.TEMPLE
        ):
            donor = (record.payer_name or "").strip() or (
                record.household_name_snapshot or ""
            ).strip() or "匿名"
            return f"{donor} {category_label} {amount_label} / {record.service_schedule.service_label}"
        person_name = (record.person_name_snapshot or "").strip()
        household_name = (record.household_name_snapshot or "").strip()
        if person_name and household_name and household_name != person_name:
            return f"{person_name}（{household_name}） {category_label} {amount_label}"
        if person_name:
            return f"{person_name} {category_label} {amount_label}"
        if household_name:
            return f"{household_name} {category_label} {amount_label}"
        return f"{category_label} {amount_label}"
    return record.service_label or record.schedule_uid


def _deleted_meta(record: Household | Person | ServiceSchedule | OfferingPayment) -> dict:
    return {
        "deleted_at": getattr(record, "deleted_at", None),
        "deleted_by": getattr(record, "deleted_by", ""),
        "deletion_note": getattr(record, "deletion_note", ""),
    }


def _snapshot_value(snapshot: dict, path: str):
    current = snapshot
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _format_history_value(value) -> str:
    import json

    normalized = _normalize_snapshot_value(value)
    if normalized in (None, "", []):
        return "未入力"
    if isinstance(normalized, bool):
        return "はい" if normalized else "いいえ"
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, ensure_ascii=False)
    return str(normalized)
