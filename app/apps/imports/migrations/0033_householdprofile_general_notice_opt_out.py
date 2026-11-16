from django.db import migrations, models


def _parse_legacy_household_notice_opt_out(value):
    cleaned = str(value or "").strip()
    if not cleaned or cleaned == "__MDB_NULL__":
        return False
    lowered = cleaned.lower()
    return cleaned in {"×", "✕", "☓", "ｘ", "Ｘ", "x", "X"} or lowered in {
        "0",
        "false",
        "off",
        "no",
        "不要",
    }


def backfill_household_notice_flags(apps, schema_editor):
    Household = apps.get_model("imports", "Household")
    HouseholdProfile = apps.get_model("imports", "HouseholdProfile")

    seen = set()
    households = (
        Household.objects.select_related("batch__source")
        .filter(deleted_at__isnull=True)
        .order_by("legacy_source_id", "legacy_household_id", "-id")
    )
    for household in households.iterator():
        key = (household.legacy_source_id, household.legacy_household_id)
        if key in seen:
            continue
        seen.add(key)
        raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
        general_notice_opt_out = _parse_legacy_household_notice_opt_out(raw_record.get("案内要否"))
        memorial_notice_opt_out = _parse_legacy_household_notice_opt_out(raw_record.get("年回要否"))
        if not general_notice_opt_out and not memorial_notice_opt_out:
            continue
        profile, _created = HouseholdProfile.objects.get_or_create(
            source=household.batch.source,
            legacy_household_id=household.legacy_household_id,
        )
        changed = False
        if general_notice_opt_out and profile.general_notice_opt_out is None:
            profile.general_notice_opt_out = True
            changed = True
        if memorial_notice_opt_out and profile.memorial_notice_opt_out is None:
            profile.memorial_notice_opt_out = True
            changed = True
        if changed:
            profile.save()


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0032_person_memorial_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdprofile",
            name="general_notice_opt_out",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_household_notice_flags, migrations.RunPython.noop),
    ]
