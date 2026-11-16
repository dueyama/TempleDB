from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0060_rename_household_profile_mailing_person_uid_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField(
                    model_name="annualmembershipfeepostalscan",
                    old_name="selected_legacy_household_id",
                    new_name="selected_household_uid",
                ),
                migrations.AlterField(
                    model_name="annualmembershipfeepostalscan",
                    name="selected_household_uid",
                    field=models.CharField(
                        "selected legacy household id",
                        blank=True,
                        db_column="selected_legacy_household_id",
                        max_length=255,
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="annualmembershipfeepostalscan",
                    name="imports_ann_selecte_b430f3_idx",
                ),
                migrations.AddIndex(
                    model_name="annualmembershipfeepostalscan",
                    index=models.Index(
                        fields=["selected_household_uid", "year"],
                        name="imports_ann_selecte_b430f3_idx",
                    ),
                ),
            ],
        ),
    ]
