import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0009_district_officer_keys"),
    ]

    operations = [
        migrations.CreateModel(
            name="HouseholdProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("legacy_household_id", models.CharField(max_length=255)),
                ("household_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("household_name_kana_snapshot", models.CharField(blank=True, max_length=255)),
                (
                    "district",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="household_profiles",
                        to="imports.district",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="household_profiles",
                        to="imports.legacysource",
                    ),
                ),
            ],
            options={
                "ordering": ["source__source_id", "legacy_household_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="householdprofile",
            constraint=models.UniqueConstraint(
                fields=("source", "legacy_household_id"),
                name="imports_householdprofile_unique_source_household",
            ),
        ),
    ]
