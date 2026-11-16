from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0015_householdprofile_mailing_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_person_legacy_person_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
