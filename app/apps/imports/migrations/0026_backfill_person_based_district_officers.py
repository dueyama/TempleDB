from __future__ import annotations

from django.db import migrations


def _backfill_person_based_district_officers(apps, schema_editor):
    District = apps.get_model("imports", "District")
    HouseholdProfile = apps.get_model("imports", "HouseholdProfile")
    LegacySource = apps.get_model("imports", "LegacySource")
    Person = apps.get_model("imports", "Person")

    for district in District.objects.exclude(officer_legacy_household_id=""):
        source_id = (district.officer_legacy_source_id or "").strip()
        household_id = (district.officer_legacy_household_id or "").strip()
        person_id = (district.officer_legacy_person_id or "").strip()
        officer_name = (district.officer_name or "").strip()
        if not source_id or not household_id:
            continue

        source = LegacySource.objects.filter(source_id=source_id).first()
        if source is None:
            continue

        profile_exists = HouseholdProfile.objects.filter(
            source=source,
            legacy_household_id=household_id,
            delivery_method="district",
            district_id=district.pk,
        ).exists()
        if not profile_exists:
            continue

        people = Person.objects.filter(
            legacy_source_id=source_id,
            legacy_household_id=household_id,
            deleted_at__isnull=True,
            family_category="0",
        )
        if person_id:
            people = people.filter(legacy_person_id=person_id)
        elif officer_name:
            people = people.filter(name=officer_name)

        for person in people:
            if not person.is_district_officer:
                person.is_district_officer = True
                person.save(update_fields=["is_district_officer", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0025_person_role_flags_and_district_person_link"),
    ]

    operations = [
        migrations.RunPython(
            _backfill_person_based_district_officers,
            migrations.RunPython.noop,
        ),
    ]
