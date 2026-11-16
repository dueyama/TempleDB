from __future__ import annotations

from datetime import date

from . import memorial_shared, service_ledger_runtime
from .models import ServiceSchedule
from .runtime_shared import _parse_iso_date


def _runtime_module():
    from . import memorial_notice_runtime

    return memorial_notice_runtime


def _memorial_notice_schedule_status(schedule: ServiceSchedule | None, target_date: date | None) -> str:
    if schedule is None:
        return "未記録"
    effective_status = service_ledger_runtime._effective_service_schedule_status(schedule)
    effective_date = schedule.completed_on or schedule.scheduled_date
    is_pre_served = (
        target_date is not None
        and effective_date is not None
        and effective_date < target_date
    )
    if effective_status == ServiceSchedule.Status.COMPLETED:
        return "取越済" if is_pre_served else "済"
    if effective_status == ServiceSchedule.Status.SCHEDULED:
        return "取越予定" if is_pre_served else "予定済"
    if effective_status == ServiceSchedule.Status.CANCELLED:
        return "中止"
    if effective_status == ServiceSchedule.Status.DEFERRED:
        return "見送り"
    return schedule.get_status_display()


def _memorial_notice_note(
    schedule: ServiceSchedule | None,
    target_date: date | None,
    linked_schedules_by_group: dict[str, list[ServiceSchedule]],
) -> str:
    runtime = _runtime_module()
    if schedule is None:
        return ""
    effective_date = schedule.completed_on or schedule.scheduled_date
    effective_date_text = effective_date.isoformat() if effective_date else ""
    linked_summary = runtime._memorial_notice_linked_summary(schedule, linked_schedules_by_group)
    is_pre_served = (
        target_date is not None
        and effective_date is not None
        and effective_date < target_date
    )
    if service_ledger_runtime._effective_service_schedule_status(schedule) != ServiceSchedule.Status.COMPLETED:
        return ""
    if linked_summary and effective_date_text:
        action = "取越にてお勤めいたしました" if is_pre_served else "お勤めいたしました"
        return f"{linked_summary} と一緒に {effective_date_text}に{action}。"
    if effective_date_text:
        action = "取越にてお勤めいたしました" if is_pre_served else "お勤めいたしました"
        return f"{effective_date_text}に{action}。"
    return ""


def _memorial_notice_linked_summary(
    schedule: ServiceSchedule,
    linked_schedules_by_group: dict[str, list[ServiceSchedule]],
) -> str:
    if not schedule.link_group_key:
        return ""
    linked = [
        item
        for item in linked_schedules_by_group.get(schedule.link_group_key, [])
        if item.pk != schedule.pk
    ]
    if not linked:
        return ""
    labels = [
        f"{item.subject_name or item.person_name_snapshot or item.person_uid} {item.service_label}"
        for item in linked[:3]
    ]
    suffix = " ほか" if len(linked) > 3 else ""
    return "、".join(labels) + suffix


def _build_memorial_notice_column(
    candidate: dict,
    schedules: list[ServiceSchedule],
    linked_schedules_by_group: dict[str, list[ServiceSchedule]],
) -> dict:
    runtime = _runtime_module()
    target_date = _parse_iso_date(candidate.get("target_date"))
    death_date = _parse_iso_date(candidate.get("death_date"))
    matched_schedule = service_ledger_runtime._matching_actual_schedule_for_candidate(candidate, schedules)
    status_label = runtime._memorial_notice_schedule_status(matched_schedule, target_date)
    return {
        "person_name": candidate.get("person_name", ""),
        "kaimyo": candidate.get("kaimyo", ""),
        "relationship": candidate.get("relationship", ""),
        "target_date_iso": candidate.get("target_date", ""),
        "target_date_wareki": memorial_shared._to_wareki_date_numeric(death_date)
        if death_date
        else candidate.get("death_date", ""),
        "label": candidate.get("label", ""),
        "zokumyo": runtime._memorial_notice_zokumyo_text(candidate),
        "status_label": status_label,
        "other_note": runtime._memorial_notice_note(matched_schedule, target_date, linked_schedules_by_group),
    }
