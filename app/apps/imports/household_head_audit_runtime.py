from __future__ import annotations

from . import canonical_population
from .district_authority import (
    _district_profile_map_for_households,
    district_officer_people_by_district,
)
from .kana import normalize_kana_for_match
from .models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)
from .runtime_shared import _clean_value, _normalize_same_name_text


def person_authority_audit(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> dict:
    target_batch = batch or canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    summary = {
        "source_id": source_id,
        "batch_uuid": str(target_batch.batch_uuid) if target_batch is not None else "",
        "prepared_snapshot_id": target_batch.prepared_snapshot_id if target_batch is not None else "",
        "head_name_mismatch_count": 0,
        "head_name_mismatches": [],
        "head_snapshot_drift_count": 0,
        "head_snapshot_drifts": [],
        "mailing_name_mismatch_count": 0,
        "mailing_name_mismatches": [],
        "district_officer_conflict_count": 0,
        "district_officer_conflicts": [],
        "district_officer_ineligible_count": 0,
        "district_officer_ineligible_people": [],
    }
    if target_batch is None:
        return summary

    households = list(
        Household.objects.select_related("head_person")
        .filter(batch=target_batch, deleted_at__isnull=True)
        .order_by("household_uid")
    )
    household_ids = [household.household_uid for household in households]
    head_name_mismatches: list[dict] = []
    for household in households:
        raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
        raw_name = _clean_value(raw_record.get("氏名"))
        display_name = _clean_value(household.display_head_name())
        if raw_name and _normalize_same_name_text(raw_name) != _normalize_same_name_text(display_name):
            head_name_mismatches.append(
                {
                    "household_id": household.household_uid,
                    "raw_head_name": raw_name,
                    "display_head_name": display_name,
                    "head_person_id": household.head_person.person_uid if household.head_person_id else "",
                }
            )
    summary["head_name_mismatch_count"] = len(head_name_mismatches)
    summary["head_name_mismatches"] = head_name_mismatches

    head_snapshot_drifts: list[dict] = []
    for household in households:
        resolved_head_person = household.resolve_head_person()
        if resolved_head_person is None:
            continue
        snapshot_name = _clean_value(household.snapshot_head_name())
        snapshot_kana = _clean_value(household.snapshot_head_name_kana())
        person_name = _clean_value(resolved_head_person.name)
        person_kana = _clean_value(resolved_head_person.kana)
        name_drift = _normalize_same_name_text(snapshot_name) != _normalize_same_name_text(person_name)
        kana_drift = normalize_kana_for_match(snapshot_kana) != normalize_kana_for_match(person_kana)
        if not name_drift and not kana_drift:
            continue
        head_snapshot_drifts.append(
            {
                "household_id": household.household_uid,
                "head_person_id": resolved_head_person.person_uid,
                "snapshot_head_name": snapshot_name,
                "person_name": person_name,
                "snapshot_head_kana": snapshot_kana,
                "person_kana": person_kana,
                "name_drift": name_drift,
                "kana_drift": kana_drift,
            }
        )
    summary["head_snapshot_drift_count"] = len(head_snapshot_drifts)
    summary["head_snapshot_drifts"] = head_snapshot_drifts

    current_people = list(
        Person.objects.select_related("household")
        .filter(batch=target_batch, deleted_at__isnull=True)
        .order_by("household__household_uid", "person_uid")
    )
    current_people_by_key = {
        (person.household.household_uid, _clean_value(person.person_uid)): person
        for person in current_people
    }
    mailing_name_mismatches: list[dict] = []
    for profile in (
        HouseholdProfile.objects.select_related("district")
        .filter(
            source__source_id=source_id,
            household_uid__in=household_ids,
        )
        .order_by("household_uid", "id")
    ):
        mailing_person_id = _clean_value(profile.mailing_person_uid)
        if not mailing_person_id:
            continue
        mailing_person = current_people_by_key.get((profile.household_uid, mailing_person_id))
        if mailing_person is None:
            continue
        mailing_name = _clean_value(profile.mailing_name)
        resolved_person_name = _clean_value(mailing_person.name)
        if mailing_name and _normalize_same_name_text(mailing_name) != _normalize_same_name_text(
            resolved_person_name
        ):
            mailing_name_mismatches.append(
                {
                    "household_id": profile.household_uid,
                    "mailing_person_id": mailing_person.person_uid,
                    "mailing_name": mailing_name,
                    "person_name": resolved_person_name,
                }
            )
    summary["mailing_name_mismatch_count"] = len(mailing_name_mismatches)
    summary["mailing_name_mismatches"] = mailing_name_mismatches

    district_conflicts: list[dict] = []
    districts_by_id = District.objects.in_bulk()
    for district_id, entries in district_officer_people_by_district(source_id, batch=target_batch).items():
        if len(entries) <= 1:
            continue
        district = districts_by_id.get(district_id)
        district_conflicts.append(
            {
                "district_id": district_id,
                "district_name": district.name if district is not None else "",
                "people": [
                    {
                        "household_id": person.household.household_uid,
                        "person_id": person.person_uid,
                        "person_name": _clean_value(person.name),
                    }
                    for person, _profile in entries
                ],
            }
        )
    summary["district_officer_conflict_count"] = len(district_conflicts)
    summary["district_officer_conflicts"] = district_conflicts

    flagged_people = list(
        Person.objects.select_related("household")
        .filter(
            batch=target_batch,
            deleted_at__isnull=True,
            is_district_officer=True,
        )
        .order_by("household__household_uid", "person_uid")
    )
    profile_map = _district_profile_map_for_households(
        source_id,
        [person.household.household_uid for person in flagged_people],
    )
    ineligible_people: list[dict] = []
    for person in flagged_people:
        profile = profile_map.get(person.household.household_uid)
        if person.family_category != FAMILY_CATEGORY_CURRENT:
            reason = "current person ではありません"
        elif profile is None:
            reason = "household profile がありません"
        elif profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT:
            reason = "地区所属ではありません"
        elif profile.district_id is None:
            reason = "所属地区が未設定です"
        else:
            continue
        ineligible_people.append(
            {
                "household_id": person.household.household_uid,
                "person_id": person.person_uid,
                "person_name": _clean_value(person.name),
                "reason": reason,
            }
        )
    summary["district_officer_ineligible_count"] = len(ineligible_people)
    summary["district_officer_ineligible_people"] = ineligible_people
    return summary
