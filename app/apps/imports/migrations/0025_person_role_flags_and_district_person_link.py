from __future__ import annotations

from django.db import migrations, models


def _backfill_district_officer_persons(apps, schema_editor):
    District = apps.get_model("imports", "District")
    Household = apps.get_model("imports", "Household")
    ImportBatch = apps.get_model("imports", "ImportBatch")
    Person = apps.get_model("imports", "Person")

    for district in District.objects.exclude(officer_legacy_household_id=""):
        if district.officer_legacy_person_id:
            continue
        source_id = (district.officer_legacy_source_id or "").strip()
        household_id = (district.officer_legacy_household_id or "").strip()
        if not source_id or not household_id:
            continue

        latest_batch = (
            ImportBatch.objects.filter(source__source_id=source_id, status="succeeded")
            .order_by("-created_at", "-id")
            .first()
        )
        if latest_batch is None:
            continue

        household = (
            Household.objects.filter(
                batch=latest_batch,
                deleted_at__isnull=True,
                legacy_household_id=household_id,
            )
            .order_by("id")
            .first()
        )
        if household is None:
            continue

        person = None
        if household.head_person_id:
            person = (
                Person.objects.filter(
                    pk=household.head_person_id,
                    deleted_at__isnull=True,
                )
                .order_by("id")
                .first()
            )
        if person is None:
            person = (
                Person.objects.filter(
                    batch=latest_batch,
                    deleted_at__isnull=True,
                    legacy_household_id=household_id,
                    family_category="0",
                )
                .order_by("id")
                .first()
            )
        if person is None:
            person = (
                Person.objects.filter(
                    batch=latest_batch,
                    deleted_at__isnull=True,
                    legacy_household_id=household_id,
                )
                .order_by("id")
                .first()
            )
        if person is None:
            continue

        district.officer_legacy_person_id = person.legacy_person_id
        if person.name:
            district.officer_name = person.name
        district.save(update_fields=["officer_legacy_person_id", "officer_name", "updated_at"])

        if not person.is_district_officer:
            person.is_district_officer = True
            person.save(update_fields=["is_district_officer", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0024_backfill_anonymous_editor_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="district",
            name="officer_legacy_person_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="person",
            name="is_district_officer",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="person",
            name="is_monto_sodai",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="person",
            name="is_responsible_officer",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(_backfill_district_officer_persons, migrations.RunPython.noop),
    ]
