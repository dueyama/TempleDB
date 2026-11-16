from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0054_rename_annual_fee_household_uid_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="handdeliveryreviewresolution",
                    old_name="legacy_household_id",
                    new_name="selected_household_uid",
                ),
                migrations.AlterField(
                    model_name="handdeliveryreviewresolution",
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
