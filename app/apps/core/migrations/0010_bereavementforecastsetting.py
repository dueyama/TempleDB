from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_templeidentitysetting_generic_defaults"),
    ]

    operations = [
        migrations.CreateModel(
            name="BereavementForecastSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, unique=True)),
                ("timesfm_enabled", models.BooleanField(blank=True, default=None, null=True)),
            ],
            options={
                "ordering": ["singleton_key"],
            },
        ),
    ]
