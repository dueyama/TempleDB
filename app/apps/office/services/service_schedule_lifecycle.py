from __future__ import annotations

from datetime import date, time

from apps.imports import service_ledger_runtime
from apps.imports.models import (
    Household,
    ImportBatch,
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
)

from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_service_schedule_record
from .service_schedule_core import (
    _new_manual_service_schedule,
    _persist_manual_service_schedule_identity,
    _service_schedule_for_edit,
)


def _refresh_manual_service_schedule_household_snapshots(
    *,
    household: Household,
    previous_household_name: str,
    editor_label: str,
    change_note: str,
) -> None:
    previous_name = (previous_household_name or "").strip()
    current_name = (household.snapshot_head_name() or "").strip()
    if not previous_name or not current_name or previous_name == current_name:
        return
    schedules = (
        ServiceSchedule.objects.filter(
            household=household,
            deleted_at__isnull=True,
            source_table="manual_service_schedule",
            household_name_snapshot=previous_name,
        )
        .select_related("person", "household")
        .order_by("id")
    )
    for schedule in schedules:
        before_data = _serialize_service_schedule_record(schedule)
        schedule.household_name_snapshot = current_name
        schedule.save(update_fields=["household_name_snapshot", "updated_at"])
        schedule = _service_schedule_for_edit(schedule.pk)
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=schedule,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(schedule),
            editor_label=editor_label,
            change_note=f"{change_note}（戸主名 snapshot 更新）",
        )


def _refresh_offering_payment_household_snapshots(
    *,
    household: Household,
    previous_household_name: str,
) -> None:
    previous_name = (previous_household_name or "").strip()
    current_name = (household.snapshot_head_name() or "").strip()
    if not previous_name or not current_name or previous_name == current_name:
        return
    payments = OfferingPayment.objects.filter(
        household=household,
        household_name_snapshot=previous_name,
    ).order_by("id")
    for payment in payments:
        payment.household_name_snapshot = current_name
        payment.save(update_fields=["household_name_snapshot", "updated_at"])


def _is_manual_service_schedule(schedule: ServiceSchedule) -> bool:
    return (
        schedule.record_origin == ServiceSchedule.Origin.MANUAL
        and schedule.source_table == "manual_service_schedule"
    )


def _manual_service_schedule_has_blocking_relations(schedule: ServiceSchedule) -> bool:
    return schedule.offering_payments.exists() or schedule.visit_notes.exists()


def _matching_active_schedule_for_candidate(
    schedule: ServiceSchedule,
    *,
    exclude_pks: set[int] | None = None,
) -> ServiceSchedule | None:
    excluded_schedule_pks = {schedule.pk}
    if exclude_pks:
        excluded_schedule_pks.update(int(value) for value in exclude_pks if value)
    candidate_target_date = service_ledger_runtime._resolved_service_schedule_target_date(schedule)
    candidate = {
        "person_id": schedule.person_uid,
        "label": schedule.service_label,
        "target_date": candidate_target_date.isoformat() if candidate_target_date else "",
    }
    relation_filters: dict[str, object]
    if schedule.person_id:
        relation_filters = {
            "household_id": schedule.household_id,
            "person_id": schedule.person_id,
        }
    else:
        relation_filters = {
            "legacy_source_id": schedule.legacy_source_id,
            "household_uid": schedule.household_uid,
            "person_uid": schedule.person_uid,
        }
    schedules = list(
        ServiceSchedule.objects.filter(
            **relation_filters,
            record_origin=ServiceSchedule.Origin.MANUAL,
            source_table="manual_service_schedule",
            deleted_at__isnull=True,
        )
        .exclude(pk__in=sorted(excluded_schedule_pks))
        .select_related("person", "person__deceased_profile")
        .order_by("id")
    )
    return service_ledger_runtime._matching_actual_schedule_for_candidate(candidate, schedules)


def _soft_delete_service_schedule(
    schedule: ServiceSchedule,
    *,
    editor_label: str,
    change_note: str,
    action_kind: str = RecordEditLog.ActionKind.DELETE,
) -> tuple[ServiceSchedule, RecordEditLog | None]:
    before_data = _serialize_service_schedule_record(schedule)
    schedule.mark_deleted(editor_label=editor_label, note=change_note)
    schedule.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "deletion_note",
            "updated_at",
        ]
    )
    refreshed = _service_schedule_for_edit(schedule.pk)
    log_entry = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=refreshed,
        before_data=before_data,
        after_data=_serialize_service_schedule_record(refreshed),
        editor_label=editor_label,
        change_note=change_note,
        action_kind=action_kind,
    )
    return refreshed, log_entry


