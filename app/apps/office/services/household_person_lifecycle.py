from __future__ import annotations

from apps.core.services.kana import normalize_kana_storage
from apps.imports.forms import GENDER_CHOICES, HouseholdHeadTransitionForm
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    Household,
    Person,
    RecordEditLog,
)
from apps.imports.source_runtime import current_source_path

from .household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _clean_household_head_value,
    _matching_household_head_people,
    _next_generated_person_id,
    _person_for_edit,
    _resolved_household_head_person,
)
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_person_record


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


def _person_memorial_transition_initial(person: Person) -> dict:
    relationship_label = (person.relationship_label or "").strip()
    if relationship_label in {"戸主", "本人"}:
        relationship_label = ""
    return {
        "registration_mode": HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL,
        "death_date_input": person.death_date.isoformat() if person.death_date else "",
        "kaimyo": person.kaimyo,
        "kaimyo_kana": person.kaimyo_kana,
        "age_at_death": person.age_at_death,
        "age_unit": person.age_unit or "歳",
        "relationship_label": relationship_label,
        "deceased_note": person.deceased_note,
        "funeral_scheduled_time": "10:00",
    }


def _household_head_memorial_transition_initial(household: Household) -> dict:
    head_person = _resolved_household_head_person(household)
    if head_person is None:
        matched_people = _matching_household_head_people(household)
        if len(matched_people) == 1:
            head_person = matched_people[0]
    if head_person is not None:
        return _person_memorial_transition_initial(head_person)
    raw_record = household.raw_record or {}
    relationship_label = _clean_household_head_value(raw_record.get("続柄"))
    if relationship_label in {"戸主", "本人"}:
        relationship_label = ""
    return {
        "registration_mode": HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL,
        "death_date_input": "",
        "kaimyo": "",
        "kaimyo_kana": "",
        "age_at_death": None,
        "age_unit": "歳",
        "relationship_label": relationship_label,
        "deceased_note": "",
        "funeral_scheduled_time": "10:00",
    }


def _register_person_memorial_transition(
    *,
    person: Person,
    household: Household,
    form_data: dict,
    editor_label: str,
    change_note: str,
) -> tuple[Person, RecordEditLog | None, RecordEditLog | None]:
    from .service_schedule_lifecycle import _create_funeral_service_schedule_for_person

    before_data = _serialize_person_record(person)
    death_date = form_data.get("death_date_input")
    relationship_label = (form_data.get("relationship_label") or "").strip()
    person.family_category = FAMILY_CATEGORY_MEMORIAL
    person.is_deceased = True
    person.relationship_label = relationship_label
    _apply_household_contact_defaults_to_person(person, household)
    raw_record = dict(person.raw_record or {})
    raw_record["家族区分"] = FAMILY_CATEGORY_MEMORIAL
    raw_record["命日"] = death_date.isoformat() if death_date else ""
    raw_record["戒名"] = (form_data.get("kaimyo") or "").strip()
    age_at_death = form_data.get("age_at_death")
    raw_record["享年"] = str(age_at_death) if age_at_death is not None else ""
    raw_record["故人備考"] = (form_data.get("deceased_note") or "").strip()
    person.death_date = death_date
    person.death_date_raw = death_date.isoformat() if death_date else ""
    person.death_date_parse_error = ""
    person.kaimyo = (form_data.get("kaimyo") or "").strip()
    person.kaimyo_kana = normalize_kana_storage((form_data.get("kaimyo_kana") or "").strip())
    person.age_at_death = age_at_death
    person.age_at_death_raw = str(age_at_death) if age_at_death is not None else ""
    person.age_unit = (form_data.get("age_unit") or "歳").strip() or "歳"
    person.deceased_note = (form_data.get("deceased_note") or "").strip()
    person.raw_record = raw_record
    person.save()
    person.sync_legacy_deceased_profile()

    person = _person_for_edit(person.pk)
    log_entry = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=person,
        before_data=before_data,
        after_data=_serialize_person_record(person),
        editor_label=editor_label,
        change_note=change_note,
    )
    funeral_log = None
    if (
        (form_data.get("registration_mode") or HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL)
        == HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL
    ):
        funeral_log = _create_funeral_service_schedule_for_person(
            person=person,
            batch=household.batch,
            death_date=death_date,
            funeral_scheduled_date=form_data.get("funeral_scheduled_date_input"),
            funeral_scheduled_time=form_data.get("funeral_scheduled_time"),
            funeral_location=(form_data.get("funeral_location") or "").strip(),
            editor_label=editor_label,
            change_note=f"{change_note}（葬儀予定作成）",
        )
    return person, log_entry, funeral_log


def _create_new_household_memorial_person(
    *,
    household: Household,
    form_data: dict,
) -> Person:
    legacy_person_id = _next_generated_person_id(household.batch)
    birth_date = form_data.get("birth_date_input")
    normalized_kana = normalize_kana_storage((form_data.get("kana") or "").strip())
    gender = (form_data.get("gender") or "").strip()
    normalized_gender = gender if gender in {choice[0] for choice in GENDER_CHOICES} else "未決定"
    raw_record = {
        "家族ID": legacy_person_id,
        "台帳ID": household.household_uid,
        "氏名": (form_data.get("name") or "").strip(),
        "ﾌﾘｶﾞﾅ": (form_data.get("kana") or "").strip(),
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": (form_data.get("relationship_label") or "").strip(),
        "性別": "" if normalized_gender == "未決定" else normalized_gender,
        "生年月日": birth_date.isoformat() if birth_date else "",
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    return Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="manual_memorial_person",
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=(form_data.get("name") or "").strip(),
        kana=normalized_kana,
        relationship_label=(form_data.get("relationship_label") or "").strip(),
        family_category=FAMILY_CATEGORY_CURRENT,
        gender=normalized_gender,
        birth_date_raw=birth_date.isoformat() if birth_date else "",
        birth_date=birth_date,
        birth_date_parse_error="",
        person_note="",
        is_deceased=False,
        raw_record=raw_record,
    )


def _create_new_household_current_person(
    *,
    household: Household,
    form_data: dict,
) -> Person:
    legacy_person_id = _next_generated_person_id(household.batch)
    birth_date = form_data.get("birth_date_input")
    normalized_kana = normalize_kana_storage((form_data.get("kana") or "").strip())
    gender = (form_data.get("gender") or "").strip()
    normalized_gender = gender if gender in {choice[0] for choice in GENDER_CHOICES} else "未決定"
    raw_record = {
        "家族ID": legacy_person_id,
        "台帳ID": household.household_uid,
        "氏名": (form_data.get("name") or "").strip(),
        "ﾌﾘｶﾞﾅ": (form_data.get("kana") or "").strip(),
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": (form_data.get("relationship_label") or "").strip(),
        "性別": "" if normalized_gender == "未決定" else normalized_gender,
        "生年月日": birth_date.isoformat() if birth_date else "",
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    return Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="manual_current_person",
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=(form_data.get("name") or "").strip(),
        kana=normalized_kana,
        relationship_label=(form_data.get("relationship_label") or "").strip(),
        family_category=FAMILY_CATEGORY_CURRENT,
        gender=normalized_gender,
        birth_date_raw=birth_date.isoformat() if birth_date else "",
        birth_date=birth_date,
        birth_date_parse_error="",
        person_note=(form_data.get("person_note") or "").strip(),
        is_deceased=False,
        raw_record=raw_record,
    )
