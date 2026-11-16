from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0028_remove_district_legacy_officer_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DistrictMemberSheetState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("manual_note", models.TextField(blank=True)),
                ("last_printed_member_snapshot", models.JSONField(blank=True, default=list)),
                ("last_printed_prepared_snapshot_id", models.CharField(blank=True, max_length=255)),
                ("last_printed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "district",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="member_sheet_states",
                        to="imports.district",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="district_member_sheet_states",
                        to="imports.legacysource",
                    ),
                ),
            ],
            options={
                "ordering": ["source__source_id", "district__sort_order", "district__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="districtmembersheetstate",
            constraint=models.UniqueConstraint(
                fields=("source", "district"),
                name="imports_districtmembersheetstate_unique_source_district",
            ),
        ),
    ]
