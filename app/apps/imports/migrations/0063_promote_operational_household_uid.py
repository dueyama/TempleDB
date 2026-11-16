from django.db import migrations, models

OPERATIONAL_MODELS = (
    ("serviceschedule", "imports_ser_legacy__babdc7_idx"),
    ("visitnote", "imports_vis_legacy__ed7ac3_idx"),
    ("offeringpayment", "imports_off_legacy__fdfc48_idx"),
)


def operational_household_uid_state_operations():
    operations = []
    for model_name, index_name in OPERATIONAL_MODELS:
        operations.extend(
            [
                migrations.RenameField(
                    model_name=model_name,
                    old_name="legacy_household_id",
                    new_name="household_uid",
                ),
                migrations.AlterField(
                    model_name=model_name,
                    name="household_uid",
                    field=models.CharField(
                        blank=True,
                        db_column="legacy_household_id",
                        max_length=255,
                    ),
                ),
                migrations.RemoveIndex(
                    model_name=model_name,
                    name=index_name,
                ),
                migrations.AddIndex(
                    model_name=model_name,
                    index=models.Index(
                        fields=["household_uid"],
                        name=index_name,
                    ),
                ),
            ]
        )
    return operations


class Migration(migrations.Migration):
    dependencies = [
        (
            "imports",
            "0062_rename_annual_fee_postal_scan_selected_household_uid_column",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=operational_household_uid_state_operations(),
        ),
    ]
