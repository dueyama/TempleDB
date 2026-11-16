from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0045_postal_scan_statement_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="serviceschedule",
            name="category",
            field=models.CharField(
                choices=[
                    ("memorial", "年忌"),
                    ("chuin", "中陰"),
                    ("hatsubon", "初盆"),
                    ("funeral", "葬儀"),
                    ("bon", "盆"),
                    ("otokoshi", "お取越し"),
                    ("visit", "訪問"),
                    ("other", "その他"),
                ],
                default="memorial",
                max_length=32,
            ),
        ),
    ]
