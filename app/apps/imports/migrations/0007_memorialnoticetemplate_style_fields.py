from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0006_memorialnoticetemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="memorialnoticetemplate",
            name="body_font_size",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="memorialnoticetemplate",
            name="recipient_font_size",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="memorialnoticetemplate",
            name="signature_font_size",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="memorialnoticetemplate",
            name="table_font_size",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
