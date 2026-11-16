from __future__ import annotations

from .models import (
    District,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)
from .source_runtime import latest_succeeded_import_batch


def _office_module():
    from apps.office.services import district_authority

    return district_authority


def _district_officer_person_from_household(household: Household) -> Person | None:
    return _office_module()._district_officer_person_from_household(household)


def _district_profile_map_for_households(
    source_id: str,
    household_ids: list[str],
) -> dict[str, HouseholdProfile]:
    return _office_module()._district_profile_map_for_households(source_id, household_ids)


def district_profile_for_person(source_id: str, person: Person) -> HouseholdProfile | None:
    return _office_module().district_profile_for_person(source_id, person)


def person_can_be_district_officer(source_id: str, person: Person) -> bool:
    return _office_module().person_can_be_district_officer(source_id, person)


def clear_district_officer_flags_for_household(
    source_id: str,
    household: Household,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> list[Person]:
    return _office_module().clear_district_officer_flags_for_household(
        source_id,
        household,
        editor_label=editor_label,
        change_note=change_note,
    )


def clear_district_officer_flags_for_district(
    source_id: str,
    district: District,
    *,
    batch: ImportBatch | None = None,
    exclude_person_pk: int | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> list[Person]:
    return _office_module().clear_district_officer_flags_for_district(
        source_id,
        district,
        batch=batch,
        exclude_person_pk=exclude_person_pk,
        editor_label=editor_label,
        change_note=change_note,
    )


def assign_district_officer_to_person(
    source_id: str,
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    return _office_module().assign_district_officer_to_person(
        source_id,
        person,
        editor_label=editor_label,
        change_note=change_note,
    )


def district_officer_people_for_batch(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> list[tuple[Person, HouseholdProfile]]:
    return _office_module().district_officer_people_for_batch(source_id, batch=batch)


def district_officer_people_by_district(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> dict[int, list[tuple[Person, HouseholdProfile]]]:
    return _office_module().district_officer_people_by_district(source_id, batch=batch)


def district_officer_person_for_district(
    source_id: str,
    district: District,
    *,
    batch: ImportBatch | None = None,
) -> Person | None:
    return _office_module().district_officer_person_for_district(
        source_id,
        district,
        batch=batch,
    )


__all__ = [
    "_district_officer_person_from_household",
    "_district_profile_map_for_households",
    "assign_district_officer_to_person",
    "clear_district_officer_flags_for_district",
    "clear_district_officer_flags_for_household",
    "district_officer_people_by_district",
    "district_officer_people_for_batch",
    "district_officer_person_for_district",
    "district_profile_for_person",
    "latest_succeeded_import_batch",
    "person_can_be_district_officer",
]
