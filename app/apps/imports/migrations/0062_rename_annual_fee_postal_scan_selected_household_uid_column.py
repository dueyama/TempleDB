from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0061_promote_annual_fee_postal_scan_selected_household_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="annualmembershipfeepostalscan",
            name="selected_household_uid",
            field=models.CharField(
                "selected legacy household id",
                blank=True,
                max_length=255,
            ),
        ),
    ]
