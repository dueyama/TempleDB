from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_googlecalendarsyncsetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlecalendarsyncsetting",
            name="base_url",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