def _sync_linked_service_schedule_members(
    schedule: ServiceSchedule,
    *,
    selected_linked_schedule_ids: list[str],
    reset_unlinked_schedules: bool,
    editor_label: str,
    change_note: str,
) -> tuple[ServiceSchedule, list[RecordEditLog]]:
    if not schedule.link_group_key:
        return schedule, []
    # Unlinked schedules should not remain as active memorial services on their own.
    # Keep the argument for call-site compatibility, but always reset planning state.
    reset_unlinked_schedules = True
    siblings = list(
        ServiceSchedule.objects.filter(
            link_group_key=schedule.link_group_key,
            deleted_at__isnull=True,
        )
        .exclude(pk=schedule.pk)
        .order_by("id")
    )
    selected_ids = {int(value) for value in selected_linked_schedule_ids if str(value).isdigit()}
    logs: list[RecordEditLog] = []
    kept_any = False
    for item in siblings:
        if item.pk in selected_ids:
            kept_any = True
            continue
        if _is_manual_service_schedule(item) and not _manual_service_schedule_has_blocking_relations(item):
            _refreshed, log_entry = _soft_delete_service_schedule(
                item,
                editor_label=editor_label,
                change_note=change_note,
                action_kind=RecordEditLog.ActionKind.DELETE,
            )
            if log_entry is not None:
                logs.append(log_entry)
            continue
        before_data = _serialize_service_schedule_record(item)
        item.link_group_key = ""
        update_fields = ["link_group_key", "updated_at"]
        if reset_unlinked_schedules and not _is_manual_service_schedule(item):
            _reset_service_schedule_planning_fields(item)
            update_fields.extend(
                [
                    "scheduled_date",
                    "scheduled_time",
                    "completed_on",
                    "location",
                    "status",
                    "external_calendar_ref",
                ]
            )
        item.save(update_fields=update_fields)
        refreshed = _service_schedule_for_edit(item.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=refreshed,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(refreshed),
            editor_label=editor_label,
            change_note=change_note,
            action_kind=RecordEditLog.ActionKind.LINK_UPDATE,
        )
        if log_entry is not None:
            logs.append(log_entry)
    if not kept_any and siblings:
        duplicate_schedule = _matching_active_schedule_for_candidate(schedule)
        if (
            duplicate_schedule is not None
            and _is_manual_service_schedule(schedule)
            and not _manual_service_schedule_has_blocking_relations(schedule)
        ):
            schedule, log_entry = _soft_delete_service_schedule(
                schedule,
                editor_label=editor_label,
                change_note=change_note,
                action_kind=RecordEditLog.ActionKind.DELETE,
            )
            if log_entry is not None:
                logs.append(log_entry)
            return schedule, logs
        before_data = _serialize_service_schedule_record(schedule)
        schedule.link_group_key = ""
        schedule.save(update_fields=["link_group_key", "updated_at"])
        schedule = _service_schedule_for_edit(schedule.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=schedule,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(schedule),
            editor_label=editor_label,
            change_note=change_note,
            action_kind=RecordEditLog.ActionKind.LINK_UPDATE,
        )
        if log_entry is not None:
            logs.append(log_entry)
    return schedule, logs


def _reset_service_schedule_planning_fields(schedule: ServiceSchedule) -> None:
    schedule.scheduled_date = None
    schedule.scheduled_time = None
    schedule.completed_on = None
    schedule.location = ""
    schedule.status = ServiceSchedule.Status.CANDIDATE
    schedule.external_calendar_ref = ""


def _create_funeral_service_schedule_for_person(
    *,
    person: Person,
    batch: ImportBatch,
    death_date: date | None,
    funeral_scheduled_date: date | None,
    funeral_scheduled_time: time | None,
    funeral_location: str,
    editor_label: str,
    change_note: str,
) -> RecordEditLog | None:
    schedule = _new_manual_service_schedule(batch, person)
    schedule.category = ServiceSchedule.Category.FUNERAL
    schedule.service_label = "葬儀"
    schedule.subject_name = person.name
    schedule.scheduled_date = funeral_scheduled_date or death_date
    schedule.scheduled_time = funeral_scheduled_time or time(hour=10, minute=0)
    schedule.location = funeral_location
    schedule.status = ServiceSchedule.Status.SCHEDULED
    schedule.save()
    _persist_manual_service_schedule_identity(schedule)
    schedule = _service_schedule_for_edit(schedule.pk)
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=schedule,
        before_data={},
        after_data=_serialize_service_schedule_record(schedule),
        editor_label=editor_label,
        change_note=change_note,
    )
