from __future__ import annotations

from .household_head_runtime import (
    VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX,
    VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
    sync_household_head_snapshot_from_person,
)
from .kana import normalize_kana_storage
from .models import Household, HouseholdHeadResolutionError, Person
from .runtime_shared import _clean_value
from .source_runtime import current_source_path

YUEN_HOUSEHOLD_SOURCE_TABLE = "synthetic_yuen_household"
YUEN_HOUSEHOLD_HEAD_SOURCE_TABLE = "synthetic_yuen_household_head"
YUEN_MEMORIAL_PERSON_SOURCE_TABLE = "synthetic_yuen_memorial_person"
YUEN_HEAD_RELATIONSHIP_LABEL = "有縁保持"
YUEN_PERSON_NOTE = "UTB002_家族 台帳IDなし有縁故人から作成"
YUEN_HOUSEHOLD_NAME_PREFIX = "寺院有縁 "
YUEN_KANA_PREFIX = "＊"
YUEN_UNKNOWN_BUCKET_LABEL = "命日不明"
YUEN_UNKNOWN_BUCKET_KANA = f"{YUEN_KANA_PREFIX}じいんゆうえんめいにちふめい"

EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE = "synthetic_extinct_household_head"
EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL = "絶家保持"
EXTINCT_HOUSEHOLD_NOTE = "絶家保持 household"
EXTINCT_HOUSEHOLD_NAME_SUFFIX = "（絶家）"
EXTINCT_HOUSEHOLD_KANA_FALLBACK = f"{YUEN_KANA_PREFIX}ぜっけ"

_EXTINCT_SYNTHETIC_SOURCE_TABLES = {
    VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
    EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE,
}


def household_name_to_bucket_label(name: str) -> str:
    cleaned = _clean_value(name)
    if cleaned.startswith(YUEN_HOUSEHOLD_NAME_PREFIX):
        return cleaned.removeprefix(YUEN_HOUSEHOLD_NAME_PREFIX) or YUEN_UNKNOWN_BUCKET_LABEL
    return YUEN_UNKNOWN_BUCKET_LABEL


def extinct_kana(base_kana: str) -> str:
    cleaned = _clean_value(base_kana)
    if cleaned.startswith(YUEN_KANA_PREFIX):
        return cleaned
    if cleaned:
        return f"{YUEN_KANA_PREFIX}{normalize_kana_storage(cleaned)}"
    return EXTINCT_HOUSEHOLD_KANA_FALLBACK


def _append_extinct_suffix(name: str) -> str:
    cleaned = _clean_value(name)
    if not cleaned:
        cleaned = ""
    if cleaned.endswith(EXTINCT_HOUSEHOLD_NAME_SUFFIX):
        return cleaned
    return f"{cleaned}{EXTINCT_HOUSEHOLD_NAME_SUFFIX}" if cleaned else EXTINCT_HOUSEHOLD_NAME_SUFFIX


def _best_extinct_household_base_identity(household: Household) -> tuple[str, str]:
    head_person = None
    try:
        head_person = household.resolve_head_person()
    except HouseholdHeadResolutionError:
        head_person = None
    if head_person is not None and head_person.source_table not in _EXTINCT_SYNTHETIC_SOURCE_TABLES:
        return (
            _clean_value(head_person.name) or household.household_uid,
            _clean_value(head_person.kana),
        )

    snapshot_name = _clean_value(household.snapshot_head_name())
    snapshot_kana = _clean_value(household.snapshot_head_name_kana())
    if snapshot_name and not _is_synthetic_snapshot_name(snapshot_name):
        return snapshot_name, snapshot_kana

    fallback_person = (
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
        )
        .exclude(source_table__in=_EXTINCT_SYNTHETIC_SOURCE_TABLES)
        .order_by("family_category", "person_uid", "id")
        .first()
    )
    if fallback_person is not None and _clean_value(fallback_person.name):
        return _clean_value(fallback_person.name), _clean_value(fallback_person.kana)

    if snapshot_name:
        return snapshot_name, snapshot_kana
    return household.household_uid, ""


def _is_synthetic_snapshot_name(name: str) -> bool:
    cleaned = _clean_value(name)
    return cleaned.startswith(VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX) or cleaned.endswith(
        EXTINCT_HOUSEHOLD_NAME_SUFFIX
    )


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


def _sync_household_head_to_person(household: Household, person: Person) -> None:
    update_fields = sync_household_head_snapshot_from_person(
        household=household,
        head_person=person,
    )
    update_fields.append("updated_at")
    household.save(update_fields=list(dict.fromkeys(update_fields)))


def update_person_identity(
    person: Person,
    *,
    name: str,
    kana: str,
    relationship_label: str,
    family_category: str,
    is_deceased: bool,
    person_note: str,
    raw_record: dict[str, str],
) -> None:
    update_fields: list[str] = []
    desired_values = {
        "name": name,
        "kana": kana,
        "relationship_label": relationship_label,
        "family_category": family_category,
        "is_deceased": is_deceased,
        "person_note": person_note,
        "raw_record": raw_record,
    }
    for field_name, expected in desired_values.items():
        if getattr(person, field_name) != expected:
            setattr(person, field_name, expected)
            update_fields.append(field_name)
    if update_fields:
        person.save(update_fields=[*update_fields, "updated_at"])


__all__ = [
    "EXTINCT_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL",
    "EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE",
    "EXTINCT_HOUSEHOLD_KANA_FALLBACK",
    "EXTINCT_HOUSEHOLD_NAME_SUFFIX",
    "EXTINCT_HOUSEHOLD_NOTE",
    "YUEN_HEAD_RELATIONSHIP_LABEL",
    "YUEN_HOUSEHOLD_HEAD_SOURCE_TABLE",
    "YUEN_HOUSEHOLD_NAME_PREFIX",
    "YUEN_HOUSEHOLD_SOURCE_TABLE",
    "YUEN_KANA_PREFIX",
    "YUEN_MEMORIAL_PERSON_SOURCE_TABLE",
    "YUEN_PERSON_NOTE",
    "YUEN_UNKNOWN_BUCKET_KANA",
    "YUEN_UNKNOWN_BUCKET_LABEL",
    "_append_extinct_suffix",
    "_best_extinct_household_base_identity",
    "_current_household_source_mdb_file",
    "_is_synthetic_snapshot_name",
    "_sync_household_head_to_person",
    "extinct_kana",
    "household_name_to_bucket_label",
    "update_person_identity",
]
