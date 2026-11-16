from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_templeidentitysetting_service_schedule_sutra_cycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlecalendarsyncsetting",
            name="external_base_url",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
