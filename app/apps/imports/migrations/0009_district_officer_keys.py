from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0008_district"),
    ]

    operations = [
        migrations.AddField(
            model_name="district",
            name="officer_legacy_household_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="district",
            name="officer_legacy_source_id",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
