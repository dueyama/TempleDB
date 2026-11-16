from __future__ import annotations

from datetime import date, timedelta

from apps.core.services import tenant_policy

from .memorial_shared import (
    _add_memorial_offset_years,
    _first_obon_date,
    _kijitsu_offset_days_from_label,
    _memorial_offset_years_from_label,
)
from .models import ServiceSchedule
from .runtime_shared import _clean_row_record, _clean_value, _search_text, _sort_text


def _service_row_from_model(service: ServiceSchedule) -> dict[str, str]:
    raw_record = _clean_row_record(service.raw_record)
    row = dict(raw_record)
    resolved_target_date = _resolved_service_schedule_target_date(service)
    effective_status = _effective_service_schedule_status(service)
    row["予定ID"] = service.schedule_uid or service.legacy_pk_text
    row["台帳ID"] = service.household_uid
    row["家族ID"] = service.person_uid
    row["予定種別ID"] = service.legacy_schedule_type_id
    row["予定種別名"] = service.service_label
    row["予定年月日"] = service.scheduled_date.isoformat() if service.scheduled_date else ""
    row["実施日"] = service.completed_on.isoformat() if service.completed_on else ""
    row["状態"] = _effective_service_schedule_status_label(service)
    row["status"] = service.status
    row["effective_status"] = effective_status
    row["record_origin"] = service.record_origin
    row["__event_scope"] = service.event_scope
    row["__schedule_pk"] = str(service.pk or "")
    row["target_date"] = resolved_target_date.isoformat() if resolved_target_date else ""
    row["予定備考"] = service.notes
    row["法事場所"] = service.location
    row["予備俗名"] = service.subject_name
    row["__source_table"] = service.source_table
    row["__raw_record"] = raw_record
    return row


def _actual_service_schedule_death_date(schedule: ServiceSchedule) -> date | None:
    person = getattr(schedule, "person", None)
    return person.death_date if person is not None else None


def _resolved_service_schedule_target_date(schedule: ServiceSchedule) -> date | None:
    death_date = _actual_service_schedule_death_date(schedule)
    if death_date is None:
        return schedule.target_date
    if schedule.category == ServiceSchedule.Category.HATSUBON or _clean_value(schedule.service_label) == "初盆":
        return _first_obon_date(death_date)
    kijitsu_offset_days = _kijitsu_offset_days_from_label(schedule.service_label)
    if kijitsu_offset_days is not None:
        return death_date + timedelta(days=kijitsu_offset_days)
    memorial_offset_years = _memorial_offset_years_from_label(schedule.service_label)
    if memorial_offset_years is not None:
        return _add_memorial_offset_years(death_date, memorial_offset_years)
    return schedule.target_date


def _compact_service_label(service_label: str | None) -> str:
    normalized_label = _clean_value(service_label)
    if not normalized_label:
        return ""
    memorial_offset_years = _memorial_offset_years_from_label(normalized_label)
    if memorial_offset_years is None:
        return normalized_label
    if memorial_offset_years == 1:
        return "一周忌"
    return f"{memorial_offset_years + 1}回忌"


def _service_category_badge_label(
    category: str | None,
    service_label: str | None = None,
) -> str:
    normalized_category = _clean_value(category)
    normalized_label = _clean_value(service_label)
    if normalized_category == ServiceSchedule.Category.MEMORIAL:
        if _memorial_offset_years_from_label(normalized_label) is not None:
            return "回忌"
    return _service_schedule_category_label(normalized_category)


def _service_schedule_category_label(category: str | None) -> str:
    normalized_category = _clean_value(category)
    if not normalized_category:
        return ""
    labels = tenant_policy.service_schedule_category_labels()
    return labels.get(normalized_category, normalized_category)


def _service_schedule_primary_display_name(schedule: ServiceSchedule) -> str:
    if schedule.category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    }:
        return _service_schedule_category_label(schedule.category)
    return schedule.subject_name or schedule.person_name_snapshot or ""


def _service_schedule_display_label(schedule: ServiceSchedule) -> str:
    if schedule.category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    }:
        return _service_schedule_category_label(schedule.category)
    return schedule.service_label


def _is_household_service_schedule(schedule: ServiceSchedule) -> bool:
    return schedule.category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    }


