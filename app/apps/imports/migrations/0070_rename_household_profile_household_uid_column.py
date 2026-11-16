from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0069_promote_household_profile_household_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="householdprofile",
            name="household_uid",
            field=models.CharField(max_length=255),
        ),
    ]
