import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0047_retire_bereavement_forecast"),
    ]

    operations = [
        migrations.AlterField(
            model_name="household",
            name="batch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="households",
                to="imports.importbatch",
            ),
        ),
        migrations.AlterField(
            model_name="person",
            name="batch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="persons",
                to="imports.importbatch",
            ),
        ),
    ]
