from __future__ import annotations

from django.db import migrations, models

DATABASE_BACKUP_ENGINES = ("postgresql", "sqlite")


def backfill_database_backup_engines(apps, schema_editor) -> None:
    DatabaseBackupRun = apps.get_model("core", "DatabaseBackupRun")
    DatabaseBackupSetting = apps.get_model("core", "DatabaseBackupSetting")
    alias = schema_editor.connection.alias

    DatabaseBackupRun.objects.using(alias).filter(database_engine__isnull=True).update(
        database_engine="postgresql"
    )
    DatabaseBackupSetting.objects.using(alias).filter(
        last_scheduled_attempt_on__isnull=False,
        last_scheduled_attempt_engine="",
    ).update(last_scheduled_attempt_engine="postgresql")


def clear_database_backup_engines(apps, schema_editor) -> None:
    DatabaseBackupSetting = apps.get_model("core", "DatabaseBackupSetting")
    DatabaseBackupSetting.objects.using(schema_editor.connection.alias).update(
        last_scheduled_attempt_engine=""
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_database_runtime_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="databasebackuprun",
            name="database_engine",
            field=models.CharField(
                choices=[("postgresql", "PostgreSQL"), ("sqlite", "SQLite")],
                db_index=True,
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="databasebackupsetting",
            name="last_scheduled_attempt_engine",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "未実行"),
                    ("postgresql", "PostgreSQL"),
                    ("sqlite", "SQLite"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.RunPython(
            backfill_database_backup_engines,
            clear_database_backup_engines,
        ),
        migrations.AlterField(
            model_name="databasebackuprun",
            name="database_engine",
            field=models.CharField(
                choices=[("postgresql", "PostgreSQL"), ("sqlite", "SQLite")],
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="databasebackuprun",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("database_engine__in", DATABASE_BACKUP_ENGINES)
                ),
                name="core_backup_run_engine_valid",
            ),
        ),
    ]
