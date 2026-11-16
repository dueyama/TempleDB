from __future__ import annotations

from django.db.models import Q

from apps.imports import canonical_population, source_runtime
from apps.imports.models import (
    AnnualMembershipFeePayment,
    AnnualMembershipFeeSetting,
    District,
    DistrictMemberSheetState,
    Household,
    OfferingPayment,
    RecordEditLog,
    ServiceSchedule,
)
from apps.office.web_support import RECORD_HISTORY_ACTIONS

from .record_history_snapshot import _history_log_event_scope
from .record_history_source_ops import _source_operation_history_entries


def _entries_module():
    from . import record_history_entries

    return record_history_entries


def _build_record_history_context(
    *,
    source_id: str | None,
    query: str,
    action: str,
    current_url: str,
) -> dict:
    source = source_runtime.resolve_source_entry(source_id)
    active_source_id = source["source_id"]
    latest_export = source_runtime.latest_export_snapshot(active_source_id)
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )

    logs = RecordEditLog.objects.filter(legacy_source_id=active_source_id).prefetch_related(
        "field_changes"
    )
    query_text = (query or "").strip()
    if query_text:
        logs = logs.filter(
            Q(record_label__icontains=query_text)
            | Q(legacy_household_id__icontains=query_text)
            | Q(legacy_person_id__icontains=query_text)
            | Q(legacy_schedule_id__icontains=query_text)
            | Q(editor_label__icontains=query_text)
            | Q(change_note__icontains=query_text)
        )

    entries = []
    for log in logs.order_by("-created_at", "-id")[:120]:
        entry = _entries_module()._record_history_entry(
            log,
            active_source_id,
            canonical_batch,
            current_url,
        )
        if action != "all" and entry["action"]["key"] != action:
            continue
        entries.append(entry)

    source_operation_entries = _source_operation_history_entries(
        source_id=active_source_id,
        query=query_text,
    )

    return {
        "selected_source_id": active_source_id,
        "registered_sources": source_runtime.registered_sources(active_source_id),
        "latest_export": latest_export,
        "canonical_batch": canonical_batch,
        "canonical_snapshot_id": (
            canonical_batch.prepared_snapshot_id if canonical_batch is not None else ""
        ),
        "action": action,
        "action_options": [
            {**item, "selected": item["key"] == action} for item in RECORD_HISTORY_ACTIONS
        ],
        "query": query_text,
        "entries": entries,
        "entry_count": len(entries),
        "update_count": sum(1 for entry in entries if entry["action"]["key"] == "update"),
        "delete_count": sum(1 for entry in entries if entry["action"]["key"] == "delete"),
        "restore_count": sum(1 for entry in entries if entry["action"]["key"] == "restore"),
        "source_operation_entries": source_operation_entries,
        "source_operation_count": len(source_operation_entries),
        "current_url": current_url,
        "has_current_batch": canonical_batch is not None,
    }


def _resolve_current_record_for_log(log: RecordEditLog, latest_batch):
    administrative_models = {
        RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT: AnnualMembershipFeePayment,
        RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_SETTING: AnnualMembershipFeeSetting,
        RecordEditLog.RecordType.DISTRICT_MEMBER_SHEET: DistrictMemberSheetState,
    }
    if log.record_type in administrative_models:
        return administrative_models[log.record_type].objects.filter(
            pk=log.record_id, source__source_id=log.legacy_source_id,
        ).first()
    if log.record_type == RecordEditLog.RecordType.DISTRICT:
        return District.objects.filter(pk=log.record_id).first()
    if latest_batch is None:
        return None
    if (
        log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE
        and _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE
    ):
        return ServiceSchedule.objects.filter(
            pk=log.record_id,
            event_scope=ServiceSchedule.EventScope.TEMPLE,
        ).first()
    if log.record_type == RecordEditLog.RecordType.HOUSEHOLD and log.legacy_household_id:
        return Household.objects.filter(
            household_uid=log.legacy_household_id,
        ).first()
    if (
        log.record_type == RecordEditLog.RecordType.PERSON
        and log.legacy_household_id
        and log.legacy_person_id
    ):
        from apps.imports.models import Person

        return (
            Person.objects.select_related("household")
            .filter(
                household__household_uid=log.legacy_household_id,
                person_uid=log.legacy_person_id,
            )
            .first()
        )
    if (
        log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE
        and log.legacy_household_id
        and log.legacy_schedule_id
    ):
        source_table = (
            log.after_data.get("source_table") or log.before_data.get("source_table") or ""
        )
        schedules = ServiceSchedule.objects.filter(
            household_uid=log.legacy_household_id,
            schedule_uid=log.legacy_schedule_id,
        )
        if source_table:
            schedules = schedules.filter(source_table=source_table)
        return schedules.first()
    if log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT:
        return (
            OfferingPayment.objects.select_related("household", "person", "service_schedule")
            .filter(
                pk=log.record_id,
            )
            .first()
        )
    return None
