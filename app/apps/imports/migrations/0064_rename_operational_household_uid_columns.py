from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0063_promote_operational_household_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="serviceschedule",
            name="household_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="visitnote",
            name="household_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="offeringpayment",
            name="household_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
