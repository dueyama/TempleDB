from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_retire_bereavement_forecast"),
    ]

    operations = [
        migrations.AddField(
            model_name="databasebackupsetting",
            name="weekly_verification_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="databasebackupverificationrun",
            name="trigger_kind",
            field=models.CharField(
                choices=[("manual", "手動"), ("scheduled", "週次自動")],
                default="manual",
                max_length=16,
            ),
        ),
    ]
