from __future__ import annotations

from .auxiliary_generated_ids import _next_generated_person_id
from .importer_parsing import _parse_legacy_date
from .kana import normalize_kana_storage
from .models import FAMILY_CATEGORY_CURRENT, Household, ImportBatch, Person
from .runtime_shared import _clean_value
from .source_runtime import current_source_path


def _runtime_module():
    from . import household_head_runtime

    return household_head_runtime


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


def create_manual_household_head_person_from_snapshot(household: Household) -> Person | None:
    snapshot_name = _clean_value(household.snapshot_head_name())
    if not snapshot_name:
        return None

    raw_record = household.raw_record or {}
    birth_date_raw = _clean_value(raw_record.get("生年月日"))
    parsed_birth_date = _parse_legacy_date(birth_date_raw)
    relationship_label = _clean_value(raw_record.get("続柄")) or "戸主"
    gender = _clean_value(raw_record.get("性別"))
    legacy_person_id = _next_generated_person_id(household.batch)
    snapshot_kana_raw = _clean_value(household.snapshot_head_name_kana())
    snapshot_kana = normalize_kana_storage(snapshot_kana_raw)
    raw_person_record = {
        "家族ID": legacy_person_id,
        "台帳ID": household.household_uid,
        "氏名": snapshot_name,
        "ﾌﾘｶﾞﾅ": snapshot_kana_raw,
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": relationship_label,
        "性別": gender,
        "生年月日": birth_date_raw,
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    return Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="manual_household_head",
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=snapshot_name,
        kana=snapshot_kana,
        relationship_label=relationship_label,
        family_category=FAMILY_CATEGORY_CURRENT,
        gender=gender,
        birth_date_raw=birth_date_raw,
        birth_date=parsed_birth_date.value,
        birth_date_parse_error=parsed_birth_date.error,
        person_note="",
        is_deceased=False,
        raw_record=raw_person_record,
    )


def create_virtual_household_head_person(household: Household) -> Person:
    runtime = _runtime_module()
    existing_virtual_head = (
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_deceased=False,
            source_table=runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
        )
        .order_by("id")
        .first()
    )
    if existing_virtual_head is not None:
        return existing_virtual_head

    virtual_head_number = runtime._next_virtual_household_head_number(household.batch)
    virtual_head_code = f"P{virtual_head_number}"
    legacy_person_id = _next_generated_person_id(household.batch)
    name = f"{runtime.VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX}{virtual_head_number}"
    raw_person_record = {
        "家族ID": legacy_person_id,
        "台帳ID": household.household_uid,
        "氏名": name,
        "ﾌﾘｶﾞﾅ": runtime.VIRTUAL_HOUSEHOLD_HEAD_KANA,
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": runtime.VIRTUAL_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
        "家族区分": FAMILY_CATEGORY_CURRENT,
        "仮戸主コード": virtual_head_code,
    }
    return Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table=runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=name,
        kana=runtime.VIRTUAL_HOUSEHOLD_HEAD_KANA,
        relationship_label=runtime.VIRTUAL_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL,
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note="実戸主未定のため作成した仮戸主",
        is_deceased=False,
        raw_record=raw_person_record,
    )


def _next_virtual_household_head_number(batch: ImportBatch) -> int:
    runtime = _runtime_module()
    max_number = 0
    prefix = runtime.VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX
    existing_names = Person.objects.filter(
        batch=batch,
        source_table=runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
    ).values_list("name", flat=True)
    for value in existing_names:
        cleaned = str(value or "").strip()
        if not cleaned.startswith(prefix):
            continue
        suffix = cleaned[len(prefix) :]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return max_number + 1
