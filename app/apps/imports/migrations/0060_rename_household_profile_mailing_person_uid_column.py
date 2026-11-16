from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0059_promote_household_profile_mailing_person_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="householdprofile",
            name="mailing_person_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
