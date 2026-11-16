from __future__ import annotations

from . import runtime_shared, service_ledger_runtime
from .household_browser_runtime_shared import _runtime_timezone


def _runtime_module():
    from . import household_memorial_candidates_runtime

    return household_memorial_candidates_runtime


def _service_event_is_actual(event: dict) -> bool:
    return service_ledger_runtime._service_event_is_actual(event)


def _service_schedule_category_for_candidate_type(
    candidate_type: str | None,
    service_label: str | None = None,
) -> str:
    return service_ledger_runtime._service_schedule_category_for_candidate_type(
        candidate_type,
        service_label,
    )


def _candidate_can_record_with_funeral(
    candidate_type: str | None,
    service_label: str | None = None,
) -> bool:
    return service_ledger_runtime._candidate_can_record_with_funeral(
        candidate_type,
        service_label,
    )


def _effective_service_schedule_status(schedule) -> str:
    return service_ledger_runtime._effective_service_schedule_status(schedule)


def _effective_service_event_status(event: dict) -> str:
    return runtime_shared._clean_value(event.get("status"))


def _person_is_service_target(person) -> bool:
    return service_ledger_runtime._person_is_service_target(person)


def _attach_action_to_memorial_candidates(
    candidates: list[dict],
    events: list[dict] | None = None,
) -> list[dict]:
    runtime = _runtime_module()
    today = _runtime_timezone().localdate()
    events = events or []
    schedule_index: dict[tuple[str, str, str], dict] = {}
    for event in events:
        if not runtime._service_event_is_actual(event):
            continue
        person_id = runtime._clean_value(event.get("person_id"))
        label = runtime._clean_value(event.get("schedule_type"))
        target_date = runtime._clean_value(event.get("target_date"))
        if not person_id or not label:
            continue
        schedule_index.setdefault((person_id, label, target_date), event)
        schedule_index.setdefault((person_id, label, ""), event)

    decorated: list[dict] = []
    for item in candidates:
        person_id = runtime._clean_value(item.get("person_id"))
        label = runtime._clean_value(item.get("label"))
        target_date_text = runtime._clean_value(item.get("target_date"))
        target_date_value = runtime._parse_iso_date(target_date_text)
        candidate_type = runtime._clean_value(item.get("candidate_type"))
        category = runtime._service_schedule_category_for_candidate_type(candidate_type, label)
        can_record_with_funeral = runtime._candidate_can_record_with_funeral(
            candidate_type,
            label,
        )
        matched = schedule_index.get((person_id, label, target_date_text)) or schedule_index.get(
            (person_id, label, "")
        )
        if matched is None and (
            target_date_value is None or (target_date_value < today and label != "臨終勤行")
        ):
            decorated.append(
                {
                    **item,
                    "is_actionable": False,
                    "has_schedule": False,
                    "schedule_event_id": "",
                    "schedule_source_table": "",
                    "schedule_category": category,
                    "schedule_status_label": "",
                    "can_record_with_funeral": can_record_with_funeral,
                }
            )
            continue
        decorated.append(
            {
                **item,
                "is_actionable": True,
                "has_schedule": matched is not None,
                "schedule_event_id": matched.get("event_id", "") if matched else "",
                "schedule_source_table": matched.get("source_table", "") if matched else "",
                "schedule_category": category,
                "schedule_status_label": matched.get("status_label", "") if matched else "",
                "can_record_with_funeral": can_record_with_funeral and matched is None,
            }
        )
    return decorated


def build_household_rinju_records(memorial_members: list[dict], events: list[dict]) -> list[dict]:
    """Offer registration/edit through the forty-ninth day, independently of candidate filters."""
    today = _runtime_timezone().localdate()
    candidates = []
    for person in memorial_members:
        death_date = runtime_shared._parse_iso_date(person.get("death_date_iso"))
        if death_date is None or not person.get("person_id"):
            continue
        # The date of death is day one, so the forty-ninth day is 48 days later.
        if not 0 <= (today - death_date).days <= 48:
            continue
        candidates.append({
            "person_id": person["person_id"],
            "household_id": person.get("household_id", ""),
            "person_name": person.get("name", ""),
            "label": "臨終勤行", "candidate_type": "臨終勤行",
            "target_date": death_date.isoformat(),
        })
    return _attach_action_to_memorial_candidates(candidates, events)
