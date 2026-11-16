from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_bereavementforecastsetting"),
    ]

    operations = [
        migrations.CreateModel(
            name="UiAppearanceSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, unique=True)),
                (
                    "theme",
                    models.CharField(
                        choices=[("legacy", "従来"), ("work", "業務UI")],
                        default="legacy",
                        max_length=16,
                    ),
                ),
            ],
            options={
                "ordering": ["singleton_key"],
            },
        ),
    ]
