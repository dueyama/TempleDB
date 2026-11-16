from __future__ import annotations

from typing import Any

from django.urls import reverse
from django.utils import timezone

from apps.imports.models import ImportBatch

from .memo_search_entry_support import _safe_household_name
from .memo_search_scope import _scoped_households, _scoped_people, _scoped_service_schedules
from .memo_search_shared import RESULT_KIND_DEFINITIONS, _date_to_text, _excerpt


def _entity_entries(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
    result_kinds: set[str] | None = None,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    target_kinds = result_kinds or set(RESULT_KIND_DEFINITIONS.keys())
    if "household" in target_kinds:
        households = _scoped_households(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).order_by("-updated_at", "-id")
        for household in households:
            household_name = _safe_household_name(household)
            body = " / ".join(
                value
                for value in [
                    household.address_line1,
                    household.address_line2,
                    household.phone,
                    household.email,
                ]
                if (value or "").strip()
            )
            entries.append(
                {
                    "result_kind": "household",
                    "kind_label": RESULT_KIND_DEFINITIONS["household"]["label"],
                    "note_type": "",
                    "note_label": "",
                    "title": household_name,
                    "text": body,
                    "excerpt": _excerpt(body) if body else "",
                    "updated_at": household.updated_at,
                    "updated_label": timezone.localtime(household.updated_at).strftime("%Y-%m-%d %H:%M"),
                    "household_id": household.household_uid,
                    "household_name": household_name,
                    "person_id": "",
                    "person_name": "",
                    "schedule_id": "",
                    "legacy_source_id": household.legacy_source_id,
                    "legacy_household_id": household.household_uid,
                    "legacy_person_id": "",
                    "legacy_schedule_id": "",
                    "action_url": reverse("office:household_browser")
                    + f"?household_id={household.household_uid}",
                    "action_label": "この家を開く",
                    "tags": [],
                    "event_date": "",
                    "batch_snapshot_id": household.batch.prepared_snapshot_id if household.batch_id else "",
                    "sort_key": (
                        household.updated_at.timestamp(),
                        household.household_uid,
                        "",
                        "",
                        "household",
                    ),
                }
            )

    if "person" in target_kinds:
        people = _scoped_people(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).order_by("-updated_at", "-id")
        for person in people:
            household_name = _safe_household_name(person.household)
            household_uid = person.household.household_uid
            body = " / ".join(
                value
                for value in [
                    person.kana,
                    person.relationship_label,
                    person.kaimyo,
                ]
                if (value or "").strip()
            )
            entries.append(
                {
                    "result_kind": "person",
                    "kind_label": RESULT_KIND_DEFINITIONS["person"]["label"],
                    "note_type": "",
                    "note_label": "",
                    "title": person.name,
                    "text": body,
                    "excerpt": _excerpt(body) if body else "",
                    "updated_at": person.updated_at,
                    "updated_label": timezone.localtime(person.updated_at).strftime("%Y-%m-%d %H:%M"),
                    "household_id": household_uid,
                    "household_name": household_name,
                    "person_id": person.person_uid,
                    "person_name": person.name,
                    "schedule_id": "",
                    "legacy_source_id": person.legacy_source_id,
                    "legacy_household_id": household_uid,
                    "legacy_person_id": person.person_uid,
                    "legacy_schedule_id": "",
                    "action_url": reverse(
                        "office:edit_person",
                        args=[household_uid, person.person_uid],
                    ),
                    "action_label": "この人を修正",
                    "tags": [],
                    "event_date": "",
                    "batch_snapshot_id": person.batch.prepared_snapshot_id if person.batch_id else "",
                    "sort_key": (
                        person.updated_at.timestamp(),
                        household_uid,
                        person.person_uid,
                        "",
                        "person",
                    ),
                }
            )

    if "schedule" in target_kinds:
        schedules = _scoped_service_schedules(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        )
        if date_from:
            schedules = schedules.filter(scheduled_date__gte=date_from)
        if date_to:
            schedules = schedules.filter(scheduled_date__lte=date_to)
        schedules = schedules.order_by("-updated_at", "-id")
        for schedule in schedules:
            household_name = (
                _safe_household_name(schedule.household)
                if schedule.household_id
                else (schedule.household_name_snapshot or schedule.household_uid)
            )
            person_name = (
                schedule.person.name
                if schedule.person_id
                else (schedule.person_name_snapshot or schedule.subject_name)
            )
            body = " / ".join(
                value
                for value in [
                    person_name,
                    schedule.location,
                    schedule.scheduled_date.isoformat() if schedule.scheduled_date else "",
                ]
                if (value or "").strip()
            )
            schedule_uid = schedule.schedule_uid
            if schedule.household_uid and schedule_uid:
                action_url = reverse(
                    "office:edit_service_schedule",
                    args=[schedule.household_uid, schedule_uid],
                )
                action_label = "この予定を修正"
            else:
                action_url = reverse("office:service_ledger")
                action_label = "法要台帳を開く"
            entries.append(
                {
                    "result_kind": "schedule",
                    "kind_label": RESULT_KIND_DEFINITIONS["schedule"]["label"],
                    "note_type": "",
                    "note_label": "",
                    "title": schedule.service_label,
                    "text": body,
                    "excerpt": _excerpt(body) if body else "",
                    "updated_at": schedule.updated_at,
                    "updated_label": timezone.localtime(schedule.updated_at).strftime("%Y-%m-%d %H:%M"),
                    "household_id": schedule.household_uid,
                    "household_name": household_name,
                    "person_id": schedule.person_uid,
                    "person_name": person_name,
                    "schedule_id": schedule_uid,
                    "legacy_source_id": schedule.legacy_source_id,
                    "legacy_household_id": schedule.household_uid,
                    "legacy_person_id": schedule.person_uid,
                    "legacy_schedule_id": schedule.schedule_uid,
                    "action_url": action_url,
                    "action_label": action_label,
                    "tags": [],
                    "event_date": _date_to_text(schedule.scheduled_date or schedule.target_date),
                    "batch_snapshot_id": (
                        schedule.related_batch.prepared_snapshot_id if schedule.related_batch_id else ""
                    ),
                    "sort_key": (
                        schedule.updated_at.timestamp(),
                        schedule.household_uid,
                        schedule.person_uid,
                        schedule_uid,
                        "schedule",
                    ),
                }
            )
    return entries


__all__ = ["_entity_entries"]
