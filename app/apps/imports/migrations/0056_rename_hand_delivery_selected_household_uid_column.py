from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0055_promote_hand_delivery_selected_household_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="handdeliveryreviewresolution",
            name="selected_household_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
