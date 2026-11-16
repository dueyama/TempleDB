from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Model

from apps.imports.models import Household, OfferingPayment, Person, RecordEditLog, ServiceSchedule

from .district_officer_rules import (
    district_profile_for_person,
    reconcile_restored_district_officer,
)
from .record_history_snapshot import (
    _changed_snapshot_fields,
    _infer_record_edit_action_kind,
    _normalize_snapshot_value,
    _record_label,
    _write_record_field_changes,
)


@dataclass(frozen=True)
class RecordDeleteOutcome:
    refreshed_record: Household | Person | ServiceSchedule | OfferingPayment
    log_entry: RecordEditLog | None
    user_message: str


@transaction.atomic
def _create_record_edit_log(
    *,
    record_type: str,
    record: Model,
    before_data: dict,
    after_data: dict,
    editor_label: str,
    change_note: str,
    action_kind: str | None = None,
    source_id: str | None = None,
    household_uid: str | None = None,
    record_label: str | None = None,
) -> RecordEditLog | None:
    before_data = _normalize_snapshot_value(before_data)
    after_data = _normalize_snapshot_value(after_data)
    changed_fields = _changed_snapshot_fields(before_data, after_data)
    if not changed_fields:
        return None
    record_id = getattr(record, "pk", None) or before_data.get("id") or after_data.get("id")
    log_entry = RecordEditLog.objects.create(
        record_type=record_type,
        action_kind=action_kind or _infer_record_edit_action_kind(before_data, after_data),
        record_id=record_id,
        legacy_source_id=(
            source_id if source_id is not None else getattr(record, "legacy_source_id", "")
        ),
        legacy_household_id=household_uid if household_uid is not None else getattr(
            record,
            "household_uid",
            getattr(record, "legacy_household_id", ""),
        ),
        legacy_person_id=(
            record.person_uid
            if isinstance(record, Person)
            else getattr(record, "person_uid", "")
        ),
        legacy_schedule_id=(
            record.schedule_uid
            if isinstance(record, ServiceSchedule)
            else getattr(getattr(record, "service_schedule", None), "schedule_uid", "")
        ),
        record_label=record_label if record_label is not None else _record_label(record),
        changed_fields=changed_fields,
        before_data=before_data,
        after_data=after_data,
        editor_label=(editor_label or "").strip(),
        change_note=(change_note or "").strip(),
    )
    _write_record_field_changes(
        log_entry=log_entry,
        before_data=before_data,
        after_data=after_data,
        changed_fields=changed_fields,
    )
    return log_entry


def perform_record_delete_action(
    *,
    action: str,
    record_type: str,
    record: Household | Person | ServiceSchedule | OfferingPayment,
    serializer,
    refresh,
    editor_label: str,
    change_note: str,
    deleted_message: str,
    restored_message: str,
) -> RecordDeleteOutcome | None:
    if action not in {"delete", "restore"}:
        return None

    restore_note = ""
    with transaction.atomic():
        if isinstance(record, Person):
            if action == "restore":
                # Match delivery edits: Household first, then fresh Person/profile and District.
                Household.objects.select_for_update(of=("self",)).get(pk=record.household_id)
            record.refresh_from_db()
        before_data = serializer(record)
        district_context = None
        if isinstance(record, Person):
            profile = district_profile_for_person(record.batch.source.source_id, record)
            district = profile.district if profile is not None else None
            district_context = {
                "district_id": district.pk if district is not None else None,
                "district_name": district.name if district is not None else "",
            }
            before_data["district_officer_context"] = district_context
        if action == "delete":
            record.mark_deleted(editor_label=editor_label, note=change_note)
        else:
            was_deleted = record.deleted_at is not None
            record.restore_deleted()
            if was_deleted and isinstance(record, Person):
                restore_note = reconcile_restored_district_officer(record)
        record.save()
        refreshed = refresh(record.pk)
        after_data = serializer(refreshed)
        if district_context is not None:
            after_data["district_officer_context"] = district_context
        log_entry = _create_record_edit_log(
            record_type=record_type,
            record=refreshed,
            before_data=before_data,
            after_data=after_data,
            editor_label=editor_label,
            change_note=" ".join(part for part in (change_note, restore_note) if part),
            action_kind=(
                RecordEditLog.ActionKind.DELETE
                if action == "delete"
                else RecordEditLog.ActionKind.RESTORE
            ),
        )

    message_text = deleted_message if action == "delete" else restored_message
    if restore_note:
        message_text = f"{message_text} {restore_note}"
    return RecordDeleteOutcome(
        refreshed_record=refreshed,
        log_entry=log_entry,
        user_message=record_action_message_text(log_entry, message_text),
    )


def record_action_message_text(
    log_entry: RecordEditLog | None,
    message_text: str,
) -> str:
    if log_entry is None:
        return "変更内容はありませんでした。"
    return f"{message_text} 履歴 {log_entry.created_at:%Y-%m-%d %H:%M:%S} を記録しました。"