def _service_ledger_schedule_entry(
    schedule: ServiceSchedule,
    *,
    today: date,
    overdue_period_start: date,
) -> dict:
    target_date = _resolved_service_schedule_target_date(schedule)
    scheduled_date = schedule.scheduled_date
    completed_on = schedule.completed_on
    scheduled_time = schedule.scheduled_time
    effective_status = _effective_service_schedule_status(schedule)
    is_done = effective_status in {
        ServiceSchedule.Status.COMPLETED,
        ServiceSchedule.Status.CANCELLED,
    }
    is_actionable_overdue = (
        scheduled_date is not None
        and overdue_period_start <= scheduled_date < today
        and not is_done
    )
    service_label = _service_schedule_display_label(schedule)
    is_household_event = _is_household_service_schedule(schedule)
    return {
        "event_id": schedule.schedule_uid or str(schedule.pk),
        "schedule_pk": schedule.pk,
        "source_table": schedule.source_table or "",
        "link_group_key": schedule.link_group_key or "",
        "household_id": schedule.household_uid,
        "household_name": schedule.household_name_snapshot
        or (schedule.household.display_head_name() if schedule.household_id else ""),
        "person_id": schedule.person_uid,
        "person_name": _service_schedule_primary_display_name(schedule),
        "relationship": schedule.person.relationship_label if schedule.person_id and schedule.person is not None else "",
        "service_label": service_label,
        "service_label_compact": _compact_service_label(service_label),
        "category": schedule.category,
        "category_label": _service_category_badge_label(schedule.category, service_label),
        "is_household_event": is_household_event,
        "status": schedule.status,
        "effective_status": effective_status,
        "status_label": _effective_service_schedule_status_label(schedule),
        "scheduled_date": scheduled_date.strftime("%Y-%m-%d") if scheduled_date else "",
        "scheduled_date_value": scheduled_date,
        "scheduled_time": scheduled_time.strftime("%H:%M") if scheduled_time else "",
        "scheduled_time_sort": scheduled_time.isoformat() if scheduled_time else "",
        "target_date": target_date.strftime("%Y-%m-%d") if target_date else "",
        "target_date_value": target_date,
        "completed_on": completed_on.strftime("%Y-%m-%d") if completed_on else "",
        "completed_on_value": completed_on,
        "location": schedule.location,
        "notes": schedule.notes,
        "record_origin": schedule.record_origin,
        "record_origin_label": schedule.get_record_origin_display(),
        "note_count": getattr(schedule, "note_count", 0),
        "payment_count": getattr(schedule, "payment_count", 0),
        "is_done": is_done,
        "is_today": scheduled_date == today,
        "is_overdue": is_actionable_overdue,
        "is_candidate": False,
    }


def _collapse_linked_service_entries(entries: list[dict]) -> list[dict]:
    grouped: list[dict] = []
    grouped_keys: set[str] = set()
    entries_by_group: dict[str, list[dict]] = {}
    for entry in entries:
        link_group_key = str(entry.get("link_group_key") or "")
        if link_group_key:
            entries_by_group.setdefault(link_group_key, []).append(entry)
    for entry in entries:
        link_group_key = str(entry.get("link_group_key") or "")
        if not link_group_key:
            grouped.append({**entry, "linked_entries": [], "linked_group_count": 0})
            continue
        if link_group_key in grouped_keys:
            continue
        group_members = sorted(
            entries_by_group.get(link_group_key, []),
            key=_linked_service_entry_master_sort_key,
        )
        master = group_members[0] if group_members else entry
        linked_entries = [item for item in group_members if item is not master]
        grouped.append(
            {
                **master,
                "linked_entries": linked_entries,
                "linked_group_count": len(group_members),
            }
        )
        grouped_keys.add(link_group_key)
    return grouped


def _linked_service_entry_master_sort_key(entry: dict) -> tuple:
    schedule_pk = entry.get("schedule_pk")
    return (
        int(schedule_pk) if schedule_pk not in (None, "") else 0,
        entry.get("scheduled_date_value") or date.max,
        entry.get("scheduled_time_sort") or "99:99:99",
        entry.get("target_date_value") or date.max,
        _sort_text(entry.get("person_name", "")),
        _sort_text(entry.get("service_label", "")),
    )


def _effective_service_schedule_status(schedule: ServiceSchedule) -> str:
    return schedule.status


def _effective_service_schedule_status_label(schedule: ServiceSchedule) -> str:
    effective_status = _effective_service_schedule_status(schedule)
    if effective_status == ServiceSchedule.Status.COMPLETED:
        return ServiceSchedule.Status.COMPLETED.label
    if effective_status == ServiceSchedule.Status.CANCELLED:
        return ServiceSchedule.Status.CANCELLED.label
    if effective_status == ServiceSchedule.Status.DEFERRED:
        return ServiceSchedule.Status.DEFERRED.label
    if effective_status == ServiceSchedule.Status.SCHEDULED:
        return ServiceSchedule.Status.SCHEDULED.label
    return schedule.get_status_display()


def _service_event_is_actual(event: dict) -> bool:
    # Temple events remain events, but are not actual household memorial services.
    if _clean_value(event.get("event_scope")) == ServiceSchedule.EventScope.TEMPLE:
        return False
    record_origin = _clean_value(event.get("record_origin"))
    status = _clean_value(event.get("status"))
    has_dates = bool(_clean_value(event.get("scheduled_date")) or _clean_value(event.get("completed_on")))
    if record_origin == ServiceSchedule.Origin.MANUAL:
        return status != ServiceSchedule.Status.CANDIDATE or has_dates
    if status != ServiceSchedule.Status.CANDIDATE:
        return True
    return has_dates


def _is_actual_service_schedule(schedule: ServiceSchedule) -> bool:
    event_scope = getattr(schedule, "event_scope", ServiceSchedule.EventScope.HOUSEHOLD)
    if event_scope == ServiceSchedule.EventScope.TEMPLE:
        return False
    if schedule.record_origin == ServiceSchedule.Origin.MANUAL:
        return schedule.status != ServiceSchedule.Status.CANDIDATE or bool(
            schedule.scheduled_date or schedule.completed_on
        )
    if schedule.status != ServiceSchedule.Status.CANDIDATE:
        return True
    return bool(schedule.scheduled_date or schedule.completed_on)


def _service_ledger_schedule_matches(entry: dict, needle: str) -> bool:
    return any(
        needle in _search_text(value)
        for value in (
            entry.get("event_id"),
            entry.get("household_id"),
            entry.get("household_name"),
            entry.get("person_id"),
            entry.get("person_name"),
            entry.get("service_label"),
            entry.get("category_label"),
            entry.get("status_label"),
            entry.get("scheduled_date"),
            entry.get("location"),
            entry.get("notes"),
        )
    )
