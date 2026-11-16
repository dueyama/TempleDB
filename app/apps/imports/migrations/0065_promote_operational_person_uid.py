from django.db import migrations, models

OPERATIONAL_MODELS = (
    "serviceschedule",
    "visitnote",
    "offeringpayment",
)


def operational_person_uid_state_operations():
    operations = []
    for model_name in OPERATIONAL_MODELS:
        operations.extend(
            [
                migrations.RenameField(
                    model_name=model_name,
                    old_name="legacy_person_id",
                    new_name="person_uid",
                ),
                migrations.AlterField(
                    model_name=model_name,
                    name="person_uid",
                    field=models.CharField(
                        blank=True,
                        db_column="legacy_person_id",
                        max_length=255,
                    ),
                ),
            ]
        )
    return operations


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0064_rename_operational_household_uid_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=operational_person_uid_state_operations(),
        ),
    ]
