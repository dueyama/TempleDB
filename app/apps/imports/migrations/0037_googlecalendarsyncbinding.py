import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0036_alter_serviceschedule_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleCalendarSyncBinding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("calendar_id", models.CharField(blank=True, max_length=255)),
                ("sync_key", models.CharField(max_length=255, unique=True)),
                ("google_event_id", models.CharField(blank=True, max_length=255)),
                ("google_etag", models.CharField(blank=True, max_length=255)),
                ("last_pushed_fingerprint", models.CharField(blank=True, max_length=64)),
                (
                    "sync_status",
                    models.CharField(
                        choices=[
                            ("pending", "未同期"),
                            ("synced", "同期済み"),
                            ("error", "エラー"),
                            ("conflict", "競合"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_message", models.TextField(blank=True)),
                (
                    "primary_schedule",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="google_calendar_sync_bindings",
                        to="imports.serviceschedule",
                    ),
                ),
            ],
            options={
                "ordering": ["sync_key"],
            },
        ),
        migrations.AddIndex(
            model_name="googlecalendarsyncbinding",
            index=models.Index(fields=["sync_status", "last_synced_at"], name="imports_goo_sync_st_4d7975_idx"),
        ),
        migrations.AddIndex(
            model_name="googlecalendarsyncbinding",
            index=models.Index(fields=["calendar_id"], name="imports_goo_calenda_804289_idx"),
        ),
    ]
