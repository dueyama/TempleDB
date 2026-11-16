from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.imports.models import Household, MemoTagAssignment

from .memo_search_shared import RESULT_KIND_DEFINITIONS, _excerpt


def _build_entry(
    *,
    content_type_id: int,
    object_id: int,
    field_name: str,
    note_type: str,
    note_label: str,
    title: str,
    text: str,
    updated_at: datetime,
    household_id: str,
    household_name: str,
    person_id: str,
    person_name: str,
    schedule_id: str,
    legacy_source_id: str,
    legacy_household_id: str,
    legacy_person_id: str,
    legacy_schedule_id: str,
    action_url: str,
    action_label: str,
    event_date: str = "",
    batch_snapshot_id: str = "",
    assignment_map: dict[tuple[int, int, str], list[MemoTagAssignment]] | None = None,
) -> dict[str, Any]:
    clean_text = (text or "").strip()
    key = (content_type_id, object_id, field_name)
    assignments = (assignment_map or {}).get(key, [])
    tags = [
        {
            "slug": assignment.tag.slug,
            "label": assignment.tag.label,
            "source_kind": assignment.source_kind,
        }
        for assignment in assignments
    ]
    return {
        "result_kind": "memo",
        "kind_label": RESULT_KIND_DEFINITIONS["memo"]["label"],
        "content_type_id": content_type_id,
        "object_id": object_id,
        "field_name": field_name,
        "note_type": note_type,
        "note_label": note_label,
        "title": (title or "").strip() or note_label,
        "text": clean_text,
        "excerpt": _excerpt(clean_text, length=220),
        "updated_at": updated_at,
        "updated_label": timezone.localtime(updated_at).strftime("%Y-%m-%d %H:%M"),
        "household_id": household_id or "",
        "household_name": household_name or "",
        "person_id": person_id or "",
        "person_name": person_name or "",
        "schedule_id": schedule_id or "",
        "legacy_source_id": legacy_source_id or "",
        "legacy_household_id": legacy_household_id or "",
        "legacy_person_id": legacy_person_id or "",
        "legacy_schedule_id": legacy_schedule_id or "",
        "action_url": action_url,
        "action_label": action_label,
        "tags": tags,
        "event_date": event_date or "",
        "batch_snapshot_id": batch_snapshot_id or "",
        "sort_key": (
            updated_at.timestamp(),
            (household_id or ""),
            (person_id or ""),
            (schedule_id or ""),
            note_type,
        ),
    }


def _safe_household_name(household: Household) -> str:
    try:
        return household.display_head_name()
    except Exception:
        return household.snapshot_head_name() or household.household_uid


__all__ = ["_build_entry", "_safe_household_name"]
