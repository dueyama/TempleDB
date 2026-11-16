from __future__ import annotations

from django.db import migrations, models


def _snapshot_value(snapshot: dict, field_path: str):
    value = snapshot
    for part in field_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _changed_snapshot_fields(before_data: dict, after_data: dict, prefix: str = "") -> list[str]:
    changed_fields: list[str] = []
    keys = sorted(set(before_data.keys()) | set(after_data.keys()))
    for key in keys:
        field_path = f"{prefix}.{key}" if prefix else key
        before_value = before_data.get(key)
        after_value = after_data.get(key)
        if isinstance(before_value, dict) or isinstance(after_value, dict):
            nested_before = before_value if isinstance(before_value, dict) else {}
            nested_after = after_value if isinstance(after_value, dict) else {}
            nested_changes = _changed_snapshot_fields(nested_before, nested_after, field_path)
            if nested_changes:
                changed_fields.extend(nested_changes)
            elif before_value != after_value:
                changed_fields.append(field_path)
            continue
        if before_value != after_value:
            changed_fields.append(field_path)
    return changed_fields


def _infer_action_kind(before_data: dict, after_data: dict) -> str:
    before_deleted = bool((before_data or {}).get("deleted_at"))
    after_deleted = bool((after_data or {}).get("deleted_at"))
    if not before_deleted and after_deleted:
        return "delete"
    if before_deleted and not after_deleted:
        return "restore"
    return "update"


def _backfill_record_field_changes(apps, schema_editor) -> None:
    RecordEditLog = apps.get_model("imports", "RecordEditLog")
    RecordFieldChange = apps.get_model("imports", "RecordFieldChange")
    for log in RecordEditLog.objects.iterator():
        before_data = log.before_data or {}
        after_data = log.after_data or {}
        changed_fields = list(log.changed_fields or [])
        recalculated = _changed_snapshot_fields(before_data, after_data)
        if not changed_fields:
            changed_fields = recalculated
        if log.action_kind in {"", None}:
            log.action_kind = _infer_action_kind(before_data, after_data)
            log.save(update_fields=["action_kind"])
        elif log.action_kind == "update":
            inferred = _infer_action_kind(before_data, after_data)
            if inferred != "update":
                log.action_kind = inferred
                log.save(update_fields=["action_kind"])
        for sort_order, field_path in enumerate(changed_fields):
            RecordFieldChange.objects.update_or_create(
                record_edit_log=log,
                field_path=field_path,
                defaults={
                    "before_value": _snapshot_value(before_data, field_path),
                    "after_value": _snapshot_value(after_data, field_path),
                    "sort_order": sort_order,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0017_legacysource_active_import_batch"),
    ]

    operations = [
        migrations.AddField(
            model_name="recordeditlog",
            name="action_kind",
            field=models.CharField(
                choices=[
                    ("update", "更新"),
                    ("delete", "削除"),
                    ("restore", "復元"),
                    ("reset_schedule", "予定リセット"),
                    ("link_update", "法要リンク調整"),
                ],
                default="update",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="RecordFieldChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("field_path", models.CharField(max_length=255)),
                ("before_value", models.JSONField(blank=True, default=None, null=True)),
                ("after_value", models.JSONField(blank=True, default=None, null=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "record_edit_log",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="field_changes", to="imports.recordeditlog"),
                ),
            ],
            options={
                "ordering": ["record_edit_log_id", "sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="SourceOperationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "operation_kind",
                    models.CharField(
                        choices=[
                            ("set_active_batch", "表示 batch 切替"),
                            ("follow_latest_batch", "最新成功 batch 追従"),
                            ("import_pipeline_started", "再取込開始"),
                            ("import_pipeline_succeeded", "再取込完了"),
                            ("import_pipeline_failed", "再取込失敗"),
                        ],
                        max_length=48,
                    ),
                ),
                ("before_payload", models.JSONField(blank=True, default=dict)),
                ("after_payload", models.JSONField(blank=True, default=dict)),
                ("editor_label", models.CharField(blank=True, max_length=100)),
                ("change_note", models.TextField(blank=True)),
                (
                    "source",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="operation_logs", to="imports.legacysource"),
                ),
                (
                    "target_batch",
                    models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="source_operation_logs", to="imports.importbatch"),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="recordeditlog",
            index=models.Index(fields=["action_kind"], name="imports_rec_action__9c2db7_idx"),
        ),
        migrations.AddIndex(
            model_name="recordfieldchange",
            index=models.Index(fields=["record_edit_log", "sort_order"], name="imports_rec_record__cd753a_idx"),
        ),
        migrations.AddIndex(
            model_name="recordfieldchange",
            index=models.Index(fields=["field_path"], name="imports_rec_field_p_e64bcb_idx"),
        ),
        migrations.AddConstraint(
            model_name="recordfieldchange",
            constraint=models.UniqueConstraint(fields=("record_edit_log", "field_path"), name="imports_recordfieldchange_unique_log_path"),
        ),
        migrations.AddIndex(
            model_name="sourceoperationlog",
            index=models.Index(fields=["source", "created_at"], name="imports_sou_source__d9ba74_idx"),
        ),
        migrations.AddIndex(
            model_name="sourceoperationlog",
            index=models.Index(fields=["operation_kind"], name="imports_sou_operati_c7ad74_idx"),
        ),
        migrations.RunPython(_backfill_record_field_changes, migrations.RunPython.noop),
    ]
