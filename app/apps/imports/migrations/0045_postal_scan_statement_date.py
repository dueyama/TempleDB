from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0044_postal_scan_pages"),
    ]

    operations = [
        migrations.AddField(
            model_name="annualmembershipfeepostalscan",
            name="statement_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
