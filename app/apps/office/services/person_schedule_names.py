"""Propagate personal name corrections without rescheduling observances."""

from django.db import transaction
from django.utils import timezone

from apps.imports.models import RecordEditLog, ServiceSchedule

from .google_calendar_sync_targets import google_calendar_sync_key_for_schedule
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_service_schedule_record


@transaction.atomic
def update_person_schedule_names(person, *, previous_name, editor_label):
    keys = set()
    for schedule in (
        ServiceSchedule.objects.select_for_update(of=("self",))
        .filter(person=person, deleted_at__isnull=True)
        .select_related("person", "household")
    ):
        keys.add(google_calendar_sync_key_for_schedule(schedule))
        before = _serialize_service_schedule_record(schedule)
        old_snapshot = schedule.person_name_snapshot
        changes = {}
        if old_snapshot != person.name:
            changes["person_name_snapshot"] = person.name
        if (
            schedule.subject_name in {"", previous_name, old_snapshot}
            and schedule.subject_name != person.name
        ):
            changes["subject_name"] = person.name
        if not changes:
            continue
        changes["updated_at"] = timezone.now()
        ServiceSchedule.objects.filter(pk=schedule.pk).update(**changes)
        for field, value in changes.items():
            setattr(schedule, field, value)
        _create_record_edit_log(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
            record=schedule,
            before_data=before,
            after_data=_serialize_service_schedule_record(schedule),
            editor_label=editor_label,
            change_note="過去帳の氏名修正を予定へ反映",
        )
    return sorted(keys)
