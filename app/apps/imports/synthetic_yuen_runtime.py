from __future__ import annotations

from collections.abc import Mapping, Sequence

from .auxiliary_generated_ids import (
    _next_generated_household_id,
    _next_generated_household_row_number,
    _next_generated_person_id,
)
from .importer_parsing import _parse_int, _parse_legacy_date
from .kana import normalize_kana_storage
from .models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    HOUSEHOLD_DELIVERY_NONE,
    Household,
    HouseholdProfile,
    ImportBatch,
    LegacySource,
    Person,
)
from .runtime_shared import _clean_value
from .source_runtime import current_source_path
from .synthetic_household_support import (
    YUEN_HEAD_RELATIONSHIP_LABEL,
    YUEN_HOUSEHOLD_HEAD_SOURCE_TABLE,
    YUEN_HOUSEHOLD_NAME_PREFIX,
    YUEN_HOUSEHOLD_SOURCE_TABLE,
    YUEN_KANA_PREFIX,
    YUEN_MEMORIAL_PERSON_SOURCE_TABLE,
    YUEN_PERSON_NOTE,
    YUEN_UNKNOWN_BUCKET_KANA,
    YUEN_UNKNOWN_BUCKET_LABEL,
    _current_household_source_mdb_file,
    _sync_household_head_to_person,
    household_name_to_bucket_label,
    update_person_identity,
)


def yuen_import_key(row: Mapping[str, object]) -> str:
    return "::".join(
        (
            _clean_value(row.get("source_csv")),
            _clean_value(row.get("snapshot_id")),
            _clean_value(row.get("家族ID")),
        )
    )


def ensure_yuen_input_row(row: Mapping[str, object], *, csv_path: str, snapshot_id: str) -> dict[str, str]:
    normalized = {str(key): _clean_value(value) for key, value in row.items()}
    normalized.setdefault("source_csv", "")
    normalized.setdefault("snapshot_id", "")
    normalized.setdefault("classification", "")
    if not normalized["source_csv"]:
        normalized["source_csv"] = csv_path
    if not normalized["snapshot_id"]:
        normalized["snapshot_id"] = snapshot_id
    return normalized


def yuen_input_classification(row: Mapping[str, object]) -> str:
    return _clean_value(row.get("classification")) or "standalone_no_db_match"


