"""Atomic schedule, payment, history and observance persistence for form saves.

Views validate forms and register the returned sync keys after commit. This
module never contacts Google or depends on requests, messages or redirects.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import transaction

from apps.imports.models import ImportBatch, OfferingPayment, Person, RecordEditLog, ServiceSchedule

from .funeral_first_seventh import (
    add_first_seventh,
    lock_linked_funeral_observances,
    sync_linked_funeral_observances,
)
from .google_calendar_sync_targets import google_calendar_sync_key_for_schedule
from .offering_payments import create_offering_payment_logs_for_diff
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_service_schedule_record
from .service_schedule_core import (
    _apply_manual_service_schedule_defaults,
    _normalize_service_schedule_subject_name,
    _normalize_service_schedule_target_date,
    _persist_manual_service_schedule_identity,
    _service_schedule_for_edit,
)
from .service_schedule_lifecycle import _sync_linked_service_schedule_members
from .service_schedule_links import (
    _apply_linked_group_updates,
    _create_linked_service_schedules,
    _new_service_link_group_key,
    _selected_service_link_candidates,
)


@dataclass(frozen=True)
class ServiceScheduleSaveSnapshot:
    """Values captured before a bound form mutates its model instance."""

    before_data: dict
    payment_snapshots: dict[int, dict]
    payment_records: dict[int, OfferingPayment]
    link_group_key: str
    sync_key: str


@dataclass(frozen=True)
class ServiceScheduleSaveOptions:
    supports_linking: bool
    link_candidates: list[dict] = field(default_factory=list)
    linked_candidate_tokens: list[str] = field(default_factory=list)
    linked_schedule_ids: list[str] = field(default_factory=list)
    reset_unlinked_schedules: bool = False
    apply_to_linked_group: bool = False
    include_first_seventh: bool = False


@dataclass(frozen=True)
class ServiceScheduleSaveResult:
    schedule: ServiceSchedule
    log_entry: RecordEditLog | None
    payment_logs: list[RecordEditLog]
    linked_logs: list[RecordEditLog]
    unlinked_logs: list[RecordEditLog]
    linked_created: list[ServiceSchedule]
    sync_keys: list[str]


@transaction.atomic
def save_service_schedule(
    schedule: ServiceSchedule,
    *,
    batch: ImportBatch,
    person: Person | None,
    source_id: str,
    options: ServiceScheduleSaveOptions,
    persist_payments: Callable[[], object],
    editor_label: str,
    change_note: str,
    snapshot: ServiceScheduleSaveSnapshot | None = None,
) -> ServiceScheduleSaveResult:
    """Save a validated instance and payment callback in one transaction.

    No snapshot means a new manual schedule. For edits the caller must supply
    the pre-form snapshot; creation defaults and edit-only funeral propagation
    remain distinct, while their shared persistence order has one owner.
    """
    creating = snapshot is None
    if creating != (schedule.pk is None):
        raise ValueError("New schedules require no snapshot; edits require their prior snapshot.")
    if creating:
        if person is None:
            raise ValueError("A person is required to create a manual service schedule.")
        if not options.supports_linking:
            schedule.link_group_key = ""
        _apply_manual_service_schedule_defaults(schedule, batch, person)
    elif not options.supports_linking:
        schedule.link_group_key = snapshot.link_group_key
    _normalize_service_schedule_target_date(schedule)
    _normalize_service_schedule_subject_name(schedule)
    if not creating:
        lock_linked_funeral_observances(schedule)
    schedule.save()
    persist_payments()
    payment_logs = create_offering_payment_logs_for_diff(
        before_snapshots=snapshot.payment_snapshots if snapshot else {},
        before_records=snapshot.payment_records if snapshot else {},
        after_payments=list(
            OfferingPayment.objects.filter(service_schedule=schedule)
            .select_related("household", "person", "service_schedule").order_by("pk")
        ),
        editor_label=editor_label,
        change_note=change_note,
    )
    selected_candidates = (
        _selected_service_link_candidates(options.linked_candidate_tokens, options.link_candidates)
        if options.supports_linking else []
    )
    if selected_candidates and (creating or not schedule.link_group_key):
        schedule.link_group_key = _new_service_link_group_key()
        schedule.save(update_fields=["link_group_key", "updated_at"])
    unlinked_logs = []
    if creating:
        _persist_manual_service_schedule_identity(schedule)
    elif options.supports_linking:
        schedule, unlinked_logs = _sync_linked_service_schedule_members(
            schedule,
            selected_linked_schedule_ids=options.linked_schedule_ids,
            reset_unlinked_schedules=options.reset_unlinked_schedules,
            editor_label=editor_label,
            change_note=change_note or "法要リンクを調整",
        )
    schedule = _service_schedule_for_edit(schedule.pk)
    before_data = snapshot.before_data if snapshot else {}
    log_entry = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=schedule,
        before_data=before_data,
        after_data=_serialize_service_schedule_record(schedule),
        editor_label=editor_label,
        change_note=change_note,
    )
    linked_logs = []
    if not creating:
        if options.supports_linking:
            linked_logs = _apply_linked_group_updates(
                schedule,
                apply_updates=options.apply_to_linked_group,
                editor_label=editor_label,
                change_note=change_note,
            )
        linked_logs.extend(sync_linked_funeral_observances(
            schedule, before_data=before_data, editor_label=editor_label,
        ))
    previous_linked_sync_keys: list[str] = []
    linked_created = (
        _create_linked_service_schedules(
            batch=batch,
            source_id=source_id,
            base_schedule=schedule,
            selected_candidates=selected_candidates,
            editor_label=editor_label,
            change_note=change_note,
            previous_sync_keys=previous_linked_sync_keys,
        ) if options.supports_linking else []
    )
    first_seventh = (
        add_first_seventh(schedule, editor_label=editor_label)
        if not creating and options.include_first_seventh else None
    )
    sync_keys = [google_calendar_sync_key_for_schedule(schedule), *previous_linked_sync_keys]
    if first_seventh is not None:
        sync_keys.extend([
            f"schedule:{first_seventh.pk}", google_calendar_sync_key_for_schedule(first_seventh),
        ])
    if snapshot is not None:
        sync_keys.append(snapshot.sync_key)
    return ServiceScheduleSaveResult(
        schedule=schedule, log_entry=log_entry, payment_logs=payment_logs,
        linked_logs=linked_logs, unlinked_logs=unlinked_logs, linked_created=linked_created,
        sync_keys=sync_keys,
    )
