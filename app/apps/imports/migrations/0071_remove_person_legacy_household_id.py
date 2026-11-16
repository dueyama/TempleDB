from django.db import migrations, models
from django.db.models import F


def validate_person_household_uids(apps, schema_editor) -> None:
    person = apps.get_model("imports", "Person")
    database_alias = schema_editor.connection.alias
    mismatches = list(
        person.objects.using(database_alias)
        .exclude(
            legacy_household_id=F("household__household_uid"),
        )
        .order_by("pk")
        .values_list(
            "pk",
            "legacy_household_id",
            "household__household_uid",
        )[:20]
    )
    if mismatches:
        raise RuntimeError(
            "Cannot remove Person.legacy_household_id because values differ "
            f"from the related Household: {mismatches}"
        )


def restore_person_household_uids(apps, schema_editor) -> None:
    person = apps.get_model("imports", "Person")
    database_alias = schema_editor.connection.alias
    rows = list(person.objects.using(database_alias).select_related("household"))
    for row in rows:
        row.legacy_household_id = row.household.household_uid
    if rows:
        person.objects.using(database_alias).bulk_update(
            rows,
            ["legacy_household_id"],
            batch_size=1000,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0070_rename_household_profile_household_uid_column"),
    ]

    operations = [
        migrations.AlterField(
            model_name="person",
            name="legacy_household_id",
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.RunPython(
            validate_person_household_uids,
            reverse_code=restore_person_household_uids,
        ),
        migrations.RemoveField(
            model_name="person",
            name="legacy_household_id",
        ),
    ]
