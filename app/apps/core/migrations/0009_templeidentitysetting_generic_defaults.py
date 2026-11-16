from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_templeidentitysetting_postal_and_priest"),
    ]

    operations = [
        migrations.AlterField(
            model_name="templeidentitysetting",
            name="temple_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="templeidentitysetting",
            name="temple_phone",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
