from django.db import migrations, models


def copy_deceased_profile_to_person(apps, schema_editor):
    Person = apps.get_model("imports", "Person")
    DeceasedProfile = apps.get_model("imports", "DeceasedProfile")
    for profile in DeceasedProfile.objects.select_related("person").iterator():
        Person.objects.filter(pk=profile.person_id).update(
            death_date_raw=profile.death_date_raw,
            death_date=profile.death_date,
            death_date_parse_error=profile.death_date_parse_error,
            kaimyo=profile.kaimyo,
            kaimyo_kana=profile.kaimyo_kana,
            age_at_death_raw=profile.age_at_death_raw,
            age_at_death=profile.age_at_death,
            age_unit=profile.age_unit,
            legacy_hatsubon_flag=profile.legacy_hatsubon_flag,
            hatsubon_flag=profile.hatsubon_flag,
            memorial_notice_opt_out=profile.memorial_notice_opt_out,
            deceased_note=profile.deceased_note,
            memorial_payload=profile.memorial_payload,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0031_deceasedprofile_kaimyo_kana"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="age_at_death",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="age_at_death_raw",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="person",
            name="age_unit",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="person",
            name="death_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="death_date_parse_error",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="person",
            name="death_date_raw",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="person",
            name="deceased_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="person",
            name="hatsubon_flag",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="kaimyo",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="person",
            name="kaimyo_kana",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="person",
            name="legacy_hatsubon_flag",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="person",
            name="memorial_notice_opt_out",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="memorial_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(copy_deceased_profile_to_person, migrations.RunPython.noop),
    ]
