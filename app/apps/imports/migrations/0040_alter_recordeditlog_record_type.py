from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0039_bereavementforecastsnapshot_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recordeditlog",
            name="record_type",
            field=models.CharField(
                choices=[
                    ("household", "戸主"),
                    ("person", "家族"),
                    ("service_schedule", "予定"),
                    ("offering_payment", "入金"),
                ],
                max_length=32,
            ),
        ),
    ]
