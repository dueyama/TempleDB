from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from apps.core.services import google_calendar as google_calendar_service
from apps.core.services import tenant_policy as tenant_policy_services
from apps.imports.models import ServiceSchedule
from apps.office.services.memorials import (
    _actual_service_schedule_death_date,
    _compact_service_label,
    _resolved_service_schedule_target_date,
)

GOOGLE_CALENDAR_STATUS_PREFIXES = {
    ServiceSchedule.Status.COMPLETED: "[完了] ",
    ServiceSchedule.Status.CANCELLED: "[中止] ",
    ServiceSchedule.Status.DEFERRED: "[見送り] ",
}


def _google_calendar_is_temple_event(schedule: ServiceSchedule) -> bool:
    return schedule.event_scope == ServiceSchedule.EventScope.TEMPLE


def _google_calendar_is_generic_other_event(schedule: ServiceSchedule) -> bool:
    normalized_category = str(schedule.category or "").strip()
    normalized_label = str(schedule.service_label or "").strip()
    return normalized_category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    } or (
        normalized_category == ServiceSchedule.Category.OTHER
        and normalized_label != "葬儀"
    )


def _build_google_calendar_event_payload(
    *,
    sync_key: str,
    schedule: ServiceSchedule,
    member_schedule_ids: list[int],
) -> dict:
    del sync_key
    event_date = _google_calendar_effective_date(schedule)
    assert event_date is not None
    status_prefix = GOOGLE_CALENDAR_STATUS_PREFIXES.get(schedule.status, "")
    subject_label = _google_calendar_subject_label(schedule)
    service_label = _google_calendar_service_label(schedule)
    description_lines = _google_calendar_schedule_detail_lines(schedule)
    linked_member_lines = _google_calendar_linked_member_lines(
        schedule=schedule,
        member_schedule_ids=member_schedule_ids,
    )
    if linked_member_lines:
        description_lines.append(f"リンク法要: {len(member_schedule_ids)} 件を一緒に勤めます")
        description_lines.extend(linked_member_lines)
    for link_label, link_url in _google_calendar_edit_urls(schedule):
        description_lines.append(f"{link_label}: {link_url}")
    if _google_calendar_is_temple_event(schedule):
        summary = f"{status_prefix}{service_label}"
        if subject_label:
            summary += f" / {subject_label}"
    else:
        summary = f"{status_prefix}{subject_label} / {service_label}"
    payload = {
        "summary": summary,
        "description": "\n".join(description_lines),
        "location": (schedule.location or "").strip(),
    }
    event_time = schedule.scheduled_time
    if isinstance(event_time, datetime_time):
        start_dt = datetime.combine(event_date, event_time)
        end_dt = start_dt + timedelta(hours=1)
        payload["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": settings.TIME_ZONE,
        }
        payload["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": settings.TIME_ZONE,
        }
    else:
        payload["start"] = {"date": event_date.isoformat()}
        payload["end"] = {"date": (event_date + timedelta(days=1)).isoformat()}
    return payload


def _google_calendar_subject_label(schedule: ServiceSchedule) -> str:
    if _google_calendar_is_temple_event(schedule):
        return (schedule.subject_name or "").strip()
    generic_other_person_label = _google_calendar_generic_other_person_label(schedule)
    if generic_other_person_label:
        return generic_other_person_label
    if _google_calendar_is_generic_other_event(schedule):
        return _google_calendar_household_label(schedule)
    subject_name = ""
    for value in (
        schedule.subject_name,
        schedule.person_name_snapshot,
        schedule.person.name if schedule.person_id and schedule.person is not None else "",
    ):
        label = (value or "").strip()
        if label:
            subject_name = label
            break
    if not subject_name:
        return _google_calendar_household_label(schedule)
    person = schedule.person if schedule.person_id and schedule.person is not None else None
    person_kana = (person.kana or "").strip() if person is not None else ""
    return _google_calendar_label_with_kana(subject_name, person_kana)


