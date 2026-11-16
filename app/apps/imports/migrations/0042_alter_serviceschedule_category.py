from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0041_alter_offeringpayment_payment_category"),
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
