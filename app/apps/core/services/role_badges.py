from __future__ import annotations

from . import tenant_policy


def role_badges_for_person(person) -> list[str]:
    role_labels = tenant_policy.role_labels()
    badges: list[str] = []
    if person.is_district_officer:
        badges.append(role_labels["district_officer"])
    if person.is_responsible_officer:
        badges.append(role_labels["responsible_officer"])
    if person.is_monto_sodai:
        badges.append(role_labels["monto_sodai"])
    return badges


__all__ = ["role_badges_for_person"]
