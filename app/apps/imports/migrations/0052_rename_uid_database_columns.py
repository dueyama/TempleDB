from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0051_promote_schedule_uid_model_field"),
    ]

    operations = [
        migrations.AlterField(
            model_name="household",
            name="household_uid",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="person",
            name="person_uid",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="serviceschedule",
            name="schedule_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
