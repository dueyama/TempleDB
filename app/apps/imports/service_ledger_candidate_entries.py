from __future__ import annotations

from datetime import date

from .memorial_shared import _kijitsu_offset_days_from_label
from .models import ServiceSchedule
from .runtime_shared import _clean_value, _parse_iso_date, _search_text

SHONANUKA_OFFSET_DAYS = 6
MANCHUIN_OFFSET_DAYS = 48


def _service_schedule_category_for_candidate_type(
    candidate_type: str | None,
    service_label: str | None = None,
) -> str:
    normalized_type = _clean_value(candidate_type)
    normalized_label = _clean_value(service_label)
    if normalized_type == "初盆" or normalized_label == "初盆":
        return ServiceSchedule.Category.HATSUBON
    if normalized_type == "中陰":
        if _kijitsu_offset_days_from_label(normalized_label) == MANCHUIN_OFFSET_DAYS:
            return ServiceSchedule.Category.MEMORIAL
        return ServiceSchedule.Category.CHUIN
    if normalized_type == "葬儀" or normalized_label == "葬儀":
        return ServiceSchedule.Category.FUNERAL
    return ServiceSchedule.Category.MEMORIAL


def _candidate_can_record_with_funeral(
    candidate_type: str | None,
    service_label: str | None = None,
) -> bool:
    normalized_type = _clean_value(candidate_type)
    normalized_label = _clean_value(service_label)
    return (
        normalized_type == "中陰"
        and _kijitsu_offset_days_from_label(normalized_label) == SHONANUKA_OFFSET_DAYS
    )


def _service_ledger_candidate_matches(entry: dict, needle: str) -> bool:
    return any(
        needle in _search_text(value)
        for value in (
            entry.get("household_id"),
            entry.get("household_name"),
            entry.get("person_id"),
            entry.get("person_name"),
            entry.get("relationship"),
            entry.get("kaimyo"),
            entry.get("label"),
            entry.get("candidate_type"),
            entry.get("target_date"),
            entry.get("death_date"),
            entry.get("note"),
        )
    )


def _matching_actual_schedule_for_candidate(
    candidate: dict,
    schedules: list[ServiceSchedule],
) -> ServiceSchedule | None:
    from . import service_ledger_schedule_entries

    candidate_person_id = _clean_value(candidate.get("person_id"))
    candidate_label = _clean_value(candidate.get("label"))
    candidate_target_date = _parse_iso_date(candidate.get("target_date"))
    for schedule in schedules:
        if _clean_value(schedule.person_uid) != candidate_person_id:
            continue
        if (
            candidate_label not in {"臨終勤行", "通夜", "葬儀", "礼参"}
            and candidate_target_date
            and service_ledger_schedule_entries._resolved_service_schedule_target_date(schedule)
            == candidate_target_date
        ):
            return schedule
        if _clean_value(schedule.service_label) == candidate_label:
            return schedule
    return None


def _candidate_already_has_actual_schedule(candidate: dict, schedule_entries: list[dict]) -> bool:
    candidate_person_id = _clean_value(candidate.get("person_id"))
    candidate_label = _clean_value(candidate.get("label"))
    candidate_target_date = _clean_value(candidate.get("target_date"))
    candidate_type = _clean_value(candidate.get("candidate_type"))
    for schedule in schedule_entries:
        if _clean_value(schedule.get("person_id")) != candidate_person_id:
            continue
        if _clean_value(schedule.get("service_label")) == candidate_label:
            return True
        if (
            candidate_type == "初盆"
            and _clean_value(schedule.get("category")) == ServiceSchedule.Category.HATSUBON
        ):
            return True
        if candidate_label not in {"臨終勤行", "通夜", "葬儀", "礼参"} and candidate_target_date and _clean_value(schedule.get("target_date")) == candidate_target_date:
            return True
    return False


def _service_ledger_candidate_entry(
    candidate: dict,
    *,
    today: date,
    overdue_period_start: date,
) -> dict:
    target_date_value = _parse_iso_date(candidate.get("target_date"))
    candidate_type = _clean_value(candidate.get("candidate_type"))
    target_date = candidate.get("target_date", "")
    service_label = candidate.get("label", "")
    return {
        "event_id": f"candidate-{candidate.get('person_id', '')}-{target_date}-{candidate.get('label', '')}",
        "source_table": "calculated_memorial_candidate",
        "household_id": candidate.get("household_id", ""),
        "household_name": candidate.get("household_name", ""),
        "person_id": candidate.get("person_id", ""),
        "person_name": candidate.get("person_name", ""),
        "service_label": service_label,
        "service_label_compact": service_label,
        "category": "candidate",
        "category_label": candidate_type or "候補",
        "schedule_category": _service_schedule_category_for_candidate_type(
            candidate_type,
            service_label,
        ),
        "status": "candidate",
        "status_label": "未登録",
        "scheduled_date": target_date,
        "scheduled_date_value": target_date_value,
        "scheduled_time": "",
        "scheduled_time_sort": "",
        "target_date": target_date,
        "target_date_value": target_date_value,
        "completed_on": "",
        "completed_on_value": None,
        "location": "",
        "notes": candidate.get("note", ""),
        "notes_label": "計算メモ",
        "record_origin": "calculated",
        "record_origin_label": "その場計算",
        "note_count": 0,
        "payment_count": 0,
        "is_done": False,
        "is_today": target_date_value == today,
        "is_overdue": (
            target_date_value is not None
            and overdue_period_start <= target_date_value < today
        ),
        "is_candidate": True,
        "candidate_type": candidate_type,
        "candidate_label": candidate.get("label", ""),
        "relationship": candidate.get("relationship", ""),
        "kaimyo": candidate.get("kaimyo", ""),
        "death_date": candidate.get("death_date", ""),
        "linked_entries": [],
        "linked_group_count": 0,
        "can_record_with_funeral": _candidate_can_record_with_funeral(
            candidate_type,
            service_label,
        ),
    }
