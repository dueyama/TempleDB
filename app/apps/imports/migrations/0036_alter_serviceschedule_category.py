from django.db import migrations, models


def _migrate_funeral_category_forward(apps, schema_editor):
    ServiceSchedule = apps.get_model("imports", "ServiceSchedule")
    ServiceSchedule.objects.filter(
        category="other",
        service_label="葬儀",
    ).update(category="funeral")
    ServiceSchedule.objects.filter(
        category="other",
        service_label="満中陰（四十九日）",
    ).update(category="memorial")


def _migrate_funeral_category_backward(apps, schema_editor):
    ServiceSchedule = apps.get_model("imports", "ServiceSchedule")
    ServiceSchedule.objects.filter(
        category="funeral",
        service_label="葬儀",
    ).update(category="other")
    ServiceSchedule.objects.filter(
        category="memorial",
        service_label="満中陰（四十九日）",
    ).update(category="other")


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0035_memotag_and_assignment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="serviceschedule",
            name="category",
            field=models.CharField(
                choices=[
                    ("memorial", "年忌"),
                    ("hatsubon", "初盆"),
                    ("funeral", "葬儀"),
                    ("visit", "訪問"),
                    ("other", "その他"),
                ],
                default="memorial",
                max_length=32,
            ),
        ),
        migrations.RunPython(
            _migrate_funeral_category_forward,
            _migrate_funeral_category_backward,
        ),
    ]
