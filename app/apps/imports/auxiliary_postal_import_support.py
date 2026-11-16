from __future__ import annotations

from .auxiliary_generated_ids import (
    _next_generated_household_id,
    _next_generated_household_row_number,
    _next_generated_person_id,
)
from .ledger_categories import ledger_category_label, normalize_ledger_category_code
from .models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_POSTAL,
    LEDGER_CATEGORY_WOMENS_ASSOCIATION,
    Household,
    HouseholdProfile,
    ImportBatch,
    LegacySource,
    Person,
)
from .runtime_shared import _clean_value
from .source_runtime import current_source_path

POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION = {
    "F": LEDGER_CATEGORY_WOMENS_ASSOCIATION,
}


def _normalize_ledger_category_code(value: str | None) -> str:
    return normalize_ledger_category_code(value)


def _ledger_category_label(value: str | None) -> str:
    return ledger_category_label(value)


def _postal_imported_ledger_category(classification: str | None) -> str:
    return POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION.get(_clean_value(classification), "")


def _is_postal_imported_category(classification: str | None) -> bool:
    return bool(_postal_imported_ledger_category(classification))


def _create_postal_import_household(
    *,
    batch: ImportBatch,
    source_record: LegacySource,
    entry: dict,
) -> Household:
    source_mdb_file = str(
        current_source_path(source_record.source_id, legacy_file_path=source_record.file_path)
    )
    legacy_household_id = _next_generated_household_id(batch)
    source_row_number = _next_generated_household_row_number(batch)
    ledger_category = _postal_imported_ledger_category(entry.get("classification"))
    ledger_label = _ledger_category_label(ledger_category)
    raw_household_record = {
        "台帳ID": legacy_household_id,
        "氏名": entry["head_name"],
        "ﾌﾘｶﾞﾅ": "",
        "〒": entry["postal_code"],
        "住所1": entry["address_line1"],
        "住所2": entry["address_line2"],
        "電話": entry["phone"],
        "台帳区分": ledger_label,
        "郵送名簿区分": _clean_value(entry.get("classification")),
    }
    household = Household.objects.create(
        batch=batch,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="auxiliary_postal_household",
        source_row_number=source_row_number,
        legacy_pk_text=legacy_household_id,
        household_uid=legacy_household_id,
        head_name=entry["head_name"],
        head_name_kana="",
        postal_code=entry["postal_code"],
        address_line1=entry["address_line1"],
        address_line2=entry["address_line2"],
        phone=entry["phone"],
        ledger_category=ledger_category,
        raw_record=raw_household_record,
    )
    legacy_person_id = _next_generated_person_id(batch)
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
        "郵送名簿区分": _clean_value(entry.get("classification")),
    }
    head_person = Person.objects.create(
        batch=batch,
        household=household,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="auxiliary_postal_household_head",
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
    household.head_person = head_person
    household.save(update_fields=["head_person", "updated_at"])
    HouseholdProfile.objects.update_or_create(
        source=source_record,
        household_uid=household.household_uid,
        defaults={
            "delivery_method": HOUSEHOLD_DELIVERY_POSTAL,
            "district": None,
            "household_name_snapshot": household.display_head_name(),
            "household_name_kana_snapshot": household.display_head_name_kana(),
            "mailing_person_uid": "",
            "mailing_name": "",
            "mailing_postal_code": "",
            "mailing_address_line1": "",
            "mailing_address_line2": "",
            "mailing_phone": "",
        },
    )
    return household


def _ensure_postal_import_household_category(household: Household, classification: str | None) -> bool:
    desired_category = _postal_imported_ledger_category(classification)
    if not desired_category:
        return False
    desired_label = _ledger_category_label(desired_category)
    update_fields: list[str] = []
    if _normalize_ledger_category_code(household.ledger_category) != desired_category:
        household.ledger_category = desired_category
        update_fields.append("ledger_category")
    raw_record = dict(household.raw_record or {})
    if raw_record.get("台帳区分") != desired_label:
        raw_record["台帳区分"] = desired_label
        household.raw_record = raw_record
        update_fields.append("raw_record")
    if raw_record.get("郵送名簿区分") != _clean_value(classification):
        raw_record["郵送名簿区分"] = _clean_value(classification)
        household.raw_record = raw_record
        if "raw_record" not in update_fields:
            update_fields.append("raw_record")
    if not update_fields:
        return False
    household.save(update_fields=[*update_fields, "updated_at"])
    return True
