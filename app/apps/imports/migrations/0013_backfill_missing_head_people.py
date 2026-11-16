# Generated manually on 2026-03-15

from django.db import migrations

FAMILY_CATEGORY_CURRENT = "0"


def _normalize_head_text(value) -> str:
    if value is None:
        return ""
    return "".join(str(value).strip().replace(" ", "").replace("\u3000", "").split())


def _next_person_number_by_batch(Person, batch_id: int) -> int:
    max_numeric = 0
    for value in (
        Person.objects.filter(batch_id=batch_id)
        .values_list("legacy_person_id", flat=True)
    ):
        if str(value).isdigit():
            max_numeric = max(max_numeric, int(str(value)))
    return max_numeric + 1


def _matching_person(Person, household):
    head_name = _normalize_head_text(household.head_name)
    if not head_name:
        return None
    head_kana = _normalize_head_text(household.head_name_kana)
    candidates = list(
        Person.objects.filter(
            batch_id=household.batch_id,
            household_id=household.id,
            deleted_at__isnull=True,
        )
        .order_by("legacy_person_id", "id")
        .values("id", "name", "kana")
    )
    exact_name_matches = [
        person for person in candidates if _normalize_head_text(person.get("name")) == head_name
    ]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1 and head_kana:
        kana_matches = [
            person
            for person in exact_name_matches
            if _normalize_head_text(person.get("kana")) == head_kana
        ]
        if len(kana_matches) == 1:
            return kana_matches[0]
    return None


def _backfill_missing_head_people(apps, schema_editor) -> None:
    Household = apps.get_model("imports", "Household")
    Person = apps.get_model("imports", "Person")
    next_by_batch: dict[int, int] = {}

    households = Household.objects.filter(head_person_id__isnull=True).order_by("batch_id", "id")
    for household in households:
        match = _matching_person(Person, household)
        if match is not None:
            household.head_person_id = match["id"]
            household.save(update_fields=["head_person"])
            continue

        next_number = next_by_batch.get(household.batch_id)
        if next_number is None:
            next_number = _next_person_number_by_batch(Person, household.batch_id)
        raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
        generated_person_id = str(next_number)
        person = Person.objects.create(
            batch_id=household.batch_id,
            household_id=household.id,
            legacy_source_id=household.legacy_source_id,
            source_mdb_file=household.source_mdb_file,
            source_export_batch=household.source_export_batch,
            source_table="generated_household_head",
            source_row_number=household.source_row_number,
            legacy_pk_text=generated_person_id,
            legacy_person_id=generated_person_id,
            legacy_household_id=household.legacy_household_id,
            name=household.head_name,
            kana=household.head_name_kana,
            relationship_label=str(raw_record.get("続柄") or "").strip(),
            family_category=FAMILY_CATEGORY_CURRENT,
            gender=str(raw_record.get("性別") or "").strip(),
            birth_date_raw=str(raw_record.get("生年月日") or "").strip(),
            birth_date=None,
            birth_date_parse_error="",
            person_note="",
            is_deceased=False,
            raw_record={
                "家族ID": generated_person_id,
                "台帳ID": household.legacy_household_id,
                "氏名": household.head_name,
                "ﾌﾘｶﾞﾅ": household.head_name_kana,
                "〒": household.postal_code,
                "住所1": household.address_line1,
                "住所2": household.address_line2,
                "住所3": household.address_line3,
                "電話": household.phone,
                "ＦＡＸ": household.fax,
                "携帯": household.mobile,
                "Email": household.email,
                "続柄": str(raw_record.get("続柄") or "").strip(),
                "性別": str(raw_record.get("性別") or "").strip(),
                "生年月日": str(raw_record.get("生年月日") or "").strip(),
                "家族区分": FAMILY_CATEGORY_CURRENT,
            },
        )
        household.head_person_id = person.id
        household.save(update_fields=["head_person"])
        next_by_batch[household.batch_id] = next_number + 1


def _noop(apps, schema_editor) -> None:
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0012_household_head_person"),
    ]

    operations = [
        migrations.RunPython(_backfill_missing_head_people, _noop),
    ]
