from __future__ import annotations

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

from .household_head_editing import (
    _next_household_head_person_id,
    _sync_household_head_snapshot_from_person,
)


def create_manual_household(
    *,
    batch: ImportBatch,
    source_record: LegacySource,
    form_data: dict,
) -> tuple[Household, Person]:
    source_mdb_file = str(
        current_source_path(source_record.source_id, legacy_file_path=source_record.file_path)
    )
    legacy_household_id = _next_generated_household_id(batch)
    source_row_number = _next_generated_household_row_number(batch)
    head_name = (form_data.get("head_name") or "").strip()
    head_name_kana = (form_data.get("head_name_kana") or "").strip()
    head_gender = (form_data.get("head_gender") or "").strip()
    postal_code = (form_data.get("postal_code") or "").strip()
    address_line1 = (form_data.get("address_line1") or "").strip()
    address_line2 = (form_data.get("address_line2") or "").strip()
    address_line3 = (form_data.get("address_line3") or "").strip()
    phone = (form_data.get("phone") or "").strip()
    mobile = (form_data.get("mobile") or "").strip()
    email = (form_data.get("email") or "").strip()
    ledger_category = (form_data.get("ledger_category") or "").strip()
    notes = (form_data.get("notes") or "").strip()
    raw_household_record = {
        "台帳ID": legacy_household_id,
        "氏名": head_name,
        "ﾌﾘｶﾞﾅ": head_name_kana,
        "〒": postal_code,
        "住所1": address_line1,
        "住所2": address_line2,
        "住所3": address_line3,
        "電話": phone,
        "携帯": mobile,
        "Email": email,
        "台帳区分": ledger_category,
        "備考": notes,
    }
    household = Household.objects.create(
        batch=batch,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="manual_household",
        source_row_number=source_row_number,
        legacy_pk_text=legacy_household_id,
        household_uid=legacy_household_id,
        head_name=head_name,
        head_name_kana=head_name_kana,
        postal_code=postal_code,
        address_line1=address_line1,
        address_line2=address_line2,
        address_line3=address_line3,
        phone=phone,
        mobile=mobile,
        email=email,
        ledger_category=ledger_category,
        notes=notes,
        raw_record=raw_household_record,
    )
    legacy_person_id = _next_household_head_person_id(household)
    raw_person_record = {
        "家族ID": legacy_person_id,
        "台帳ID": legacy_household_id,
        "氏名": head_name,
        "ﾌﾘｶﾞﾅ": head_name_kana,
        "〒": postal_code,
        "住所1": address_line1,
        "住所2": address_line2,
        "住所3": address_line3,
        "電話": phone,
        "携帯": mobile,
        "Email": email,
        "続柄": "戸主",
        "性別": "" if head_gender == "未決定" else head_gender,
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    head_person = Person.objects.create(
        batch=batch,
        household=household,
        legacy_source_id=source_record.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="manual_household_head",
        source_row_number=source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=legacy_household_id,
        name=head_name,
        kana=head_name_kana,
        relationship_label="戸主",
        family_category=FAMILY_CATEGORY_CURRENT,
        gender=head_gender,
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
        household.save(update_fields=[*dict.fromkeys(household_updates), "updated_at"])
    return household, head_person


__all__ = ["create_manual_household"]
