from __future__ import annotations

import uuid

from django.conf import settings
from django.db import migrations, models


def create_runtime_identity(apps, schema_editor) -> None:
    DatabaseRuntimeIdentity = apps.get_model("core", "DatabaseRuntimeIdentity")
    runtime_kind = "demo" if getattr(settings, "TEMPLEDB_DEMO_MODE", False) else "product"
    DatabaseRuntimeIdentity.objects.using(schema_editor.connection.alias).get_or_create(
        singleton_key=1,
        defaults={"runtime_kind": runtime_kind},
    )


def remove_runtime_identity(apps, schema_editor) -> None:
    DatabaseRuntimeIdentity = apps.get_model("core", "DatabaseRuntimeIdentity")
    DatabaseRuntimeIdentity.objects.using(schema_editor.connection.alias).filter(
        singleton_key=1
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_weekly_backup_verification"),
    ]

    operations = [
        migrations.CreateModel(
            name="DatabaseRuntimeIdentity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(default=1, unique=True),
                ),
                (
                    "installation_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "runtime_kind",
                    models.CharField(
                        choices=[("product", "製品"), ("demo", "デモ")],
                        default="product",
                        max_length=16,
                    ),
                ),
            ],
            options={"ordering": ["singleton_key"]},
        ),
        migrations.RunPython(
            create_runtime_identity,
            remove_runtime_identity,
        ),
    ]
