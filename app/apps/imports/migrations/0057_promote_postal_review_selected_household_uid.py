from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0056_rename_hand_delivery_selected_household_uid_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="postalreviewresolution",
                    old_name="legacy_household_id",
                    new_name="selected_household_uid",
                ),
                migrations.AlterField(
                    model_name="postalreviewresolution",
                    name="selected_household_uid",
                    field=models.CharField(
                        blank=True,
                        db_column="legacy_household_id",
                        max_length=255,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