def _google_calendar_generic_other_person_label(schedule: ServiceSchedule) -> str:
    if not _google_calendar_is_generic_other_event(schedule):
        return ""
    if str(schedule.category or "").strip() != ServiceSchedule.Category.OTHER:
        return ""
    person = schedule.person if schedule.person_id and schedule.person is not None else None
    if person is None or not person.is_deceased:
        return ""
    person_name = (person.name or "").strip() or (schedule.person_name_snapshot or "").strip()
    if not person_name:
        return ""
    return _google_calendar_label_with_kana(person_name, (person.kana or "").strip())


def _google_calendar_service_label(schedule: ServiceSchedule) -> str:
    if _google_calendar_is_temple_event(schedule):
        return (schedule.service_label or "").strip() or "寺の予定"
    compact_label = _compact_service_label(schedule.service_label)
    if compact_label:
        return compact_label
    if _google_calendar_is_generic_other_event(schedule):
        return "イベント予定"
    return "法要予定"


def _google_calendar_service_field_label(schedule: ServiceSchedule) -> str:
    if _google_calendar_is_generic_other_event(schedule):
        return "イベント"
    return "法要"


def _google_calendar_household_label(schedule: ServiceSchedule) -> str:
    household_label = (schedule.household_name_snapshot or "").strip()
    household_kana = ""
    if not household_label and schedule.household_id and schedule.household is not None:
        household_label = schedule.household.display_head_name()
    if schedule.household_id and schedule.household is not None:
        household_kana = (schedule.household.display_head_name_kana() or "").strip()
    resolved_label = household_label or schedule.household_uid or "法要予定"
    return _google_calendar_label_with_kana(resolved_label, household_kana)


def _google_calendar_label_with_kana(label: str, kana: str | None) -> str:
    resolved_label = (label or "").strip()
    resolved_kana = (kana or "").strip()
    if not resolved_label:
        return ""
    if not resolved_kana:
        return resolved_label
    return f"{resolved_label}（{resolved_kana}）"


def _google_calendar_kaimyo_label(schedule: ServiceSchedule) -> str:
    person = schedule.person if schedule.person_id and schedule.person is not None else None
    if person is None:
        return ""
    kaimyo = (person.kaimyo or "").strip()
    kaimyo_kana = (person.kaimyo_kana or "").strip()
    return _google_calendar_label_with_kana(kaimyo, kaimyo_kana)


def _google_calendar_kaimyo_field_label() -> str:
    return tenant_policy_services.get_label("person.kaimyo", "法名")


def _google_calendar_death_date_label(schedule: ServiceSchedule) -> str:
    death_date = _actual_service_schedule_death_date(schedule)
    if death_date is None:
        return ""
    return death_date.isoformat()


def _google_calendar_planned_death_date_label(schedule: ServiceSchedule) -> str:
    planned_death_date = _resolved_service_schedule_target_date(schedule)
    if planned_death_date is None:
        return ""
    return planned_death_date.isoformat()


def _google_calendar_linked_member_lines(
    *,
    schedule: ServiceSchedule,
    member_schedule_ids: list[int],
) -> list[str]:
    if _google_calendar_is_temple_event(schedule):
        return []
    if not schedule.link_group_key or len(member_schedule_ids) <= 1:
        return []
    members = list(
        ServiceSchedule.objects.filter(pk__in=member_schedule_ids, deleted_at__isnull=True)
        .select_related("person", "household")
        .order_by("pk")
    )
    lines: list[str] = []
    linked_members = [item for item in members if item.pk != schedule.pk]
    for index, item in enumerate(linked_members, start=1):
        lines.append(f"併修法要 {index}:")
        lines.extend(_google_calendar_schedule_detail_lines(item, prefix="  "))
    return lines


