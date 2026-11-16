from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from .models import ImportBatch, LegacySource, SourceOperationLog
from .source_operation_history_compat import source_operation_kind_label
from .source_registry_runtime import (
    _analysis_snapshot_id,
    _json,
    _timestamp,
    analysis_dir,
    export_root,
    prepared_root,
)


def _source_runtime_module():
    from . import source_runtime

    return source_runtime


def build_home_context_payload(source_id: str | None = None) -> dict:
    del source_id
    source = _source_runtime_module().resolve_runtime_source_entry()
    active_source_id = source["source_id"]
    source_info = _source_runtime_module().source_summary(active_source_id)
    latest_export = _source_runtime_module().latest_export_snapshot(active_source_id)
    return {
        "selected_source_id": active_source_id,
        "default_source_id": _source_runtime_module().runtime_source_id(),
        "source": source_info,
        "latest_export": latest_export,
    }


def latest_export_snapshot(source_id: str) -> dict | None:
    latest = _json(export_root(source_id) / "latest.json")
    if not latest:
        return None
    snapshot_id = latest["latest_snapshot_id"]
    snapshot_dir = export_root(source_id) / snapshot_id
    manifest = _json(snapshot_dir / "manifest.json") or {}
    return {
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "snapshot_dir": snapshot_dir,
        "manifest": manifest,
        "table_count": manifest.get("export_settings", {}).get("table_count"),
        "created_at": manifest.get("snapshot", {}).get("created_at"),
        "log_path": snapshot_dir / "export.log",
    }


def recent_export_snapshots(source_id: str, limit: int = 5) -> list[dict]:
    root = export_root(source_id)
    if not root.exists():
        return []
    snapshots = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        manifest = _json(child / "manifest.json")
        if not manifest:
            continue
        snapshots.append(
            {
                "snapshot_id": child.name,
                "table_count": manifest.get("export_settings", {}).get("table_count"),
                "created_at": manifest.get("snapshot", {}).get("created_at"),
            }
        )
        if len(snapshots) >= limit:
            break
    return snapshots


def latest_prepared_snapshot(source_id: str) -> dict | None:
    latest = _json(prepared_root(source_id) / "latest.json")
    if not latest:
        return None
    snapshot_id = latest["latest_snapshot_id"]
    prepared_dir = prepared_root(source_id) / snapshot_id
    manifest = _json(prepared_dir / "raw_manifest.json") or {}
    return {
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "prepared_dir": prepared_dir,
        "table_count": len(manifest.get("tables", [])),
        "manifest": manifest,
        "raw_manifest_path": prepared_dir / "raw_manifest.json",
        "updated_at": _timestamp(prepared_dir / "raw_manifest.json"),
    }


def analysis_summary(source_id: str) -> dict:
    root = analysis_dir(source_id)
    schema_report = root / "schema_report.md"
    table_summary = root / "table_summary.csv"
    column_profiles = root / "column_profiles.csv"
    stamps = [
        stamp
        for stamp in (
            _timestamp(schema_report),
            _timestamp(table_summary),
            _timestamp(column_profiles),
        )
        if stamp
    ]
    return {
        "schema_report_path": schema_report,
        "table_summary_path": table_summary,
        "column_profiles_path": column_profiles,
        "has_outputs": schema_report.exists()
        and table_summary.exists()
        and column_profiles.exists(),
        "updated_at": max(stamps) if stamps else None,
        "snapshot_id": _analysis_snapshot_id(schema_report),
    }


