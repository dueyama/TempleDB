from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0053_promote_annual_fee_household_uid_field"),
    ]

    operations = [
        migrations.AlterField(
            model_name="annualmembershipfeepayment",
            name="household_uid",
            field=models.CharField(max_length=255),
        ),
    ]
