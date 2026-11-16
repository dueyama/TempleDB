from __future__ import annotations

from apps.core.services.kana import normalize_kana_for_match
from apps.imports.model_households import safe_display_head_name, safe_display_head_name_kana
from apps.imports.models import (
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
    VisitNote,
)


def _resolved_household_head_person(household) -> Person | None:
    return household.resolve_head_person()


def _household_display_head_name(household) -> str:
    return safe_display_head_name(household)


def _household_display_head_name_kana(household) -> str:
    return safe_display_head_name_kana(household)


def _person_for_edit(person_pk: int) -> Person:
    return Person.objects.select_related("household", "deceased_profile").get(pk=person_pk)


def _clean_household_head_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_household_head_name(value: str | None) -> str:
    return "".join(_clean_household_head_value(value).replace(" ", "").replace("\u3000", "").split())


def _matching_household_head_people(household) -> list[Person]:
    if household.head_person_id and getattr(household, "head_person", None) is not None:
        if household.head_person.deleted_at is None:
            return [household.head_person]
    head_name = _normalize_household_head_name(household.snapshot_head_name())
    if not head_name:
        return []
    head_kana = normalize_kana_for_match(household.snapshot_head_name_kana())
    candidates = list(
        household.persons.filter(batch=household.batch, deleted_at__isnull=True).order_by(
            "person_uid",
            "id",
        )
    )
    exact_name_matches = [
        person for person in candidates if _normalize_household_head_name(person.name) == head_name
    ]
    if len(exact_name_matches) <= 1:
        return exact_name_matches
    if head_kana:
        kana_matches = [
            person
            for person in exact_name_matches
            if normalize_kana_for_match(person.kana) == head_kana
        ]
        if kana_matches:
            return kana_matches
    return exact_name_matches


def _apply_household_contact_defaults_to_person(person: Person, household) -> None:
    raw_record = dict(person.raw_record or {})
    raw_record["〒"] = household.postal_code
    raw_record["住所1"] = household.address_line1
    raw_record["住所2"] = household.address_line2
    raw_record["住所3"] = household.address_line3
    raw_record["電話"] = household.phone
    raw_record["携帯"] = household.mobile
    raw_record["Email"] = household.email
    raw_record["家族区分"] = person.family_category
    person.raw_record = raw_record


def _next_generated_person_id(batch) -> str:
    max_numeric = 0
    for value in Person.objects.filter(batch=batch).values_list("person_uid", flat=True):
        if str(value).isdigit():
            max_numeric = max(max_numeric, int(str(value)))
    return str(max_numeric + 1)


def _normalize_generated_head_person_id(person: Person) -> Person:
    old_id = person.person_uid
    if not old_id.startswith("head-"):
        return person
    new_id = _next_generated_person_id(person.batch)
    person.person_uid = new_id
    person.legacy_pk_text = new_id
    raw_record = dict(person.raw_record or {})
    raw_record["家族ID"] = new_id
    person.raw_record = raw_record
    person.save(update_fields=["person_uid", "legacy_pk_text", "raw_record", "updated_at"])
    ServiceSchedule.objects.filter(person=person).update(person_uid=new_id)
    VisitNote.objects.filter(person=person).update(person_uid=new_id)
    OfferingPayment.objects.filter(person=person).update(person_uid=new_id)
    RecordEditLog.objects.filter(legacy_person_id=old_id).update(legacy_person_id=new_id)
    return person
