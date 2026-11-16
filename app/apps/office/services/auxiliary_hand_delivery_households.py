from __future__ import annotations

from apps.imports import canonical_population
from apps.imports.auxiliary_generated_ids import (
    _next_generated_household_id,
    _next_generated_household_row_number,
)
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    Household,
    ImportBatch,
    LegacySource,
    Person,
)
from apps.imports.source_runtime import current_source_path

from .household_editing_core import (
    _next_generated_person_id,
    _normalize_generated_head_person_id,
    _normalize_household_head_name,
)
from .household_head_editing import (
    _next_household_head_person_id,
    _sync_household_head_snapshot_from_person,
)
from .record_history_snapshot import _serialize_person_record


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


def _replace_household_head_from_hand_delivery_entry(
    *,
    household: Household,
    entry: dict,
) -> tuple[Person, dict, bool]:
    replacement_name = (entry.get("head_name") or "").strip()
    if not replacement_name:
        raise ValueError("手配り名簿の氏名が空のため、戸主差し替えできません。")

    normalized_name = _normalize_household_head_name(replacement_name)
    canonical_population.canonical_provenance_import_batch(
        source_id=household.legacy_source_id,
    )
    candidates = list(
        household.persons.filter(deleted_at__isnull=True).order_by("person_uid", "id")
    )
    current_matches = [
        person
        for person in candidates
        if _normalize_household_head_name(person.name) == normalized_name
        and person.family_category == FAMILY_CATEGORY_CURRENT
    ]
    if len(current_matches) > 1:
        raise ValueError("同名の現在帳 person が複数あるため、戸主差し替えできません。")
    if current_matches:
        person = current_matches[0]
        before_data = _serialize_person_record(person)
        person.name = replacement_name
        person.family_category = FAMILY_CATEGORY_CURRENT
        person.is_deceased = False
        if person.person_uid.startswith("head-"):
            person = _normalize_generated_head_person_id(person)
        person.clear_memorial_fields()
        person.save()
        person.sync_legacy_deceased_profile()
        return person, before_data, False

    generated_person_id = _next_generated_person_id(household.batch)
    person = Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="auxiliary_hand_delivery_head",
        source_row_number=entry.get("row_number") or household.source_row_number,
        legacy_pk_text=generated_person_id,
        person_uid=generated_person_id,
        legacy_household_id=household.household_uid,
        name=replacement_name,
        kana="",
        relationship_label="",
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note="",
        is_deceased=False,
        raw_record={
            "家族ID": generated_person_id,
            "台帳ID": household.household_uid,
            "氏名": replacement_name,
            "ﾌﾘｶﾞﾅ": "",
            "〒": entry.get("postal_code", ""),
            "住所1": entry.get("address_line1", ""),
            "住所2": entry.get("address_line2", ""),
            "電話": entry.get("phone", ""),
            "続柄": "",
            "家族区分": FAMILY_CATEGORY_CURRENT,
        },
    )
    return person, {}, True


def _create_household_from_hand_delivery_entry(
    *,
    batch: ImportBatch,
    source_record: LegacySource,
    entry: dict,
) -> tuple[Household, Person]:
    source_mdb_file = str(
        current_source_path(source_record.source_id, legacy_file_path=source_record.file_path)
    )
    legacy_household_id = _next_generated_household_id(batch)
    source_row_number = _next_generated_household_row_number(batch)
    raw_household_record = {
        "台帳ID": legacy_household_id,
        "氏名": entry["head_name"],
        "ﾌﾘｶﾞﾅ": "",
        "〒": entry["postal_code"],
        "住所1": entry["address_line1"],
        "住所2": entry["address_line2"],
        "電話": entry["phone"],
    }
    household = Household.objects.create(
        batch=batch,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="auxiliary_hand_delivery_household",
        source_row_number=source_row_number,
        legacy_pk_text=legacy_household_id,
        household_uid=legacy_household_id,
        head_name=entry["head_name"],
        head_name_kana="",
        postal_code=entry["postal_code"],
        address_line1=entry["address_line1"],
        address_line2=entry["address_line2"],
        phone=entry["phone"],
        raw_record=raw_household_record,
    )
    legacy_person_id = _next_household_head_person_id(household)
    raw_person_record = {
        "家族ID": legacy_person_id,
        "台帳ID": legacy_household_id,
        "氏名": entry["head_name"],
        "ﾌﾘｶﾞﾅ": "",
        "〒": entry["postal_code"],
        "住所1": entry["address_line1"],
        "住所2": entry["address_line2"],
        "電話": entry["phone"],
        "続柄": "戸主",
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    head_person = Person.objects.create(
        batch=batch,
        household=household,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="auxiliary_hand_delivery_household_head",
        source_row_number=source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=legacy_household_id,
        name=entry["head_name"],
        kana="",
        relationship_label="戸主",
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note="",
        is_deceased=False,
        raw_record=raw_person_record,
    )
    household_updates = _sync_household_head_snapshot_from_person(
        household=household,
        head_person=head_person,
    )
    if household_updates:
        household.save(update_fields=[*household_updates, "updated_at"])
    return household, head_person
