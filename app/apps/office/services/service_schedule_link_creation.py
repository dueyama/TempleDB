from __future__ import annotations

from uuid import uuid4

from apps.imports import service_ledger_runtime
from apps.imports.models import Person, RecordEditLog, ServiceSchedule

from .google_calendar_sync_targets import google_calendar_sync_key_for_schedule
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_service_schedule_record
from .service_schedule_core import (
    _new_manual_service_schedule,
    _normalize_service_schedule_target_date,
    _persist_manual_service_schedule_identity,
    _service_schedule_for_edit,
)
from .service_schedule_lifecycle import (
    _is_manual_service_schedule,
    _manual_service_schedule_has_blocking_relations,
)


def _new_service_link_group_key() -> str:
    return f"slg-{uuid4().hex[:12]}"


def _create_linked_service_schedules(
    *,
    batch,
    source_id: str,
    base_schedule: ServiceSchedule,
    selected_candidates: list[dict],
    editor_label: str,
    change_note: str,
    previous_sync_keys: list[str] | None = None,
) -> list[ServiceSchedule]:
    del source_id
    if not selected_candidates:
        return []
    linked_schedules: list[ServiceSchedule] = []
    persons_by_legacy_id = {
        person.person_uid: person
        for person in Person.objects.select_related("household").filter(
            household__household_uid=base_schedule.household_uid,
            deleted_at__isnull=True,
        )
    }
    for candidate in selected_candidates:
        if not candidate.get("is_selectable", True):
            continue
        person = persons_by_legacy_id.get(candidate.get("person_id", ""))
        if person is None:
            continue
        linked_schedule = _find_reusable_linked_schedule(
            batch=batch,
            base_schedule=base_schedule,
            person=person,
            candidate=candidate,
        )
        before_data = (
            _serialize_service_schedule_record(linked_schedule)
            if linked_schedule is not None
            else {}
        )
        if linked_schedule is None:
            provenance_batch = base_schedule.related_batch or person.batch
            linked_schedule = _new_manual_service_schedule(provenance_batch, person)
        elif previous_sync_keys is not None:
            previous_sync_keys.append(google_calendar_sync_key_for_schedule(linked_schedule))
        _apply_linked_schedule_values(
            linked_schedule=linked_schedule,
            base_schedule=base_schedule,
            person=person,
            candidate=candidate,
        )
        _normalize_service_schedule_target_date(linked_schedule)
        linked_schedule.save()
        _persist_manual_service_schedule_identity(linked_schedule)
        linked_schedule = _service_schedule_for_edit(linked_schedule.pk)
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=linked_schedule,
            before_data=before_data,
            after_data=_serialize_service_schedule_record(linked_schedule),
            editor_label=editor_label,
            change_note=change_note,
            action_kind=(
                RecordEditLog.ActionKind.LINK_UPDATE
                if before_data
                else RecordEditLog.ActionKind.UPDATE
            ),
        )
        linked_schedules.append(linked_schedule)
    return linked_schedules


def _apply_linked_schedule_values(
    *,
    linked_schedule: ServiceSchedule,
    base_schedule: ServiceSchedule,
    person: Person,
    candidate: dict,
) -> None:
    linked_schedule.link_group_key = base_schedule.link_group_key
    linked_schedule.category = service_ledger_runtime._service_schedule_category_for_candidate_type(
        candidate.get("candidate_type"),
        candidate.get("label"),
    )
    linked_schedule.service_label = candidate.get("label", "")
    linked_schedule.subject_name = person.name
    linked_schedule.scheduled_date = base_schedule.scheduled_date
    linked_schedule.scheduled_time = base_schedule.scheduled_time
    linked_schedule.completed_on = base_schedule.completed_on
    linked_schedule.location = base_schedule.location
    linked_schedule.status = base_schedule.status
    linked_schedule.notes = base_schedule.notes
    linked_schedule.external_calendar_ref = base_schedule.external_calendar_ref


def _find_reusable_linked_schedule(
    *,
    batch,
    base_schedule: ServiceSchedule,
    person: Person,
    candidate: dict,
) -> ServiceSchedule | None:
    del batch
    matching_schedules = [
        item
        for item in ServiceSchedule.objects.filter(
            household_uid=base_schedule.household_uid,
            person_uid=person.person_uid,
            deleted_at__isnull=True,
        )
        .exclude(pk=base_schedule.pk)
        .select_related("person", "person__deceased_profile")
        .order_by("id")
        if (
            _is_manual_service_schedule(item)
            and not item.link_group_key
            and not _manual_service_schedule_has_blocking_relations(item)
        )
    ]
    return service_ledger_runtime._matching_actual_schedule_for_candidate(candidate, matching_schedules)
