from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Household, Person


def sync_household_head_snapshot_from_person(
    *,
    household: Household,
    head_person: Person,
) -> list[str]:
    """Update the in-memory snapshot; callers own saving and change history."""
    update_fields: list[str] = []
    if household.head_person_id != head_person.pk:
        household.head_person = head_person
        update_fields.append("head_person")
    person_name = head_person.name or ""
    if household.snapshot_head_name() != person_name:
        household.head_name = person_name
        update_fields.append("raw_record")
    person_kana = head_person.kana or ""
    if household.snapshot_head_name_kana() != person_kana:
        household.head_name_kana = person_kana
        update_fields.append("raw_record")
    return update_fields
