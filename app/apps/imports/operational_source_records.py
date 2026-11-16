from __future__ import annotations

from pathlib import Path

from django.db.utils import OperationalError, ProgrammingError

from .models import LegacySource, SourceOperationLog


def _runtime_module():
    from . import operational_source_runtime

    return operational_source_runtime


def _primary_legacy_source_record() -> LegacySource | None:
    try:
        return LegacySource.objects.filter(is_primary=True).order_by("source_id").first()
    except (OperationalError, ProgrammingError):
        return None


def _source_entry_from_legacy_source(source_record: LegacySource) -> dict:
    runtime = _runtime_module()
    registry_source = runtime._registry_source_entry(source_record.source_id)
    resolved_path = runtime._resolved_source_path(
        registry_source,
        legacy_file_path=source_record.file_path,
    )
    if registry_source is not None:
        path_text = (
            (registry_source.get("path") or "").strip()
            or (registry_source.get("file_path") or "").strip()
            or str(resolved_path)
        )
    else:
        path_text = (source_record.file_path or "").strip() or str(resolved_path)
    return {
        "source_id": source_record.source_id,
        "label": source_record.label or source_record.source_id,
        "path": path_text,
        "status": source_record.status or "registered",
        "notes": source_record.notes or "",
        "resolved_path": resolved_path,
        "is_default": bool(source_record.is_primary),
    }


def _legacy_source_defaults_from_summary(summary: dict, *, is_primary: bool) -> dict:
    resolved_path = Path(summary["resolved_path"])
    return {
        "label": summary.get("label", summary["source_id"]),
        "file_path": str(resolved_path),
        "file_name": resolved_path.name,
        "sha256": summary.get("sha256") or "",
        "status": summary.get("status", "registered"),
        "notes": summary.get("notes", ""),
        "is_primary": is_primary,
    }


def _sync_legacy_source_from_summary(
    source_record: LegacySource,
    summary: dict,
    *,
    is_primary: bool,
) -> LegacySource:
    defaults = _legacy_source_defaults_from_summary(summary, is_primary=is_primary)
    updates: list[str] = []
    for field_name, expected in defaults.items():
        if getattr(source_record, field_name) != expected:
            setattr(source_record, field_name, expected)
            updates.append(field_name)
    if updates:
        source_record.save(update_fields=updates + ["updated_at"])
    return source_record


def _ensure_legacy_source_from_registry(
    source_id: str | None = None,
    *,
    force_primary: bool,
) -> LegacySource:
    runtime = _runtime_module()
    summary = runtime.source_summary(source_id)
    defaults = _legacy_source_defaults_from_summary(summary, is_primary=force_primary)
    source_record, _created = LegacySource.objects.get_or_create(
        source_id=summary["source_id"],
        defaults=defaults,
    )
    return _sync_legacy_source_from_summary(source_record, summary, is_primary=force_primary)


def _latest_operational_source_bootstrap_log(
    source_record: LegacySource | None,
) -> SourceOperationLog | None:
    if source_record is None:
        return None
    try:
        return (
            SourceOperationLog.objects.filter(
                source=source_record,
                operation_kind=SourceOperationLog.OperationKind.OPERATIONAL_SOURCE_BOOTSTRAP,
            )
            .order_by("-created_at", "-id")
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None
