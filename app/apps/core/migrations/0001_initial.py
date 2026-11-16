from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DatabaseBackupSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, unique=True)),
                ("destination_path", models.TextField(blank=True)),
                ("retention_count", models.PositiveIntegerField(default=30)),
                ("daily_enabled", models.BooleanField(default=True)),
                ("last_scheduled_attempt_on", models.DateField(blank=True, null=True)),
                (
                    "last_status",
                    models.CharField(
                        blank=True,
                        choices=[("running", "実行中"), ("succeeded", "成功"), ("failed", "失敗")],
                        max_length=16,
                    ),
                ),
                ("last_status_message", models.TextField(blank=True)),
                ("last_completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["singleton_key"]},
        ),
        migrations.CreateModel(
            name="DatabaseBackupRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "trigger_kind",
                    models.CharField(
                        choices=[("manual", "手動"), ("scheduled", "日次自動")], max_length=16
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("running", "実行中"), ("succeeded", "成功"), ("failed", "失敗")],
                        max_length=16,
                    ),
                ),
                ("requested_by_label", models.CharField(blank=True, max_length=100)),
                ("database_name", models.CharField(blank=True, max_length=255)),
                ("database_host", models.CharField(blank=True, max_length=255)),
                ("destination_path", models.TextField(blank=True)),
                ("backup_file_name", models.CharField(blank=True, max_length=255)),
                ("backup_file_path", models.TextField(blank=True)),
                ("manifest_file_path", models.TextField(blank=True)),
                ("backup_file_size", models.BigIntegerField(blank=True, null=True)),
                ("backup_sha256", models.CharField(blank=True, max_length=64)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "setting",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="runs",
                        to="core.databasebackupsetting",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["status", "started_at"], name="core_databa_status_91c182_idx"
                    ),
                    models.Index(
                        fields=["trigger_kind", "started_at"], name="core_databa_trigger_761bdb_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DatabaseBackupVerificationRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("running", "実行中"), ("succeeded", "成功"), ("failed", "失敗")],
                        max_length=16,
                    ),
                ),
                ("requested_by_label", models.CharField(blank=True, max_length=100)),
                ("verification_database_name", models.CharField(blank=True, max_length=255)),
                ("verification_summary", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "backup_run",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="verification_runs",
                        to="core.databasebackuprun",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["status", "started_at"], name="core_databa_status_7fd0bb_idx"
                    ),
                    models.Index(
                        fields=["backup_run", "started_at"], name="core_databa_backup__d2e1a5_idx"
                    ),
                ],
            },
        ),
    ]
