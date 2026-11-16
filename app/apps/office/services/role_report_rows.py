from __future__ import annotations

from apps.core.services.role_badges import role_badges_for_person
from apps.imports.models import Person
from apps.imports.role_roster_rows import build_person_role_roster_rows


def _role_badges_for_person(person: Person) -> list[str]:
    return role_badges_for_person(person)


def _build_person_role_roster_rows(source_id: str, people: list[Person]) -> list[dict]:
    return build_person_role_roster_rows(source_id, people)


__all__ = ["_build_person_role_roster_rows", "_role_badges_for_person"]
