from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0067_remove_legacy_source_active_import_batch"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sourceoperationlog",
            name="operation_kind",
            field=models.CharField(
                choices=[
                    ("operational_source_bootstrap", "通常運用 primary 自動補完"),
                    ("import_pipeline_started", "再取込開始"),
                    ("import_pipeline_succeeded", "再取込完了"),
                    ("import_pipeline_failed", "再取込失敗"),
                ],
                max_length=48,
            ),
        ),
    ]
