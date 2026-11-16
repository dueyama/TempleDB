from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0050_promote_person_uid_model_field"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="serviceschedule",
                    old_name="legacy_schedule_id",
                    new_name="schedule_uid",
                ),
                migrations.AlterField(
                    model_name="serviceschedule",
                    name="schedule_uid",
                    field=models.CharField(
                        blank=True,
                        db_column="legacy_schedule_id",
                        max_length=255,
                    ),
                ),
            ],
        ),
    ]
