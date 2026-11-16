from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0016_householdprofile_mailing_person"),
    ]

    operations = [
        migrations.AddField(
            model_name="legacysource",
            name="active_import_batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="active_for_sources",
                to="imports.importbatch",
            ),
        ),
    ]
