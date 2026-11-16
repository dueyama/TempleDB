from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0058_rename_postal_review_selected_household_uid_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="householdprofile",
                    old_name="mailing_person_legacy_person_id",
                    new_name="mailing_person_uid",
                ),
                migrations.AlterField(
                    model_name="householdprofile",
                    name="mailing_person_uid",
                    field=models.CharField(
                        blank=True,
                        db_column="mailing_person_legacy_person_id",
                        max_length=255,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
