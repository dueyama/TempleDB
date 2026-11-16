from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0065_promote_operational_person_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="serviceschedule",
            name="person_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="visitnote",
            name="person_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="offeringpayment",
            name="person_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
