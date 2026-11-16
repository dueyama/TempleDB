from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0030_drop_household_snapshot_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="deceasedprofile",
            name="kaimyo_kana",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
