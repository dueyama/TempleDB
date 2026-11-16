from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0005_serviceschedule_link_group_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemorialNoticeTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("target_year", models.PositiveIntegerField()),
                ("intro_text", models.TextField(blank=True)),
                ("outro_text", models.TextField(blank=True)),
                ("signature_text", models.TextField(blank=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="memorial_notice_templates",
                        to="imports.legacysource",
                    ),
                ),
            ],
            options={
                "ordering": ["source__source_id", "-target_year"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source", "target_year"),
                        name="imports_memorialnoticetemplate_unique_source_year",
                    )
                ],
            },
        ),
    ]
