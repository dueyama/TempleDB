from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0057_promote_postal_review_selected_household_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="postalreviewresolution",
            name="selected_household_uid",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
