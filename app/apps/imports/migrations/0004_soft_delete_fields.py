from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0003_recordeditlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="household",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="household",
            name="deleted_by",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="household",
            name="deletion_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="person",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="person",
            name="deleted_by",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="person",
            name="deletion_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="serviceschedule",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="serviceschedule",
            name="deleted_by",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="serviceschedule",
            name="deletion_note",
            field=models.TextField(blank=True),
        ),
    ]
