from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.utils import timezone

from apps.core.services.rokuyo_calendar import rokuyo_for_date
from apps.imports import canonical_population
from apps.imports.model_households import safe_display_head_name
from apps.imports.model_memorial_sync import person_has_memorial_details
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    ImportBatch,
    Person,
    ServiceSchedule,
)

HOME_MEMORIAL_CALENDAR_DAYS = 30


def build_home_memorial_calendar_context(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
    start_date: date | None = None,
    days: int = HOME_MEMORIAL_CALENDAR_DAYS,
    canonical_population_checked: bool = False,
) -> dict[str, Any]:
    canonical_batch = batch
    if not canonical_population_checked:
        canonical_batch = canonical_population.canonical_provenance_import_batch(
            source_id=source_id,
        )
    if canonical_batch is None:
        return {
            "available": False,
            "message": "命日カレンダーの対象データがありません。",
            "calendar_weeks": [],
            "anniversary_details": [],
            "scheduled_service_details": [],
            "total_anniversary_count": 0,
            "total_scheduled_service_count": 0,
            "span_label": "",
        }

    calendar_start = start_date or timezone.localdate()
    calendar_dates = [calendar_start + timedelta(days=offset) for offset in range(days)]
    rows_by_month_day = _anniversary_rows_by_month_day(
        month_day_keys={(item.month, item.day) for item in calendar_dates},
    )
    schedules_by_date = _scheduled_service_rows_by_date(
        calendar_dates=calendar_dates,
    )
    daily_rows = _calendar_daily_rows(
        calendar_dates=calendar_dates,
        rows_by_month_day=rows_by_month_day,
        schedules_by_date=schedules_by_date,
    )
    return {
        "available": True,
        "message": "",
        "calendar_weeks": _build_calendar_weeks(daily_rows),
        "anniversary_details": [
            row["anniversary_detail"]
            for row in daily_rows
            if row["anniversary_detail"]["count"] > 0
        ],
        "scheduled_service_details": [
            row["scheduled_service_detail"]
            for row in daily_rows
            if row["scheduled_service_detail"]["count"] > 0
        ],
        "total_anniversary_count": sum(row["anniversary_count"] for row in daily_rows),
        "total_scheduled_service_count": sum(
            row["scheduled_service_count"] for row in daily_rows
        ),
        "span_label": _calendar_span_label(calendar_dates),
    }


