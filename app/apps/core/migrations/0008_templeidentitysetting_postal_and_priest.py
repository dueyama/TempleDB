from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_templeidentitysetting_notice_identity_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="templeidentitysetting",
            name="temple_postal_code",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="templeidentitysetting",
            name="chief_priest_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
