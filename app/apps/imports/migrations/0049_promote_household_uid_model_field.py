from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0048_protect_import_batch_records"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="household",
                    old_name="legacy_household_id",
                    new_name="household_uid",
                ),
                migrations.AlterField(
                    model_name="household",
                    name="household_uid",
                    field=models.CharField(
                        db_column="legacy_household_id",
                        max_length=255,
                    ),
                ),
                migrations.AlterModelOptions(
                    name="household",
                    options={"ordering": ["household_uid"]},
                ),
                migrations.RemoveConstraint(
                    model_name="household",
                    name="imports_household_unique_batch_legacy_household",
                ),
                migrations.AddConstraint(
                    model_name="household",
                    constraint=models.UniqueConstraint(
                        fields=("batch", "household_uid"),
                        name="imports_household_unique_batch_legacy_household",
                    ),
                ),
            ],
        ),
    ]
