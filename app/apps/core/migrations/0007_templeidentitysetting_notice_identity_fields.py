from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_googlecalendarsyncsetting_external_base_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="templeidentitysetting",
            name="temple_address",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="templeidentitysetting",
            name="temple_sect",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
