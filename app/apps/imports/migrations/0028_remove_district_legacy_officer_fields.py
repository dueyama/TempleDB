from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0027_backfill_district_officers_from_household_head"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="district",
            name="officer_legacy_household_id",
        ),
        migrations.RemoveField(
            model_name="district",
            name="officer_legacy_person_id",
        ),
        migrations.RemoveField(
            model_name="district",
            name="officer_legacy_source_id",
        ),
        migrations.RemoveField(
            model_name="district",
            name="officer_name",
        ),
    ]
