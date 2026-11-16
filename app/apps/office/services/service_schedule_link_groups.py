from __future__ import annotations

from apps.imports import service_ledger_runtime
from apps.imports.models import RecordEditLog, ServiceSchedule

from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_service_schedule_record
from .service_schedule_core import _service_schedule_for_edit

LINKED_GROUP_SHARED_FIELDS = [
    "scheduled_date",
    "scheduled_time",
    "completed_on",
    "location",
    "status",
    "notes",
    "external_calendar_ref",
]


def _linked_service_schedule_members(schedule: ServiceSchedule) -> list[dict]:
    if not schedule.link_group_key:
        return []
    related = ServiceSchedule.objects.filter(
        link_group_key=schedule.link_group_key,
        deleted_at__isnull=True,
    ).select_related("person", "person__deceased_profile")
    members = []
    for item in related.order_by("scheduled_date", "target_date", "person_uid", "id"):
        resolved_target_date = service_ledger_runtime._actual_service_schedule_death_date(item)
        members.append(
            {
                "schedule_pk": item.pk,
                "person_name": item.subject_name or item.person_name_snapshot or item.person_uid,
                "service_label": item.service_label,
                "target_date": resolved_target_date.isoformat() if resolved_target_date else "",
                "scheduled_date": item.scheduled_date.isoformat() if item.scheduled_date else "",
                "status_label": service_ledger_runtime._effective_service_schedule_status_label(item),
                "is_current": item.pk == schedule.pk,
            }
        )
    return members


def _linked_service_schedule_choices(schedule: ServiceSchedule) -> tuple[list[tuple[str, str]], list[str]]:
    members = _linked_service_schedule_members(schedule)
    choices: list[tuple[str, str]] = []
    initial: list[str] = []
    for item in members:
        if item["is_current"]:
            continue
        label = (
            f"{item['person_name']} / {item['service_label']}"
            + (f" / 基準日 {item['target_date']}" if item["target_date"] else "")
            + (f" / 予定 {item['scheduled_date']}" if item["scheduled_date"] else "")
            + f" / {item['status_label']}"
        )
        schedule_pk = str(item["schedule_pk"])
        choices.append((schedule_pk, label))
        initial.append(schedule_pk)
    return choices, initial


def _apply_linked_group_updates(
    schedule: ServiceSchedule,
    *,
    apply_updates: bool,
    editor_label: str,
    change_note: str,
) -> list[RecordEditLog]:
    if not apply_updates or not schedule.link_group_key:
        return []
    logs: list[RecordEditLog] = []
    siblings = ServiceSchedule.objects.filter(
        link_group_key=schedule.link_group_key,
        deleted_at__isnull=True,
    ).exclude(pk=schedule.pk)
    for sibling in siblings:
        before_data = _serialize_service_schedule_record(sibling)
        for field_name in LINKED_GROUP_SHARED_FIELDS:
            setattr(sibling, field_name, getattr(schedule, field_name))
        sibling.save(update_fields=[*LINKED_GROUP_SHARED_FIELDS, "updated_at"])
        sibling = _service_schedule_for_edit(sibling.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=sibling,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(sibling),
            editor_label=editor_label,
            change_note=change_note,
            action_kind=RecordEditLog.ActionKind.LINK_UPDATE,
        )
        if log_entry is not None:
            logs.append(log_entry)
    return logs