def _calendar_daily_rows(
    *,
    calendar_dates: list[date],
    rows_by_month_day: dict[tuple[int, int], list[dict[str, Any]]],
    schedules_by_date: dict[date, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, calendar_date in enumerate(calendar_dates):
        raw_date = calendar_date.isoformat()
        anniversary_rows = list(rows_by_month_day.get((calendar_date.month, calendar_date.day), []))
        scheduled_service_rows = list(schedules_by_date.get(calendar_date, []))
        anniversary_detail = {
            "date": raw_date,
            "label": f"{calendar_date.month}/{calendar_date.day}",
            "modal_id": f"home-anniversary-{raw_date}",
            "count": len(anniversary_rows),
            "rows": anniversary_rows,
        }
        scheduled_service_detail = {
            "date": raw_date,
            "label": f"{calendar_date.month}/{calendar_date.day}",
            "modal_id": f"home-services-{raw_date}",
            "count": len(scheduled_service_rows),
            "rows": scheduled_service_rows,
            "has_temple_events": any(row.get("is_temple_event") for row in scheduled_service_rows),
        }
        rokuyo = rokuyo_for_date(calendar_date)
        rows.append(
            {
                "date": raw_date,
                "is_empty": False,
                "day_number": calendar_date.day,
                "month_number": calendar_date.month,
                "show_month_label": index == 0 or calendar_date.day == 1,
                "anniversary_count": anniversary_detail["count"],
                "has_anniversary_records": anniversary_detail["count"] > 0,
                "anniversary_modal_id": (
                    anniversary_detail["modal_id"] if anniversary_detail["count"] > 0 else ""
                ),
                "anniversary_detail": anniversary_detail,
                "scheduled_service_count": scheduled_service_detail["count"],
                "has_scheduled_service_records": scheduled_service_detail["count"] > 0,
                "scheduled_service_modal_id": (
                    scheduled_service_detail["modal_id"]
                    if scheduled_service_detail["count"] > 0
                    else ""
                ),
                "scheduled_service_detail": scheduled_service_detail,
                "has_temple_events": scheduled_service_detail["has_temple_events"],
                "rokuyo_label": rokuyo.label,
                "rokuyo_short_label": rokuyo.short_label,
            }
        )
    return rows


def _build_calendar_weeks(daily_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not daily_rows:
        return []
    leading_empty_count = _calendar_weekday_index(date.fromisoformat(daily_rows[0]["date"]))
    cells: list[dict[str, Any]] = [{"is_empty": True} for _ in range(leading_empty_count)]
    cells.extend(daily_rows)
    trailing_empty_count = (-len(cells)) % 7
    cells.extend({"is_empty": True} for _ in range(trailing_empty_count))
    return [cells[index : index + 7] for index in range(0, len(cells), 7)]


def _calendar_weekday_index(value: date) -> int:
    return (value.weekday() + 1) % 7


def _calendar_span_label(calendar_dates: list[date]) -> str:
    if not calendar_dates:
        return ""
    first = calendar_dates[0]
    last = calendar_dates[-1]
    return f"{first.month}/{first.day} - {last.month}/{last.day}"


def _anniversary_rows_by_month_day(
    *,
    month_day_keys: set[tuple[int, int]],
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    if not month_day_keys:
        return {}
    rows_by_month_day: dict[tuple[int, int], list[dict[str, Any]]] = {}
    queryset = (
        Person.objects.filter(
            deleted_at__isnull=True,
            household__deleted_at__isnull=True,
            death_date__isnull=False,
        )
        .select_related("household", "household__head_person")
        .only(
            "person_uid",
            "name",
            "gender",
            "age_at_death",
            "death_date",
            "family_category",
            "is_deceased",
            "death_date_raw",
            "kaimyo",
            "kaimyo_kana",
            "age_at_death_raw",
            "deceased_note",
            "hatsubon_flag",
            "memorial_notice_opt_out",
            "memorial_payload",
            "household__household_uid",
            "household__raw_record",
            "household__head_person_id",
            "household__head_person__name",
            "household__head_person__deleted_at",
        )
        .order_by("-death_date", "-person_uid")
    )
    for person in queryset:
        if not _is_memorial_person(person):
            continue
        death_date = person.death_date
        if death_date is None:
            continue
        month_day = (death_date.month, death_date.day)
        if month_day not in month_day_keys:
            continue
        rows_by_month_day.setdefault(month_day, []).append(
            {
                "death_date": death_date.isoformat(),
                "name": (person.name or "").strip() or person.person_uid,
                "gender": _gender_label(person.gender),
                "age_at_death": person.age_at_death or "",
                "household_name": safe_display_head_name(person.household),
                "person_id": person.person_uid,
                "household_id": person.household.household_uid,
            }
        )
    return rows_by_month_day


def _scheduled_service_rows_by_date(
    *,
    calendar_dates: list[date],
) -> dict[date, list[dict[str, Any]]]:
    if not calendar_dates:
        return {}
    first_date = calendar_dates[0]
    last_date = calendar_dates[-1]
    rows_by_date: dict[date, list[dict[str, Any]]] = {}
    queryset = (
        ServiceSchedule.objects.filter(
            deleted_at__isnull=True,
            status=ServiceSchedule.Status.SCHEDULED,
            scheduled_date__gte=first_date,
            scheduled_date__lte=last_date,
        )
        .select_related("household", "person")
        .order_by("scheduled_date", "scheduled_time", "id")
    )
    for schedule in queryset:
        scheduled_date = schedule.scheduled_date
        if scheduled_date is None:
            continue
        rows_by_date.setdefault(scheduled_date, []).append(_scheduled_service_row(schedule))
    for day, rows in rows_by_date.items():
        grouped = []
        seen = set()
        for row in rows:
            key = row.get("link_group_key")
            if not key:
                grouped.append(row)
                continue
            if key in seen:
                continue
            members = [other for other in rows if other.get("link_group_key") == key]
            master = min(members, key=lambda item: item["schedule_pk"])
            grouped.append({**master, "combined_entries": [other for other in members if other is not master],
                            "service_label": "・".join(dict.fromkeys(item["service_label"] for item in members))})
            seen.add(key)
        rows_by_date[day] = grouped
    return rows_by_date


def _scheduled_service_row(schedule: ServiceSchedule) -> dict[str, Any]:
    is_temple_event = schedule.event_scope == ServiceSchedule.EventScope.TEMPLE
    household_id = schedule.household_uid or (
        schedule.household.household_uid if schedule.household_id else ""
    )
    event_id = schedule.schedule_uid or ""
    person_name = (
        (schedule.subject_name or "").strip()
        or (schedule.person_name_snapshot or "").strip()
        or (schedule.person.name if schedule.person_id and schedule.person is not None else "")
    )
    household_name = (
        (schedule.household_name_snapshot or "").strip()
        or (schedule.household.display_head_name() if schedule.household_id else "")
    )
    if is_temple_event:
        person_name = (schedule.subject_name or "").strip()
        if not schedule.household_id:
            household_id = ""
            household_name = ""
    return {
        "scheduled_date": schedule.scheduled_date.isoformat() if schedule.scheduled_date else "",
        "scheduled_time": schedule.scheduled_time.strftime("%H:%M")
        if schedule.scheduled_time
        else "",
        "service_label": schedule.service_label,
        "schedule_pk": schedule.pk,
        "category": schedule.category,
        "status": schedule.status,
        "link_group_key": schedule.link_group_key,
        "category_label": "寺の予定" if is_temple_event else schedule.get_category_display(),
        "status_label": schedule.get_status_display(),
        "person_name": person_name,
        "household_name": household_name,
        "location": schedule.location,
        "notes": schedule.notes,
        "household_id": household_id,
        "person_id": "" if is_temple_event else schedule.person_uid,
        "event_id": event_id,
        "source_table": schedule.source_table or "",
        "is_temple_event": is_temple_event,
        "temple_event_id": schedule.pk if is_temple_event else None,
        "can_open": bool(schedule.pk) if is_temple_event else bool(household_id and event_id),
    }


def _is_memorial_person(person: Person) -> bool:
    family_category = str(person.family_category or "").strip()
    if family_category == FAMILY_CATEGORY_MEMORIAL:
        return True
    if family_category == FAMILY_CATEGORY_CURRENT:
        return False
    return person.is_deceased or person_has_memorial_details(person)


def _gender_label(value: str | None) -> str:
    cleaned = str(value or "").strip()
    return cleaned or "不明"
