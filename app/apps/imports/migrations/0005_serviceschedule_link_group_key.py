from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0004_soft_delete_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="serviceschedule",
            name="link_group_key",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
    ]
