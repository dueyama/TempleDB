from __future__ import annotations

from django.db import transaction

from apps.imports import canonical_population
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)

from . import district_authority
from .district_history import record_district_change, serialize_district
from .household_editing_core import _household_display_head_name, _resolved_household_head_person

SERVICE_LINK_LOOKBACK_DAYS = 366

SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS = 2

SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS = 10

LINKED_GROUP_SHARED_FIELDS = [
    "scheduled_date",
    "scheduled_time",
    "completed_on",
    "location",
    "status",
    "notes",
    "external_calendar_ref",
]


def district_profile_for_person(source_id: str, person: Person) -> HouseholdProfile | None:
    return district_authority.district_profile_for_person(source_id, person)


def clear_district_officer_flags_for_household(
    source_id: str,
    household: Household,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> list[Person]:
    return district_authority.clear_district_officer_flags_for_household(
        source_id,
        household,
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
    return district_authority.assign_district_officer_to_person(
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
    return district_authority.district_officer_people_for_batch(source_id, batch=batch)


def district_officer_people_by_district(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> dict[int, list[tuple[Person, HouseholdProfile]]]:
    return district_authority.district_officer_people_by_district(source_id, batch=batch)


def _district_officer_choices(source_id: str, district: District | None) -> list[tuple[str, str]]:
    if district is None:
        return []
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    household_ids = list(
        HouseholdProfile.objects.filter(
            source__source_id=source_id,
            district=district,
            delivery_method=HOUSEHOLD_DELIVERY_DISTRICT,
        ).values_list("household_uid", flat=True)
    )
    if not household_ids:
        return []
    rows = list(
        Person.objects.select_related("household")
        .filter(
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            household__household_uid__in=household_ids,
        )
        .order_by(
            "household__head_person__kana",
            "household__head_person__name",
            "kana",
            "name",
            "person_uid",
        )
    )
    choices = []
    for person in rows:
        household = person.household
        if household is None:
            continue
        key = f"{source_id}:{household.household_uid}:{person.person_uid}"
        person_name = (person.name or "").strip() or person.person_uid
        household_name = _household_display_head_name(household)
        choices.append(
            (
                key,
                f"{person_name} / 戸主 {household_name} / 台帳ID {household.household_uid} / 家族ID {person.person_uid}",
            )
        )
    return choices


def _district_officer_person_for_district(source_id: str, district: District) -> Person | None:
    return district_authority.district_officer_person_for_district(source_id, district)


def _sync_person_district_officer_flag(
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    if person.is_district_officer and not district_authority.person_can_be_district_officer(
        person.legacy_source_id,
        person,
    ):
        district_authority.clear_district_officer_flag_for_person(
            person.legacy_source_id,
            person,
            editor_label=editor_label,
            change_note=change_note or "地区所属・送付区分・家族区分の変更に伴う解除",
        )


def _clear_district_officer_for_district(
    source_id: str,
    district: District,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    district_authority.clear_district_officer_flags_for_district(
        source_id,
        district,
        editor_label=editor_label,
        change_note=change_note,
    )


def _assign_district_officer_to_person(
    district: District,
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    del district
    district_authority.assign_district_officer_to_person(
        person.legacy_source_id,
        person,
        editor_label=editor_label,
        change_note=change_note,
    )


@transaction.atomic
def _ensure_district_from_hand_delivery_entry(
    entry: dict,
    *,
    source_id: str,
    editor_label: str = "system",
    change_note: str = "",
) -> District:
    district_name = (entry.get("district_name") or "").strip()
    if not district_name:
        raise ValueError("手配り名簿の地区名が空のため、地区を決められません。")
    district, _created = District.objects.get_or_create(
        name=district_name,
        defaults={
            "short_name": district_name,
            "sort_order": int(entry.get("sort_order") or 100),
        },
    )
    before_district = {} if _created else serialize_district(district)
    update_fields: list[str] = []
    desired_sort_order = int(entry.get("sort_order") or district.sort_order or 100)
    if district.short_name != district_name:
        district.short_name = district_name
        update_fields.append("short_name")
    if desired_sort_order and district.sort_order != desired_sort_order:
        district.sort_order = desired_sort_order
        update_fields.append("sort_order")
    if update_fields:
        district.save(update_fields=[*update_fields, "updated_at"])
    record_district_change(
        district,
        source_id=source_id,
        before_data=before_district,
        editor_label=editor_label,
        change_note=change_note or "手配り名簿の照合から地区情報を反映",
    )
    return district


def _assign_district_officer_to_household(
    district: District,
    household: Household,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    person = _resolved_household_head_person(household)
    if person is not None:
        _assign_district_officer_to_person(
            district,
            person,
            editor_label=editor_label,
            change_note=change_note,
        )
    return


def _refresh_district_officer_name_snapshots(household: Household) -> None:
    del household


def _refresh_district_officer_name_snapshots_for_person(person: Person) -> None:
    del person
