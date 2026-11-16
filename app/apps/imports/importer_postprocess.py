from __future__ import annotations

from .importer_parsing import _clean_text, _parse_legacy_date
from .kana import normalize_kana_for_match, normalize_kana_storage
from .models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)
from .source_runtime import current_source_path


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


def _copy_district_officer_flags_from_previous_batch(*, batch: ImportBatch) -> dict:
    previous_batch = (
        ImportBatch.objects.filter(
            source=batch.source,
            scope=batch.scope,
            status=ImportBatch.Status.SUCCEEDED,
        )
        .exclude(pk=batch.pk)
        .order_by("-finished_at", "-created_at", "-id")
        .first()
    )
    summary = {
        "source_batch_id": previous_batch.prepared_snapshot_id if previous_batch is not None else "",
        "copied_count": 0,
        "skipped_missing_person_count": 0,
        "skipped_ineligible_count": 0,
        "conflict_district_count": 0,
        "conflict_district_names": [],
    }
    if previous_batch is None:
        return summary

    Person.objects.filter(batch=batch, is_district_officer=True).update(is_district_officer=False)
    previous_people = list(
        Person.objects.filter(
            batch=previous_batch,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_district_officer=True,
        ).order_by("person_uid", "id")
    )
    if not previous_people:
        return summary

    target_people_by_legacy_id = {
        person.person_uid: person
        for person in Person.objects.select_related("household")
        .filter(
            batch=batch,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
        )
        .order_by("person_uid", "id")
    }
    target_profiles = {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.select_related("district").filter(
            source=batch.source,
            household_uid__in=[
                person.household.household_uid
                for person in target_people_by_legacy_id.values()
            ],
        )
    }

    candidates_by_district: dict[int, dict[int, Person]] = {}
    for previous_person in previous_people:
        target_person = target_people_by_legacy_id.get(previous_person.person_uid)
        if target_person is None:
            summary["skipped_missing_person_count"] += 1
            continue
        profile = target_profiles.get(target_person.household.household_uid)
        if (
            profile is None
            or profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
            or profile.district_id is None
        ):
            summary["skipped_ineligible_count"] += 1
            continue
        candidates_by_district.setdefault(profile.district_id, {})[target_person.pk] = target_person

    for district_id, people_by_pk in candidates_by_district.items():
        candidates = list(people_by_pk.values())
        if len(candidates) != 1:
            summary["conflict_district_count"] += 1
            district_name = (
                target_profiles.get(candidates[0].legacy_household_id).district.name
                if candidates
                and target_profiles.get(candidates[0].legacy_household_id) is not None
                and target_profiles.get(candidates[0].legacy_household_id).district_id
                else str(district_id)
            )
            summary["conflict_district_names"].append(district_name)
            continue
        person = candidates[0]
        person.is_district_officer = True
        person.save(update_fields=["is_district_officer", "updated_at"])
        summary["copied_count"] += 1
    return summary


def _assign_imported_household_head_people(*, households, batch: ImportBatch) -> None:
    next_person_number = _next_generated_numeric_person_number(batch)
    for household in households:
        match = _match_imported_household_head_person(household)
        if match is None:
            next_person_number, match = _create_imported_household_head_person(
                household,
                next_person_number=next_person_number,
            )
        household.head_person = match
        household.save(update_fields=["head_person", "updated_at"])


def _match_imported_household_head_person(household: Household) -> Person | None:
    head_name = _normalize_imported_head_name(household.snapshot_head_name())
    if not head_name:
        return None
    head_kana = normalize_kana_for_match(household.snapshot_head_name_kana())
    candidates = list(
        household.persons.filter(batch=household.batch, deleted_at__isnull=True).order_by("person_uid", "id")
    )
    exact_name_matches = [
        person for person in candidates if _normalize_imported_head_name(person.name) == head_name
    ]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1 and head_kana:
        kana_matches = [
            person
            for person in exact_name_matches
            if normalize_kana_for_match(person.kana) == head_kana
        ]
        if len(kana_matches) == 1:
            return kana_matches[0]
    return None


def _create_imported_household_head_person(
    household: Household,
    *,
    next_person_number: int,
) -> tuple[int, Person]:
    raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
    birth_date_raw = _clean_text(raw_record.get("生年月日"))
    birth_date = _parse_legacy_date(birth_date_raw)
    generated_person_id = str(next_person_number)
    raw_person_record = {
        "家族ID": generated_person_id,
        "台帳ID": household.household_uid,
        "氏名": household.snapshot_head_name(),
        "ﾌﾘｶﾞﾅ": household.snapshot_head_name_kana(),
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "ＦＡＸ": household.fax,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": _clean_text(raw_record.get("続柄")),
        "性別": _clean_text(raw_record.get("性別")),
        "生年月日": birth_date_raw,
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    person = Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="generated_household_head",
        source_row_number=household.source_row_number,
        legacy_pk_text=generated_person_id,
        person_uid=generated_person_id,
        legacy_household_id=household.household_uid,
        name=household.snapshot_head_name(),
        kana=normalize_kana_storage(household.snapshot_head_name_kana()),
        relationship_label=_clean_text(raw_record.get("続柄")),
        family_category=FAMILY_CATEGORY_CURRENT,
        gender=_clean_text(raw_record.get("性別")),
        birth_date_raw=birth_date_raw,
        birth_date=birth_date.value,
        birth_date_parse_error=birth_date.error,
        person_note="",
        is_deceased=False,
        raw_record=raw_person_record,
    )
    return next_person_number + 1, person


def _next_generated_numeric_person_number(batch: ImportBatch) -> int:
    max_numeric = 0
    for value in Person.objects.filter(batch=batch).values_list("person_uid", flat=True):
        if str(value).isdigit():
            max_numeric = max(max_numeric, int(str(value)))
    return max_numeric + 1


def _normalize_imported_head_name(value: str | None) -> str:
    return "".join(_clean_text(value).replace(" ", "").replace("\u3000", "").split())
