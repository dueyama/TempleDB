from __future__ import annotations

from .models import FAMILY_CATEGORY_LABELS, FAMILY_CATEGORY_MEMORIAL, Person
from .runtime_shared import _search_text


def _service_target_person_entry(person: Person) -> dict:
    household_name = person.household.display_head_name() if person.household_id else ""
    death_date = person.death_date.strftime("%Y-%m-%d") if person.death_date else ""
    return {
        "household_id": person.household.household_uid,
        "household_name": household_name,
        "person_id": person.person_uid,
        "person_name": person.name,
        "kana": person.kana,
        "relationship": person.relationship_label,
        "kaimyo": person.kaimyo,
        "death_date": death_date,
        "family_category_label": FAMILY_CATEGORY_LABELS.get(person.family_category, person.family_category),
    }


def _person_is_service_target(person: Person) -> bool:
    return bool(
        person.name
        and (
            person.family_category == FAMILY_CATEGORY_MEMORIAL
            or person.is_deceased
            or person.has_memorial_details()
        )
    )


def _service_target_person_matches(entry: dict, needle: str) -> bool:
    return any(
        needle in _search_text(value)
        for value in (
            entry.get("household_id"),
            entry.get("household_name"),
            entry.get("person_id"),
            entry.get("person_name"),
            entry.get("kana"),
            entry.get("relationship"),
            entry.get("kaimyo"),
            entry.get("death_date"),
            entry.get("family_category_label"),
        )
    )
