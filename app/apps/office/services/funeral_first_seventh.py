"""Create and synchronize the funeral and its linked first-seventh observance."""

from uuid import uuid4

from django.db import transaction
from django.db.models import Q

from apps.imports.models import RecordEditLog, ServiceSchedule
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_service_schedule_record
from apps.office.services.service_schedule_core import (
    _new_manual_service_schedule,
    _normalize_service_schedule_target_date,
    _persist_manual_service_schedule_identity,
)


def existing_first_seventh(funeral):
    return (
        ServiceSchedule.objects.filter(
            person_id=funeral.person_id,
            household_id=funeral.household_id,
            service_label="初七日",
            deleted_at__isnull=True,
        )
        .exclude(pk=funeral.pk)
        .first()
    )


@transaction.atomic
def add_first_seventh(funeral, *, editor_label):
    # Serialize repeated submissions for this funeral before testing uniqueness.
    ServiceSchedule.objects.select_for_update().get(pk=funeral.pk)
    if funeral.category != ServiceSchedule.Category.FUNERAL or not funeral.person_id:
        raise ValueError("故人に関連付けた葬儀だけが対象です。")
    existing = existing_first_seventh(funeral)
    if existing:
        return None
    record = _new_manual_service_schedule(
        funeral.related_batch or funeral.person.batch, funeral.person
    )
    record.category = ServiceSchedule.Category.CHUIN
    record.service_label = "初七日"
    for field in ("scheduled_date", "scheduled_time", "location", "status", "completed_on"):
        setattr(record, field, getattr(funeral, field))
    record.notes = "葬儀と一緒に勤める"
    _normalize_service_schedule_target_date(record)
    record.save()
    _persist_manual_service_schedule_identity(record)
    link_funeral_first_seventh(funeral, record, editor_label=editor_label)
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=record,
        before_data={},
        after_data=_serialize_service_schedule_record(record),
        editor_label=editor_label,
        change_note="葬儀の編集から初七日を同日記録",
    )
    return record


@transaction.atomic
def link_funeral_first_seventh(funeral, first, *, editor_label):
    """Use the normal linked-service group, preserving the existing records."""
    records = list(
        ServiceSchedule.objects.select_for_update()
        .filter(pk__in=[funeral.pk, first.pk])
        .order_by("pk")
    )
    current = {record.pk: record for record in records}
    funeral_record, first_record = current[funeral.pk], current[first.pk]
    if (
        funeral_record.category != ServiceSchedule.Category.FUNERAL
        or first_record.service_label != "初七日"
    ):
        raise ValueError("葬儀と初七日の組合せが必要です。")
    if not funeral_record.person_id or any(
        getattr(funeral_record, field) != getattr(first_record, field)
        for field in (
            "person_id",
            "household_id",
            "scheduled_date",
            "scheduled_time",
            "location",
            "status",
        )
    ):
        raise ValueError("同じ故人・日時・場所・状態の予定だけをまとめられます。")
    groups = {record.link_group_key for record in records if record.link_group_key}
    if len(groups) > 1:
        raise ValueError("別々のリンクグループは自動統合しません。")
    key = next(iter(groups), f"slg-{uuid4().hex[:12]}")
    old_keys = [f"schedule:{record.pk}" for record in records if not record.link_group_key]
    for record in records:
        if record.link_group_key == key:
            continue
        before = _serialize_service_schedule_record(record)
        record.link_group_key = key
        record.save(update_fields=["link_group_key", "updated_at"])
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=record,
            before_data=before,
            after_data=_serialize_service_schedule_record(record),
            editor_label=editor_label,
            change_note="葬儀と同日初七日を併修グループへまとめる",
            action_kind=RecordEditLog.ActionKind.LINK_UPDATE,
        )
    funeral.link_group_key = first.link_group_key = key
    return [*old_keys, f"link:{key}"]


def _linked_funeral_observances(schedule):
    if (
        not schedule.person_id
        or not schedule.household_id
        or not schedule.link_group_key
        or schedule.deleted_at is not None
    ):
        return ServiceSchedule.objects.none()
    if schedule.category == ServiceSchedule.Category.FUNERAL:
        counterpart = Q(category=ServiceSchedule.Category.CHUIN, service_label="初七日")
    elif (
        schedule.category == ServiceSchedule.Category.CHUIN
        and schedule.service_label == "初七日"
    ):
        counterpart = Q(category=ServiceSchedule.Category.FUNERAL)
    else:
        return ServiceSchedule.objects.none()
    return ServiceSchedule.objects.filter(
        counterpart,
        link_group_key=schedule.link_group_key,
        person_id=schedule.person_id,
        household_id=schedule.household_id,
        deleted_at__isnull=True,
    ).exclude(pk=schedule.pk)


def lock_linked_funeral_observances(schedule):
    """Lock both sides in the same order before either edited row is saved."""
    counterpart_ids = _linked_funeral_observances(schedule).values("pk")
    if not counterpart_ids.exists():
        return []
    # The caller owns the transaction containing the edited row and its payments.
    return list(
        ServiceSchedule.objects.select_for_update()
        .filter(Q(pk=schedule.pk) | Q(pk__in=counterpart_ids))
        .order_by("pk")
    )


@transaction.atomic
def sync_linked_funeral_observances(schedule, *, before_data, editor_label):
    """Share explicit edits in either direction; keep each observance's notes."""
    shared_fields = ("scheduled_date", "scheduled_time", "location", "status", "completed_on")
    after_data = _serialize_service_schedule_record(schedule)
    fields = {field for field in shared_fields if before_data.get(field) != after_data.get(field)}
    if not fields:
        return []
    # Status and completion date describe one decision and must travel together.
    if fields.intersection({"status", "completed_on"}):
        fields.update({"status", "completed_on"})
    logs = []
    for record in _linked_funeral_observances(schedule).select_for_update().order_by("pk"):
        changed_fields = [
            field for field in shared_fields
            if field in fields and getattr(record, field) != getattr(schedule, field)
        ]
        if not changed_fields:
            continue
        before = _serialize_service_schedule_record(record)
        for field in changed_fields:
            setattr(record, field, getattr(schedule, field))
        record.save(update_fields=[*changed_fields, "updated_at"])
        log = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=record,
            before_data=before,
            after_data=_serialize_service_schedule_record(record),
            editor_label=editor_label,
            change_note="葬儀・初七日の併修で変更した日時・場所・完了状態を反映",
            action_kind=RecordEditLog.ActionKind.LINK_UPDATE,
        )
        if log:
            logs.append(log)
    return logs