def yuen_bucket_label_for_row(row: Mapping[str, object]) -> str:
    parsed = _parse_legacy_date(_clean_value(row.get("命日")))
    if parsed.value is None:
        return YUEN_UNKNOWN_BUCKET_LABEL
    decade = (parsed.value.year // 10) * 10
    return f"{decade}年代"


def yuen_bucket_kana(bucket_label: str) -> str:
    if bucket_label == YUEN_UNKNOWN_BUCKET_LABEL:
        return YUEN_UNKNOWN_BUCKET_KANA
    return f"{YUEN_KANA_PREFIX}じいんゆうえん{bucket_label.replace('年代', 'ねんだい')}"


def yuen_household_name(bucket_label: str) -> str:
    return f"{YUEN_HOUSEHOLD_NAME_PREFIX}{bucket_label}"


def yuen_household_maps(batch: ImportBatch) -> dict[str, Household]:
    households = (
        Household.objects.filter(
            batch=batch,
            deleted_at__isnull=True,
            source_table=YUEN_HOUSEHOLD_SOURCE_TABLE,
        )
        .select_related("head_person")
        .order_by("household_uid", "id")
    )
    return {household.snapshot_head_name(): household for household in households}


def yuen_memorial_people_by_import_key(batch: ImportBatch) -> dict[str, Person]:
    people = (
        Person.objects.filter(
            batch=batch,
            deleted_at__isnull=True,
            source_table=YUEN_MEMORIAL_PERSON_SOURCE_TABLE,
        )
        .select_related("household")
        .order_by("person_uid", "id")
    )
    keyed_people: dict[str, Person] = {}
    for person in people:
        key = yuen_import_key(person.raw_record or {})
        if key and key not in keyed_people:
            keyed_people[key] = person
    return keyed_people


def household_profile_map_for_households(
    source_id: str,
    household_ids: Sequence[str],
) -> dict[str, HouseholdProfile]:
    normalized_ids = [household_id for household_id in household_ids if household_id]
    if not normalized_ids:
        return {}
    profiles = HouseholdProfile.objects.filter(
        source__source_id=source_id,
        household_uid__in=normalized_ids,
    ).select_related("source")
    return {profile.household_uid: profile for profile in profiles}


def is_yuen_person_hidden_from_service_target_search(
    person: Person,
    profile: HouseholdProfile | None,
) -> bool:
    if person.source_table != YUEN_MEMORIAL_PERSON_SOURCE_TABLE:
        return False
    household = getattr(person, "household", None)
    if household is None or household.source_table != YUEN_HOUSEHOLD_SOURCE_TABLE:
        return False
    if not bool(person.memorial_notice_opt_out):
        return False
    if profile is None:
        return False
    return (
        profile.delivery_method == HOUSEHOLD_DELIVERY_NONE
        and bool(profile.general_notice_opt_out)
        and bool(profile.memorial_notice_opt_out)
    )


def get_or_create_yuen_household(
    *,
    batch: ImportBatch,
    bucket_label: str,
    existing_households_by_name: dict[str, Household],
) -> tuple[Household, bool]:
    household_name = yuen_household_name(bucket_label)
    existing = existing_households_by_name.get(household_name)
    if existing is not None:
        return existing, False

    source_mdb_file = str(
        current_source_path(batch.source.source_id, legacy_file_path=batch.source.file_path)
    )
    legacy_household_id = _next_generated_household_id(batch)
    source_row_number = _next_generated_household_row_number(batch)
    household = Household.objects.create(
        batch=batch,
        legacy_source_id=batch.source.source_id,
        source_mdb_file=source_mdb_file,
        source_export_batch=batch.prepared_snapshot_id,
        source_table=YUEN_HOUSEHOLD_SOURCE_TABLE,
        source_row_number=source_row_number,
        legacy_pk_text=legacy_household_id,
        household_uid=legacy_household_id,
        head_name=household_name,
        head_name_kana=yuen_bucket_kana(bucket_label),
        notes="",
        raw_record={
            "台帳ID": legacy_household_id,
            "氏名": household_name,
            "ﾌﾘｶﾞﾅ": yuen_bucket_kana(bucket_label),
        },
    )
    existing_households_by_name[household_name] = household
    return household, True


def get_or_create_yuen_household_head(household: Household) -> tuple[Person, bool]:
    head_name = household.snapshot_head_name() or household.display_head_name()
    head_kana = household.snapshot_head_name_kana() or yuen_bucket_kana(
        household_name_to_bucket_label(head_name)
    )
    existing = (
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            source_table=YUEN_HOUSEHOLD_HEAD_SOURCE_TABLE,
        )
        .order_by("id")
        .first()
    )
    if existing is not None:
        update_person_identity(
            existing,
            name=head_name,
            kana=head_kana,
            relationship_label=YUEN_HEAD_RELATIONSHIP_LABEL,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_deceased=False,
            person_note="",
            raw_record={
                "家族ID": existing.person_uid,
                "台帳ID": household.household_uid,
                "氏名": head_name,
                "ﾌﾘｶﾞﾅ": head_kana,
                "続柄": YUEN_HEAD_RELATIONSHIP_LABEL,
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
        source_table=YUEN_HOUSEHOLD_HEAD_SOURCE_TABLE,
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=head_name,
        kana=head_kana,
        relationship_label=YUEN_HEAD_RELATIONSHIP_LABEL,
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note="",
        is_deceased=False,
        raw_record={
            "家族ID": legacy_person_id,
            "台帳ID": household.household_uid,
            "氏名": head_name,
            "ﾌﾘｶﾞﾅ": head_kana,
            "続柄": YUEN_HEAD_RELATIONSHIP_LABEL,
            "家族区分": FAMILY_CATEGORY_CURRENT,
        },
    )
    _sync_household_head_to_person(household, person)
    return person, True


def get_or_create_yuen_memorial_person(
    *,
    household: Household,
    row: Mapping[str, object],
    existing_people_by_key: dict[str, Person],
) -> tuple[Person, bool]:
    key = yuen_import_key(row)
    existing = existing_people_by_key.get(key)
    if existing is not None:
        return existing, False

    death_date_raw = _clean_value(row.get("命日"))
    death_date = _parse_legacy_date(death_date_raw)
    age_at_death_raw = _clean_value(row.get("享年"))
    age_at_death = _parse_int(age_at_death_raw)
    legacy_person_id = _next_generated_person_id(household.batch)
    raw_record = {str(key): _clean_value(value) for key, value in row.items()}
    person = Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table=YUEN_MEMORIAL_PERSON_SOURCE_TABLE,
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=_clean_value(row.get("氏名")),
        kana=normalize_kana_storage(_clean_value(row.get("ﾌﾘｶﾞﾅ"))),
        relationship_label=_clean_value(row.get("続柄")),
        family_category=FAMILY_CATEGORY_MEMORIAL,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note=YUEN_PERSON_NOTE,
        is_deceased=True,
        death_date_raw=death_date_raw,
        death_date=death_date.value,
        death_date_parse_error=death_date.error,
        kaimyo=_clean_value(row.get("戒名")),
        kaimyo_kana="",
        age_at_death_raw=age_at_death_raw,
        age_at_death=age_at_death,
        age_unit="歳" if age_at_death_raw else "",
        legacy_hatsubon_flag="",
        hatsubon_flag=None,
        memorial_notice_opt_out=True,
        deceased_note=_clean_value(row.get("故人備考")),
        memorial_payload={
            "relationship": _clean_value(row.get("続柄")),
            "yuen_import_key": key,
        },
        raw_record=raw_record,
    )
    person.sync_legacy_deceased_profile()
    existing_people_by_key[key] = person
    return person, True


def ensure_yuen_household_profile(
    *,
    source_record: LegacySource,
    household: Household,
) -> HouseholdProfile:
    profile, _created = HouseholdProfile.objects.get_or_create(
        source=source_record,
        household_uid=household.household_uid,
    )
    update_fields: list[str] = []
    if profile.delivery_method != HOUSEHOLD_DELIVERY_NONE:
        profile.delivery_method = HOUSEHOLD_DELIVERY_NONE
        update_fields.append("delivery_method")
    if profile.general_notice_opt_out is not True:
        profile.general_notice_opt_out = True
        update_fields.append("general_notice_opt_out")
    if profile.memorial_notice_opt_out is not True:
        profile.memorial_notice_opt_out = True
        update_fields.append("memorial_notice_opt_out")
    if update_fields:
        profile.save(update_fields=[*update_fields, "updated_at"])
    return profile


__all__ = [
    "ensure_yuen_household_profile",
    "ensure_yuen_input_row",
    "get_or_create_yuen_household",
    "get_or_create_yuen_household_head",
    "get_or_create_yuen_memorial_person",
    "household_profile_map_for_households",
    "is_yuen_person_hidden_from_service_target_search",
    "yuen_bucket_kana",
    "yuen_bucket_label_for_row",
    "yuen_household_maps",
    "yuen_household_name",
    "yuen_import_key",
    "yuen_input_classification",
    "yuen_memorial_people_by_import_key",
]
