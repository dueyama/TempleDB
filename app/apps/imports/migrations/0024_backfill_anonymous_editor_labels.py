from __future__ import annotations

from django.db import migrations


def backfill_editor_labels(apps, schema_editor) -> None:
    RecordEditLog = apps.get_model("imports", "RecordEditLog")
    SourceOperationLog = apps.get_model("imports", "SourceOperationLog")
    RecordEditLog.objects.filter(editor_label="").update(editor_label="anonymous")
    SourceOperationLog.objects.filter(editor_label="").update(editor_label="anonymous")


def noop(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0023_handdeliveryreviewresolution"),
    ]

    operations = [
        migrations.RunPython(backfill_editor_labels, noop),
    ]
