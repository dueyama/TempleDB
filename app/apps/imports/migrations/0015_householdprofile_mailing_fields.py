from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0014_soft_delete_legacy_imported_schedules"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_address_line1",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_address_line2",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_phone",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="householdprofile",
            name="mailing_postal_code",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
