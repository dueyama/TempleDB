from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_database_backup_engine"),
    ]

    operations = [
        migrations.DeleteModel(
            name="UiAppearanceSetting",
        ),
    ]
