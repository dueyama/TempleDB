from __future__ import annotations

import json

from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError

from apps.imports.models import SourceOperationLog
from apps.imports.source_operation_history_compat import (
    RETIRED_FOLLOW_LATEST_BATCH,
    RETIRED_SET_ACTIVE_BATCH,
    source_operation_kind_label,
)

from .record_history_snapshot import _format_history_value


def _source_operation_history_entries(*, source_id: str, query: str) -> list[dict]:
    try:
        rows = SourceOperationLog.objects.filter(source__source_id=source_id).select_related("target_batch")
    except (OperationalError, ProgrammingError):
        return []
    if query:
        rows = rows.filter(
            Q(editor_label__icontains=query)
            | Q(change_note__icontains=query)
            | Q(operation_kind__icontains=query)
            | Q(target_batch__prepared_snapshot_id__icontains=query)
        )
    entries: list[dict] = []
    for log in rows.order_by("-created_at", "-id")[:30]:
        target_batch = log.target_batch
        entries.append(
            {
                "log": log,
                "operation_label": _source_operation_label(log),
                "headline": _source_operation_headline(log, target_batch),
                "summary": _source_operation_summary(log, target_batch),
                "target_label": (
                    target_batch.prepared_snapshot_id
                    if target_batch is not None
                    else (log.after_payload.get("visible_snapshot_id") or "")
                ),
                "payload_changes": _source_operation_payload_changes(log),
                "before_payload_json": json.dumps(log.before_payload, ensure_ascii=False, indent=2),
                "after_payload_json": json.dumps(log.after_payload, ensure_ascii=False, indent=2),
            }
        )
    return entries


def _source_operation_headline(log: SourceOperationLog, target_batch) -> str:
    target_label = (
        target_batch.prepared_snapshot_id
        if target_batch is not None
        else (log.after_payload.get("visible_snapshot_id") or "")
    )
    if log.operation_kind == RETIRED_SET_ACTIVE_BATCH:
        label = target_label or "指定 batch"
        return f"表示 batch を {label} に切り替えました"
    if log.operation_kind == RETIRED_FOLLOW_LATEST_BATCH:
        return "表示 batch を最新成功 batch 追従に戻しました"
    if log.operation_kind == SourceOperationLog.OperationKind.OPERATIONAL_SOURCE_BOOTSTRAP:
        return "通常運用 primary を registry default から自動補完しました"
    if log.operation_kind == SourceOperationLog.OperationKind.IMPORT_PIPELINE_STARTED:
        return "再取込を開始しました"
    if log.operation_kind == SourceOperationLog.OperationKind.IMPORT_PIPELINE_SUCCEEDED:
        return "再取込が完了しました"
    if log.operation_kind == SourceOperationLog.OperationKind.IMPORT_PIPELINE_FAILED:
        return "再取込が失敗しました"
    return _source_operation_label(log)


def _source_operation_label(log: SourceOperationLog) -> str:
    return source_operation_kind_label(
        log.operation_kind,
        log.get_operation_kind_display(),
    )


def _source_operation_summary(log: SourceOperationLog, target_batch) -> str:
    note = (log.change_note or "").strip()
    if note:
        return note
    changes = _source_operation_payload_changes(log)
    if not changes:
        return _source_operation_label(log)
    labels = "、".join(change["label"] for change in changes[:3])
    if len(changes) > 3:
        labels += f"、ほか{len(changes) - 3}項目"
    return f"変更点: {labels}"


def _source_operation_payload_changes(log: SourceOperationLog) -> list[dict]:
    fields = (
        ("active_snapshot_id", "固定表示 snapshot"),
        ("visible_snapshot_id", "表示中 snapshot"),
        ("active_batch_uuid", "固定表示 batch UUID"),
    )
    changes: list[dict] = []
    for key, label in fields:
        before = _format_history_value(log.before_payload.get(key))
        after = _format_history_value(log.after_payload.get(key))
        if before == after:
            continue
        changes.append(
            {
                "path": key,
                "label": label,
                "before": before,
                "after": after,
            }
        )
    return changes
