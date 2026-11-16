from __future__ import annotations

from apps.core.services.contact_normalization import (
    normalize_contact_text,
    normalize_phone_digits,
    normalize_postal_code_digits,
)
from apps.core.services.role_badges import role_badges_for_person

from .models import Household, Person
from .role_roster_rows import build_person_role_roster_rows
from .runtime_shared import _clean_value


def _hand_delivery_household_candidate_payload(household: Household) -> dict:
    return {
        "household_id": household.household_uid,
        "name": household.display_head_name(),
        "kana": household.display_head_name_kana(),
        "postal_code": household.postal_code,
        "address_line1": household.address_line1,
        "address_line2": household.address_line2,
        "phone": household.phone,
    }


def _monto_sodai_candidate_payload(person: Person) -> dict:
    household = person.household
    return {
        "person_name": _clean_value(person.name) or person.person_uid,
        "person_id": person.person_uid,
        "household_id": household.household_uid if household is not None else "",
        "household_name": household.display_head_name() if household is not None else "",
        "postal_code": household.postal_code if household is not None else "",
        "address_line1": household.address_line1 if household is not None else "",
        "address_line2": household.address_line2 if household is not None else "",
        "phone": household.phone if household is not None else "",
    }


def _monto_sodai_candidates_for_entry(entry: dict, candidates: list[Person]) -> list[Person]:
    narrowed = list(candidates)
    if len(narrowed) <= 1:
        return narrowed

    normalized_postal_code = normalize_postal_code_digits(entry.get("postal_code"))
    if normalized_postal_code:
        postal_matches = [
            person
            for person in narrowed
            if normalize_postal_code_digits(
                person.household.postal_code if person.household is not None else ""
            )
            == normalized_postal_code
        ]
        if postal_matches:
            narrowed = postal_matches
    if len(narrowed) <= 1:
        return narrowed

    normalized_phone = normalize_phone_digits(entry.get("phone"))
    if normalized_phone:
        phone_matches = [
            person
            for person in narrowed
            if normalize_phone_digits(person.household.phone if person.household is not None else "")
            == normalized_phone
        ]
        if phone_matches:
            narrowed = phone_matches
    if len(narrowed) <= 1:
        return narrowed

    entry_address = normalize_contact_text(
        "".join(
            filter(
                None,
                [
                    _clean_value(entry.get("address_line1")),
                    _clean_value(entry.get("address_line2")),
                ],
            )
        )
    )
    if entry_address:
        address_matches = []
        for person in narrowed:
            household = person.household
            candidate_address = normalize_contact_text(
                "".join(
                    filter(
                        None,
                        [
                            household.address_line1 if household is not None else "",
                            household.address_line2 if household is not None else "",
                        ],
                    )
                )
            )
            if not candidate_address:
                continue
            if candidate_address == entry_address or candidate_address.endswith(entry_address) or entry_address.endswith(candidate_address):
                address_matches.append(person)
        if address_matches:
            narrowed = address_matches
    return narrowed


def _role_badges_for_person(person: Person) -> list[str]:
    return role_badges_for_person(person)


def _build_person_role_roster_rows(source_id: str, people: list[Person]) -> list[dict]:
    return build_person_role_roster_rows(source_id, people)
