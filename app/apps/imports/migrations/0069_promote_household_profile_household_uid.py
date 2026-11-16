from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0068_retire_active_batch_operation_kinds"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="householdprofile",
                    old_name="legacy_household_id",
                    new_name="household_uid",
                ),
                migrations.AlterField(
                    model_name="householdprofile",
                    name="household_uid",
                    field=models.CharField(
                        db_column="legacy_household_id",
                        max_length=255,
                    ),
                ),
                migrations.AlterModelOptions(
                    name="householdprofile",
                    options={
                        "ordering": ["source__source_id", "household_uid"],
                    },
                ),
                migrations.RemoveConstraint(
                    model_name="householdprofile",
                    name="imports_householdprofile_unique_source_household",
                ),
                migrations.AddConstraint(
                    model_name="householdprofile",
                    constraint=models.UniqueConstraint(
                        fields=("source", "household_uid"),
                        name="imports_householdprofile_unique_source_household",
                    ),
                ),
            ],
        ),
    ]