def latest_import_batch_summary(source_id: str) -> dict | None:
    try:
        batch = (
            ImportBatch.objects.filter(source__source_id=source_id)
            .select_related("source")
            .order_by("-created_at")
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None
    if batch is None:
        return None
    return import_batch_summary(batch)


def latest_import_batch(source_id: str) -> ImportBatch | None:
    try:
        return (
            ImportBatch.objects.filter(source__source_id=source_id)
            .select_related("source")
            .order_by("-created_at")
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None


def import_batch_summary(batch: ImportBatch) -> dict:
    return {
        "id": batch.pk,
        "batch_uuid": str(batch.batch_uuid),
        "prepared_snapshot_id": batch.prepared_snapshot_id,
        "status": batch.status,
        "mode": batch.mode,
        "created_at": batch.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": batch.finished_at.strftime("%Y-%m-%d %H:%M:%S") if batch.finished_at else None,
        "households_imported": batch.households_imported,
        "persons_imported": batch.persons_imported,
        "deceased_profiles_imported": batch.deceased_profiles_imported,
        "service_schedules_imported": batch.service_schedules_imported,
        "issues_count": batch.issues_count,
        "summary": batch.summary,
    }


def _ensure_source_record_for_logging(source_id: str | None) -> LegacySource:
    if source_id:
        existing = LegacySource.objects.filter(source_id=source_id).first()
        if existing is not None:
            return existing
    summary = _source_runtime_module().source_summary(source_id)
    source_record, _created = LegacySource.objects.get_or_create(
        source_id=summary["source_id"],
        defaults={
            "label": summary.get("label", summary["source_id"]),
            "file_path": str(summary["resolved_path"]),
            "file_name": summary["resolved_path"].name,
            "sha256": summary.get("sha256") or "",
            "status": summary.get("status") or "registered",
            "notes": summary.get("notes") or "",
            "is_primary": bool(summary.get("is_primary")),
        },
    )
    return source_record


def log_source_operation(
    *,
    source_id: str | None,
    operation_kind: str,
    target_batch: ImportBatch | None = None,
    before_payload: dict | None = None,
    after_payload: dict | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> SourceOperationLog:
    try:
        normalized_operation_kind = SourceOperationLog.OperationKind(operation_kind).value
    except ValueError as exc:
        raise ValueError(f"Unsupported source operation kind: {operation_kind}") from exc
    source_record = _ensure_source_record_for_logging(source_id)
    return SourceOperationLog.objects.create(
        source=source_record,
        target_batch=target_batch,
        operation_kind=normalized_operation_kind,
        before_payload=before_payload or {},
        after_payload=after_payload or {},
        editor_label=(editor_label or "").strip(),
        change_note=(change_note or "").strip(),
    )


def recent_source_operation_entries(source_id: str | None, *, limit: int = 10) -> list[dict]:
    resolved = _source_runtime_module().resolve_source_entry(source_id)
    try:
        rows = (
            SourceOperationLog.objects.filter(source__source_id=resolved["source_id"])
            .select_related("target_batch")
            .order_by("-created_at", "-id")[:limit]
        )
    except (OperationalError, ProgrammingError):
        return []
    entries: list[dict] = []
    for log in rows:
        target_batch = log.target_batch
        entries.append(
            {
                "log": log,
                "operation_label": source_operation_kind_label(
                    log.operation_kind,
                    log.get_operation_kind_display(),
                ),
                "target_label": (
                    target_batch.prepared_snapshot_id
                    if target_batch is not None
                    else (log.after_payload.get("visible_snapshot_id") or "")
                ),
            }
        )
    return entries


def latest_succeeded_import_batch(
    source_id: str,
    snapshot_id: str | None = None,
    raise_db_errors: bool = False,
) -> ImportBatch | None:
    try:
        rows = ImportBatch.objects.filter(
            source__source_id=source_id,
            status=ImportBatch.Status.SUCCEEDED,
        ).select_related("source")
        if snapshot_id:
            rows = rows.filter(prepared_snapshot_id=snapshot_id)
        return rows.order_by("-created_at").first()
    except (OperationalError, ProgrammingError):
        if raise_db_errors:
            raise
        return None


def recent_import_batches(source_id: str, limit: int = 5) -> list[dict]:
    try:
        latest_succeeded = (
            ImportBatch.objects.filter(
                source__source_id=source_id,
                status=ImportBatch.Status.SUCCEEDED,
            )
            .order_by("-created_at")
            .first()
        )
        latest_succeeded_id = latest_succeeded.pk if latest_succeeded is not None else None
        rows = ImportBatch.objects.filter(source__source_id=source_id).order_by("-created_at")[:limit]
    except (OperationalError, ProgrammingError):
        return []
    return [
        {
            **import_batch_summary(row),
            "is_current": row.pk == latest_succeeded_id and row.status == ImportBatch.Status.SUCCEEDED,
        }
        for row in rows
    ]
