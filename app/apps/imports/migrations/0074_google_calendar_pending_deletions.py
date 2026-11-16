from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("imports", "0073_temple_events")]

    operations = [
        migrations.AddField(
            model_name="googlecalendarsyncbinding",
            name="pending_event_deletions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