def _google_calendar_schedule_detail_lines(
    schedule: ServiceSchedule,
    *,
    prefix: str = "",
) -> list[str]:
    if _google_calendar_is_temple_event(schedule):
        lines = [f"{prefix}寺の予定: {_google_calendar_service_label(schedule)}"]
        counterpart = _google_calendar_subject_label(schedule)
        if counterpart:
            lines.append(f"{prefix}相手先: {counterpart}")
        if schedule.household_id and schedule.household is not None:
            household_label = _google_calendar_household_label(schedule)
            if household_label:
                lines.append(f"{prefix}関連する家: {household_label}")
        return lines
    lines: list[str] = []
    is_generic_other_event = _google_calendar_is_generic_other_event(schedule)
    subject_label = _google_calendar_subject_label(schedule)
    if subject_label and (
        not is_generic_other_event or _google_calendar_generic_other_person_label(schedule)
    ):
        lines.append(f"{prefix}故人: {subject_label}")
    service_label = _google_calendar_service_label(schedule)
    if service_label:
        lines.append(f"{prefix}{_google_calendar_service_field_label(schedule)}: {service_label}")
    if not is_generic_other_event:
        kaimyo_label = _google_calendar_kaimyo_label(schedule)
        if kaimyo_label:
            lines.append(f"{prefix}{_google_calendar_kaimyo_field_label()}: {kaimyo_label}")
        death_date_label = _google_calendar_death_date_label(schedule)
        if death_date_label:
            lines.append(f"{prefix}命日: {death_date_label}")
        planned_death_date_label = _google_calendar_planned_death_date_label(schedule)
        if planned_death_date_label:
            lines.append(f"{prefix}予定命日: {planned_death_date_label}")
    household_label = _google_calendar_household_label(schedule)
    if household_label:
        lines.append(f"{prefix}戸主: {household_label}")
    return lines

def _google_calendar_edit_urls(schedule: ServiceSchedule) -> list[tuple[str, str]]:
    if _google_calendar_is_temple_event(schedule):
        if not schedule.pk:
            return []
        suffix = reverse("office:edit_temple_event", kwargs={"event_id": schedule.pk})
        link_label = "予定リンク"
    else:
        household_id = (schedule.household_uid or "").strip()
        event_id = (schedule.schedule_uid or "").strip()
        if not household_id or not event_id:
            return []
        path = reverse("office:edit_service_schedule", args=[household_id, event_id])
        query = {}
        source_table = (schedule.source_table or "").strip()
        if source_table:
            query["source_table"] = source_table
        suffix = f"{path}?{urlencode(query)}" if query else path
        link_label = "法要リンク"
    internal_base_url = google_calendar_service.google_calendar_base_url()
    external_base_url = google_calendar_service.google_calendar_external_base_url()
    urls: list[tuple[str, str]] = []
    if internal_base_url:
        urls.append(("内部", f"{internal_base_url}{suffix}"))
    if external_base_url and external_base_url != internal_base_url:
        urls.append(("外部", f"{external_base_url}{suffix}"))
    if len(urls) == 1:
        return [(link_label, urls[0][1])]
    return [(f"{link_label}({label})", url) for label, url in urls]


def _google_calendar_payload_fingerprint(
    *,
    sync_key: str,
    schedule: ServiceSchedule,
    member_schedule_ids: list[int],
    payload: dict | None,
) -> str:
    normalized_payload = payload or {}
    digest_input = {
        "sync_key": sync_key,
        "status": schedule.status,
        "scheduled_date": schedule.scheduled_date.isoformat() if schedule.scheduled_date else "",
        "scheduled_time": schedule.scheduled_time.isoformat() if schedule.scheduled_time else "",
        "completed_on": schedule.completed_on.isoformat() if schedule.completed_on else "",
        "target_date": schedule.target_date.isoformat() if schedule.target_date else "",
        "location": (schedule.location or "").strip(),
        "service_label": (schedule.service_label or "").strip(),
        "household_name_snapshot": (schedule.household_name_snapshot or "").strip(),
        "member_schedule_ids": member_schedule_ids,
        "payload": normalized_payload,
    }
    payload_text = json.dumps(digest_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


def _google_calendar_event_temporal_mode(event: dict | None) -> str:
    if not isinstance(event, dict):
        return ""
    start = event.get("start")
    if not isinstance(start, dict):
        return ""
    if str(start.get("dateTime", "") or "").strip():
        return "timed"
    if str(start.get("date", "") or "").strip():
        return "all_day"
    return ""


def _google_calendar_effective_date(schedule: ServiceSchedule) -> date | None:
    if schedule.status == ServiceSchedule.Status.COMPLETED and schedule.completed_on is not None:
        return schedule.completed_on
    if schedule.scheduled_date is not None:
        return schedule.scheduled_date
    if schedule.target_date is not None:
        return schedule.target_date
    return None
