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
    RecordEditLog,
)
from apps.imports.runtime_shared import _normalize_same_name_text

from .district_officer_rules import (
    district_profile_for_person as district_profile_for_person,
)
from .district_officer_rules import (
    person_can_be_district_officer as person_can_be_district_officer,
)
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_person_record


def _district_officer_person_from_household(household: Household) -> Person | None:
    if household.head_person_id:
        person = Person.objects.filter(pk=household.head_person_id, deleted_at__isnull=True).first()
        if person is not None:
            return person

    current_people = list(
        Person.objects.filter(
            deleted_at__isnull=True,
            household=household,
            family_category=FAMILY_CATEGORY_CURRENT,
        ).order_by("id")
    )
    if not current_people:
        current_people = list(
            Person.objects.filter(
                deleted_at__isnull=True,
                household=household,
            ).order_by("id")
        )
    if not current_people:
        return None

    normalized_head_name = _normalize_same_name_text(household.display_head_name())
    if normalized_head_name:
        matched_people = [
            person
            for person in current_people
            if _normalize_same_name_text(person.name) == normalized_head_name
        ]
        if len(matched_people) == 1:
            return matched_people[0]
    return current_people[0]


def _district_profile_map_for_households(
    source_id: str,
    household_ids: list[str],
) -> dict[str, HouseholdProfile]:
    if not household_ids:
        return {}
    return {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.select_related("district").filter(
            source__source_id=source_id,
            household_uid__in=household_ids,
        )
    }


def _set_district_officer_flag(
    person: Person,
    *,
    enabled: bool,
    district: District | None,
    editor_label: str,
    change_note: str,
    reason: str,
) -> bool:
    if person.is_district_officer == enabled:
        return False

    district_context = {
        "district_id": district.pk if district is not None else None,
        "district_name": district.name if district is not None else "",
    }
    before_data = _serialize_person_record(person)
    before_data["district_officer_context"] = district_context
    person.is_district_officer = enabled
    person.save(update_fields=["is_district_officer", "updated_at"])
    after_data = _serialize_person_record(person)
    after_data["district_officer_context"] = district_context
    district_label = f"（地区: {district.name}）" if district is not None else ""
    audit_note = f"{reason}{district_label}。"
    if (change_note or "").strip():
        audit_note = f"{audit_note} {change_note.strip()}"
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=person,
        before_data=before_data,
        after_data=after_data,
        editor_label=(editor_label or "").strip() or "system",
        change_note=audit_note,
    )
    return True


@transaction.atomic
def clear_district_officer_flag_for_person(
    source_id: str,
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> bool:
    profile = district_profile_for_person(source_id, person)
    return _set_district_officer_flag(
        person,
        enabled=False,
        district=profile.district if profile is not None else None,
        editor_label=editor_label,
        change_note=change_note,
        reason="地区役員解除",
    )


@transaction.atomic
def clear_district_officer_flags_for_household(
    source_id: str,
    household: Household,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> list[Person]:
    profile = (
        HouseholdProfile.objects.select_related("district")
        .filter(source__source_id=source_id, household_uid=household.household_uid)
        .first()
    )
    changed_people = list(
        household.persons.filter(
            deleted_at__isnull=True,
            is_district_officer=True,
        ).order_by("person_uid", "id")
    )
    for person in changed_people:
        _set_district_officer_flag(
            person,
            enabled=False,
            district=profile.district if profile is not None else None,
            editor_label=editor_label,
            change_note=change_note,
            reason="地区役員解除",
        )
    return changed_people


@transaction.atomic
def clear_district_officer_flags_for_district(
    source_id: str,
    district: District,
    *,
    batch: ImportBatch | None = None,
    exclude_person_pk: int | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> list[Person]:
    del batch
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
    queryset = Person.objects.filter(
        deleted_at__isnull=True,
        family_category=FAMILY_CATEGORY_CURRENT,
        household__household_uid__in=household_ids,
        is_district_officer=True,
    ).order_by("person_uid", "id")
    if exclude_person_pk is not None:
        queryset = queryset.exclude(pk=exclude_person_pk)
    changed_people = list(queryset)
    for person in changed_people:
        _set_district_officer_flag(
            person,
            enabled=False,
            district=district,
            editor_label=editor_label,
            change_note=change_note,
            reason="地区役員交代に伴う解除" if exclude_person_pk is not None else "地区役員解除",
        )
    return changed_people


@transaction.atomic
def assign_district_officer_to_person(
    source_id: str,
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    profile = district_profile_for_person(source_id, person)
    if (
        person.deleted_at is not None
        or person.family_category != FAMILY_CATEGORY_CURRENT
        or profile is None
        or profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
        or profile.district_id is None
    ):
        raise ValueError("地区所属の current person だけを地区役員にできます。")

    District.objects.select_for_update().get(pk=profile.district_id)
    cleared_people = clear_district_officer_flags_for_district(
        source_id,
        profile.district,
        batch=person.batch,
        exclude_person_pk=person.pk,
        editor_label=editor_label,
        change_note=change_note,
    )
    changed = _set_district_officer_flag(
        person,
        enabled=True,
        district=profile.district,
        editor_label=editor_label,
        change_note=change_note,
        reason="地区役員任命",
    )
    return {
        "district": profile.district,
        "changed": changed or bool(cleared_people),
        "cleared_people": cleared_people,
    }


def district_officer_people_for_batch(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> list[tuple[Person, HouseholdProfile]]:
    del batch
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    people = list(
        Person.objects.select_related("household")
        .filter(
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_district_officer=True,
        )
        .order_by(
            "household__head_person__kana",
            "household__head_person__name",
            "kana",
            "name",
            "person_uid",
        )
    )
    profile_map = _district_profile_map_for_households(
        source_id,
        [person.household.household_uid for person in people],
    )
    rows: list[tuple[Person, HouseholdProfile]] = []
    for person in people:
        profile = profile_map.get(person.household.household_uid)
        if (
            profile is None
            or profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
            or profile.district_id is None
        ):
            continue
        rows.append((person, profile))
    return rows


def district_officer_people_by_district(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> dict[int, list[tuple[Person, HouseholdProfile]]]:
    grouped: dict[int, list[tuple[Person, HouseholdProfile]]] = {}
    for person, profile in district_officer_people_for_batch(source_id, batch=batch):
        grouped.setdefault(profile.district_id, []).append((person, profile))
    return grouped


def district_officer_person_for_district(
    source_id: str,
    district: District,
    *,
    batch: ImportBatch | None = None,
) -> Person | None:
    matches = district_officer_people_by_district(source_id, batch=batch).get(district.id, [])
    if len(matches) != 1:
        return None
    return matches[0][0]


__all__ = [
    "_district_officer_person_from_household",
    "_district_profile_map_for_households",
    "assign_district_officer_to_person",
    "clear_district_officer_flag_for_person",
    "clear_district_officer_flags_for_district",
    "clear_district_officer_flags_for_household",
    "district_officer_people_by_district",
    "district_officer_people_for_batch",
    "district_officer_person_for_district",
    "district_profile_for_person",
    "person_can_be_district_officer",
]
