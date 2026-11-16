from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0052_rename_uid_database_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="annualmembershipfeepayment",
                    old_name="legacy_household_id",
                    new_name="household_uid",
                ),
                migrations.AlterField(
                    model_name="annualmembershipfeepayment",
                    name="household_uid",
                    field=models.CharField(
                        db_column="legacy_household_id",
                        max_length=255,
                    ),
                ),
                migrations.AlterModelOptions(
                    name="annualmembershipfeepayment",
                    options={
                        "ordering": ["source__source_id", "-year", "household_uid"],
                    },
                ),
                migrations.RemoveConstraint(
                    model_name="annualmembershipfeepayment",
                    name="imports_annualmembershipfeepayment_unique_source_household_year",
                ),
                migrations.AddConstraint(
                    model_name="annualmembershipfeepayment",
                    constraint=models.UniqueConstraint(
                        fields=("source", "household_uid", "year"),
                        name="imports_annualmembershipfeepayment_unique_source_household_year",
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="annualmembershipfeepayment",
                    name="imports_ann_legacy__cd19fd_idx",
                ),
                migrations.AddIndex(
                    model_name="annualmembershipfeepayment",
                    index=models.Index(
                        fields=["household_uid", "year"],
                        name="imports_ann_legacy__cd19fd_idx",
                    ),
                ),
            ],
        ),
    ]
