from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0007_memorialnoticetemplate_style_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="District",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("short_name", models.CharField(blank=True, max_length=40)),
                ("sort_order", models.PositiveIntegerField(default=100)),
                ("officer_name", models.CharField(blank=True, max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
    ]
