from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population, model_households
from .model_households import safe_display_head_name
from .models import (
    FAMILY_CATEGORY_MEMORIAL,
    HOUSEHOLD_DELIVERY_POSTAL,
    Household,
    HouseholdProfile,
    Person,
    ServiceSchedule,
)
from .quality_runtime_shared import _runtime_timezone
from .runtime_shared import (
    _clean_value,
    _int_sort,
    _normalize_same_name_text,
    _sort_text,
)


def _build_postal_non_head_recipient_search_entries(
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    candidates = _postal_non_head_recipient_candidates(
        source_id=source_id,
        latest_batch=latest_batch,
    )
    entries: list[dict] = []
    for candidate in candidates:
        profile = candidate["profile"]
        household = candidate["household"]
        head_name = candidate["head_name"]
        mailing_person = candidate["mailing_person"]
        recipient_name = candidate["recipient_name"]
        address_parts = [
            part
            for part in [
                _clean_value(profile.mailing_postal_code),
                _clean_value(profile.mailing_address_line1),
                _clean_value(profile.mailing_address_line2),
            ]
            if part
        ]
        phone = _clean_value(profile.mailing_phone)
        detail_bits = [f"現在戸主: {head_name}"]
        if address_parts:
            if profile.mailing_postal_code:
                detail_bits.append(
                    f"送付先: 〒{profile.mailing_postal_code} {' '.join(address_parts[1:])}".strip()
                )
            else:
                detail_bits.append(f"送付先: {' '.join(address_parts)}")
        if phone:
            detail_bits.append(f"電話: {phone}")
        entries.append(
            {
                "household_id": household.household_uid,
                "household_name": head_name,
                "person_id": mailing_person.person_uid if mailing_person is not None else "",
                "person_name": recipient_name,
                "kana": mailing_person.kana if mailing_person is not None else "",
                "relationship": mailing_person.relationship_label
                if mailing_person is not None
                else "郵送先",
                "kaimyo": "",
                "death_date": "",
                "age_at_death": "",
                "age_unit": "歳",
                "note": " / ".join(detail_bits),
                "status_label": "戸主以外に郵送",
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["household_name"]),
            _sort_text(item["person_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _postal_non_head_recipient_candidates(
    *,
    source_id: str | None = None,
    latest_batch=None,
    canonical_population_checked: bool = False,
) -> list[dict]:
    if not source_id or latest_batch is None:
        return []
    del latest_batch
    try:
        if not canonical_population_checked:
            canonical_population.canonical_provenance_import_batch(source_id=source_id)
        profiles = list(
            HouseholdProfile.objects.filter(
                source__source_id=source_id,
                delivery_method=HOUSEHOLD_DELIVERY_POSTAL,
            ).order_by("household_uid", "id")
        )
        profile_household_uids = {
            profile.household_uid for profile in profiles
        }
        households = {
            household.household_uid: household
            for household in Household.objects.select_related("head_person").filter(
                deleted_at__isnull=True,
                household_uid__in=profile_household_uids,
            )
        }
        household_people: dict[str, list[Person]] = {}
        mailing_people = {}
        for person in (
            Person.objects.select_related("household")
            .filter(
                deleted_at__isnull=True,
                household__deleted_at__isnull=True,
                household__household_uid__in=households,
            )
            .order_by("household__household_uid", "person_uid", "id")
        ):
            household_uid = person.household.household_uid
            household_people.setdefault(household_uid, []).append(person)
            mailing_people.setdefault(
                (household_uid, person.person_uid),
                person,
            )
    except (OperationalError, ProgrammingError):
        return []

    candidates: list[dict] = []
    for profile in profiles:
        household = households.get(profile.household_uid)
        if household is None:
            continue
        head_name = model_households.bulk_safe_display_head_name(
            household,
            household_people.get(profile.household_uid, []),
        )
        mailing_person = mailing_people.get(
            (profile.household_uid, profile.mailing_person_uid)
        )
        recipient_name = _clean_value(
            mailing_person.name if mailing_person is not None else ""
        ) or _clean_value(profile.mailing_name)
        if not recipient_name:
            continue
        if _normalize_same_name_text(recipient_name) == _normalize_same_name_text(head_name):
            continue
        candidates.append(
            {
                "profile": profile,
                "household": household,
                "head_name": head_name,
                "mailing_person": mailing_person,
                "recipient_name": recipient_name,
            }
        )
    return candidates


def _build_active_people_in_deleted_households_search_entries(
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    if not source_id or latest_batch is None:
        return []
    del latest_batch
    try:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
        people = list(
            Person.objects.select_related("household", "deceased_profile")
            .filter(
                deleted_at__isnull=True,
                household__deleted_at__isnull=False,
            )
            .order_by("household__household_uid", "person_uid", "id")
        )
    except (OperationalError, ProgrammingError):
        return []

    entries: list[dict] = []
    runtime_timezone = _runtime_timezone()
    for person in people:
        household = person.household
        household_name = safe_display_head_name(household) or household.household_uid
        household_deleted_at = (
            runtime_timezone.localtime(household.deleted_at)
            if household.deleted_at is not None
            else None
        )
        member_type_label = (
            "過去帳"
            if person.family_category == FAMILY_CATEGORY_MEMORIAL or person.has_memorial_details()
            else "現在帳"
        )
        note_bits = [
            "家は削除済み",
            f"種別: {member_type_label}",
            f"戸主表示: {household_name}",
        ]
        if household_deleted_at is not None:
            note_bits.append(f"家削除日時: {household_deleted_at:%Y-%m-%d %H:%M}")
        if _clean_value(household.deletion_note):
            note_bits.append(f"家削除メモ: {household.deletion_note}")
        entries.append(
            {
                "household_id": person.household.household_uid,
                "household_name": household_name,
                "person_id": person.person_uid,
                "person_name": person.name,
                "kana": person.kana,
                "relationship": person.relationship_label,
                "kaimyo": person.kaimyo if person.has_memorial_details() else "",
                "death_date": person.death_date_raw
                or (person.death_date.isoformat() if person.death_date else ""),
                "age_at_death": (
                    person.age_at_death_raw
                    or (str(person.age_at_death) if person.age_at_death is not None else "")
                ),
                "age_unit": person.age_unit or "歳",
                "note": " / ".join(note_bits),
                "status_label": "家は削除済み",
                "household_deleted": True,
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["household_name"]),
            _sort_text(item["person_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _build_deleted_head_person_household_search_entries(
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    if not source_id or latest_batch is None:
        return []
    del latest_batch
    try:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
        households = list(
            Household.objects.select_related("head_person")
            .filter(
                deleted_at__isnull=True,
                head_person__isnull=False,
                head_person__deleted_at__isnull=False,
            )
            .order_by("household_uid")
        )
        active_people = list(
            Person.objects.select_related("household").filter(
                household__household_uid__in=[
                    household.household_uid for household in households
                ],
                deleted_at__isnull=True,
            ).order_by("household__household_uid", "person_uid", "id")
        )
    except (OperationalError, ProgrammingError):
        return []

    active_people_by_household: dict[str, list[Person]] = {}
    for person in active_people:
        active_people_by_household.setdefault(person.household.household_uid, []).append(person)

    runtime_timezone = _runtime_timezone()
    entries: list[dict] = []
    for household in households:
        head_person = household.head_person
        if head_person is None or head_person.deleted_at is None:
            continue
        members = active_people_by_household.get(household.household_uid, [])
        current_count = sum(
            1
            for member in members
            if member.family_category != FAMILY_CATEGORY_MEMORIAL and not member.is_deceased
        )
        memorial_count = len(members) - current_count
        head_person_deleted_at = runtime_timezone.localtime(head_person.deleted_at)
        note_bits = [
            "戸主参照が削除済み person",
            f"家の構成: 現在帳 {current_count} 人 / 過去帳 {memorial_count} 人",
        ]
        note_bits.append(f"戸主person削除日時: {head_person_deleted_at:%Y-%m-%d %H:%M}")
        if _clean_value(head_person.deletion_note):
            note_bits.append(f"戸主person削除メモ: {head_person.deletion_note}")
        entries.append(
            {
                "household_id": household.household_uid,
                "household_name": safe_display_head_name(household) or household.household_uid,
                "person_id": head_person.person_uid,
                "person_name": head_person.name,
                "kana": head_person.kana,
                "relationship": head_person.relationship_label,
                "kaimyo": head_person.kaimyo if head_person.has_memorial_details() else "",
                "death_date": (
                    head_person.death_date_raw
                    or (head_person.death_date.isoformat() if head_person.death_date else "")
                ),
                "age_at_death": (
                    head_person.age_at_death_raw
                    or (
                        str(head_person.age_at_death)
                        if head_person.age_at_death is not None
                        else ""
                    )
                ),
                "age_unit": head_person.age_unit or "歳",
                "note": " / ".join(note_bits),
                "status_label": "削除済み person が戸主",
                "allow_household_delete": True,
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["household_name"]),
            _sort_text(item["person_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _build_legacy_schedule_search_entries(
    dataset: dict,
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    if dataset.get("data_backend") == "db" and latest_batch is not None:
        del latest_batch
        try:
            if not source_id:
                return []
            canonical_population.canonical_provenance_import_batch(source_id=source_id)
            schedules = list(
                ServiceSchedule.objects.select_related("household", "person")
                .filter(
                    deleted_at__isnull=True,
                    record_origin=ServiceSchedule.Origin.IMPORTED,
                )
                .order_by(
                    "service_label",
                    "scheduled_date",
                    "household_uid",
                    "schedule_uid",
                    "id",
                )
            )
        except (OperationalError, ProgrammingError):
            schedules = []
        entries = []
        for schedule in schedules:
            household_name = (
                safe_display_head_name(schedule.household)
                if schedule.household_id
                else schedule.household_name_snapshot
            ) or (schedule.household_name_snapshot or "")
            person_name = (
                schedule.person.name
                if schedule.person_id
                else (schedule.person_name_snapshot or schedule.subject_name)
            )
            entries.append(
                {
                    "result_kind": "schedule",
                    "household_id": schedule.household_uid,
                    "household_name": household_name or "",
                    "event_id": schedule.schedule_uid,
                    "person_id": schedule.person_uid,
                    "person_name": person_name or "",
                    "kana": schedule.person.kana if schedule.person_id else "",
                    "relationship": schedule.person.relationship_label
                    if schedule.person_id
                    else "",
                    "service_label": schedule.service_label or "",
                    "status_label": schedule.get_status_display(),
                    "scheduled_date": schedule.scheduled_date.strftime("%Y-%m-%d")
                    if schedule.scheduled_date
                    else "",
                    "target_date": schedule.target_date.strftime("%Y-%m-%d")
                    if schedule.target_date
                    else "",
                    "location": schedule.location,
                    "source_table": schedule.source_table,
                    "source_type_label": schedule.get_record_origin_display(),
                    "note": schedule.notes,
                }
            )
        return entries

    entries: list[dict] = []
    for detail in dataset["household_details"].values():
        for schedule in detail.get("events", []):
            if _clean_value(schedule.get("record_origin")) != ServiceSchedule.Origin.IMPORTED:
                continue
            entries.append(
                {
                    "result_kind": "schedule",
                    "household_id": schedule.get("household_id")
                    or detail["summary"]["household_id"],
                    "household_name": schedule.get("household_name")
                    or detail["summary"].get("name", ""),
                    "event_id": schedule.get("event_id", ""),
                    "person_id": schedule.get("person_id", ""),
                    "person_name": schedule.get("person_name") or schedule.get("subject_name", ""),
                    "kana": schedule.get("person_kana", ""),
                    "relationship": schedule.get("relationship", ""),
                    "service_label": schedule.get("service_label")
                    or schedule.get("schedule_type", ""),
                    "status_label": schedule.get("status_label") or "旧予定",
                    "scheduled_date": schedule.get("scheduled_date", ""),
                    "target_date": schedule.get("target_date", ""),
                    "location": schedule.get("location", ""),
                    "source_table": schedule.get("source_table", ""),
                    "source_type_label": schedule.get("record_origin_label", ""),
                    "note": schedule.get("notes", ""),
                }
            )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["service_label"]),
            _sort_text(item["scheduled_date"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _sort_text(item["event_id"]),
        ),
    )
