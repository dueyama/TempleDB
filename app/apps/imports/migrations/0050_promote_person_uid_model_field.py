from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0049_promote_household_uid_model_field"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="person",
                    old_name="legacy_person_id",
                    new_name="person_uid",
                ),
                migrations.AlterField(
                    model_name="person",
                    name="person_uid",
                    field=models.CharField(
                        db_column="legacy_person_id",
                        max_length=255,
                    ),
                ),
                migrations.AlterModelOptions(
                    name="person",
                    options={"ordering": ["person_uid"]},
                ),
                migrations.RemoveConstraint(
                    model_name="person",
                    name="imports_person_unique_batch_legacy_person",
                ),
                migrations.AddConstraint(
                    model_name="person",
                    constraint=models.UniqueConstraint(
                        fields=("batch", "person_uid"),
                        name="imports_person_unique_batch_legacy_person",
                    ),
                ),
                migrations.AlterModelOptions(
                    name="deceasedprofile",
                    options={"ordering": ["person__person_uid"]},
                ),
            ],
        ),
    ]
