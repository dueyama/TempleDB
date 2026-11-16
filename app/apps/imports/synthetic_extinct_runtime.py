from __future__ import annotations

from dataclasses import dataclass

from .auxiliary_generated_ids import _next_generated_person_id
from .household_head_runtime import VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE
from .models import FAMILY_CATEGORY_CURRENT, Household, Person
from .runtime_shared import _clean_value
from .synthetic_household_support import (
    EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
    EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE,
    EXTINCT_HOUSEHOLD_NOTE,
    _append_extinct_suffix,
    _best_extinct_household_base_identity,
    _current_household_source_mdb_file,
    _sync_household_head_to_person,
    extinct_kana,
    update_person_identity,
)


@dataclass(frozen=True)
class ExtinctHouseholdIdentity:
    base_name: str
    base_kana: str
    display_name: str
    display_kana: str


def resolve_extinct_household_identity(household: Household) -> ExtinctHouseholdIdentity:
    base_name, base_kana = _best_extinct_household_base_identity(household)
    display_name = _append_extinct_suffix(base_name)
    display_kana = extinct_kana(base_kana)
    return ExtinctHouseholdIdentity(
        base_name=base_name,
        base_kana=base_kana,
        display_name=display_name,
        display_kana=display_kana,
    )


def get_or_create_extinct_household_head(
    *,
    household: Household,
    identity: ExtinctHouseholdIdentity,
) -> tuple[Person, bool]:
    existing = (
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            source_table=EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE,
        )
        .order_by("id")
        .first()
    )
    if existing is not None:
        update_person_identity(
            existing,
            name=identity.display_name,
            kana=identity.display_kana,
            relationship_label=EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_deceased=False,
            person_note=EXTINCT_HOUSEHOLD_NOTE,
            raw_record={
                "家族ID": existing.person_uid,
                "台帳ID": household.household_uid,
                "氏名": identity.display_name,
                "ﾌﾘｶﾞﾅ": identity.display_kana,
                "続柄": EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
                "家族区分": FAMILY_CATEGORY_CURRENT,
            },
        )
        _sync_household_head_to_person(household, existing)
        return existing, False

    legacy_person_id = _next_generated_person_id(household.batch)
    person = Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table=EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE,
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=identity.display_name,
        kana=identity.display_kana,
        relationship_label=EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note=EXTINCT_HOUSEHOLD_NOTE,
        is_deceased=False,
        raw_record={
            "家族ID": legacy_person_id,
            "台帳ID": household.household_uid,
            "氏名": identity.display_name,
            "ﾌﾘｶﾞﾅ": identity.display_kana,
            "続柄": EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
            "家族区分": FAMILY_CATEGORY_CURRENT,
        },
    )
    _sync_household_head_to_person(household, person)
    return person, True


def active_real_current_people(household: Household) -> list[Person]:
    return list(
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_deceased=False,
        )
        .exclude(source_table__in={VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE, EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE})
        .order_by("person_uid", "id")
    )


def active_virtual_household_heads(household: Household) -> list[Person]:
    return list(
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            source_table=VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
        ).order_by("person_uid", "id")
    )


def append_household_note(household: Household, note_text: str) -> None:
    normalized = _clean_value(note_text)
    if not normalized:
        return
    existing_notes = [line.strip() for line in (household.notes or "").splitlines() if line.strip()]
    if normalized in existing_notes:
        return
    existing_notes.append(normalized)
    household.notes = "\n".join(existing_notes)


__all__ = [
    "ExtinctHouseholdIdentity",
    "active_real_current_people",
    "active_virtual_household_heads",
    "append_household_note",
    "get_or_create_extinct_household_head",
    "resolve_extinct_household_identity",
]
