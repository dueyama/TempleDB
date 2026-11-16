from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0010_householdprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdprofile",
            name="delivery_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "未設定"),
                    ("district", "地区所属"),
                    ("postal", "郵送"),
                    ("none", "送付しない"),
                ],
                max_length=16,
            ),
        ),
    ]
