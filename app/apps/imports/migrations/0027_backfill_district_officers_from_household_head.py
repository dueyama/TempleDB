from __future__ import annotations

from django.db import migrations


def _backfill_district_officers_from_household_head(apps, schema_editor):
    District = apps.get_model("imports", "District")
    Household = apps.get_model("imports", "Household")
    HouseholdProfile = apps.get_model("imports", "HouseholdProfile")
    ImportBatch = apps.get_model("imports", "ImportBatch")
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

        batches = ImportBatch.objects.filter(
            source=source,
            status="succeeded",
        ).order_by("id")
        for batch in batches:
            household = Household.objects.filter(
                batch=batch,
                legacy_household_id=household_id,
                deleted_at__isnull=True,
            ).first()
            if household is None:
                continue

            candidate = None
            if person_id:
                candidate = Person.objects.filter(
                    batch=batch,
                    deleted_at__isnull=True,
                    family_category="0",
                    legacy_household_id=household_id,
                    legacy_person_id=person_id,
                ).first()
            if candidate is None and officer_name:
                candidate = Person.objects.filter(
                    batch=batch,
                    deleted_at__isnull=True,
                    family_category="0",
                    legacy_household_id=household_id,
                    name=officer_name,
                ).first()
            if candidate is None and household.head_person_id:
                candidate = Person.objects.filter(
                    pk=household.head_person_id,
                    deleted_at__isnull=True,
                    family_category="0",
                ).first()
            if candidate is None:
                candidate = Person.objects.filter(
                    batch=batch,
                    deleted_at__isnull=True,
                    family_category="0",
                    legacy_household_id=household_id,
                ).order_by("id").first()
            if candidate is None or candidate.is_district_officer:
                continue
            candidate.is_district_officer = True
            candidate.save(update_fields=["is_district_officer", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0026_backfill_person_based_district_officers"),
    ]

    operations = [
        migrations.RunPython(
            _backfill_district_officers_from_household_head,
            migrations.RunPython.noop,
        ),
    ]
