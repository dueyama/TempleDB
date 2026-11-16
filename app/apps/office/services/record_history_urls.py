from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from apps.imports.models import RecordEditLog, ServiceSchedule

from .record_history_snapshot import _history_log_event_scope


def _edit_url(
    view_name: str,
    *args: str,
    source_id: str,
    next_url: str,
    extra_query: dict[str, str] | None = None,
) -> str:
    del source_id
    query = {"next": next_url}
    if extra_query:
        query.update({key: value for key, value in extra_query.items() if value})
    return f"{reverse(view_name, args=args)}?{urlencode(query)}"


def _record_history_edit_url(
    log: RecordEditLog,
    source_id: str,
    current_url: str,
    current_record_exists: bool,
) -> str:
    if log.record_type in {
        RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT,
        RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_SETTING,
    }:
        year = log.after_data.get("year") or log.before_data.get("year")
        query = {"year": str(year)} if year else {}
        url = reverse("office:annual_membership_fees")
        return f"{url}?{urlencode(query)}" if query else url
    if log.record_type == RecordEditLog.RecordType.DISTRICT:
        if current_record_exists:
            return f"{reverse('office:districts')}?{urlencode({'edit': log.record_id})}"
        return ""
    if log.record_type == RecordEditLog.RecordType.DISTRICT_MEMBER_SHEET:
        return reverse("office:district_member_sheets")
    if _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE:
        if log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE:
            event_id = log.record_id if current_record_exists else None
        elif log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT:
            event_id = log.after_data.get("service_schedule_id") or log.before_data.get(
                "service_schedule_id"
            )
        else:
            event_id = None
        if event_id:
            return _edit_url(
                "office:edit_temple_event",
                str(event_id),
                source_id=source_id,
                next_url=current_url,
            )
        return ""
    if log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT:
        if log.legacy_household_id and log.legacy_schedule_id:
            source_table = (
                log.after_data.get("service_source_table")
                or log.before_data.get("service_source_table")
                or ""
            )
            return _edit_url(
                "office:edit_service_schedule",
                log.legacy_household_id,
                log.legacy_schedule_id,
                source_id=source_id,
                next_url=current_url,
                extra_query={"source_table": source_table} if source_table else None,
            )
        if current_record_exists and log.legacy_household_id:
            return _edit_url(
                "office:edit_household_offering_payment",
                log.legacy_household_id,
                str(log.record_id),
                source_id=source_id,
                next_url=current_url,
            )
        return ""
    if not current_record_exists:
        return ""
    if log.record_type == RecordEditLog.RecordType.HOUSEHOLD and log.legacy_household_id:
        return _edit_url(
            "office:edit_household",
            log.legacy_household_id,
            source_id=source_id,
            next_url=current_url,
        )
    if (
        log.record_type == RecordEditLog.RecordType.PERSON
        and log.legacy_household_id
        and log.legacy_person_id
    ):
        return _edit_url(
            "office:edit_person",
            log.legacy_household_id,
            log.legacy_person_id,
            source_id=source_id,
            next_url=current_url,
        )
    if (
        log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE
        and log.legacy_household_id
        and log.legacy_schedule_id
    ):
        source_table = (
            log.after_data.get("source_table")
            or log.before_data.get("source_table")
            or ""
        )
        return _edit_url(
            "office:edit_service_schedule",
            log.legacy_household_id,
            log.legacy_schedule_id,
            source_id=source_id,
            next_url=current_url,
            extra_query={"source_table": source_table} if source_table else None,
        )
    return ""
