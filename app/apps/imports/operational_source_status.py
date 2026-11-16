from __future__ import annotations

from pathlib import Path

from django.db.utils import OperationalError, ProgrammingError

from .models import LegacySource


def _runtime_module():
    from . import operational_source_runtime

    return operational_source_runtime


def operational_source_id(source_id: str | None = None) -> str:
    return _runtime_module().ensure_operational_source_record(source_id).source_id


def resolve_operational_source_entry(source_id: str | None = None) -> dict:
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    source_record = runtime.ensure_operational_source_record(source_id)
    if requested_source_id is None and source_record.is_primary:
        source = runtime._source_entry_from_legacy_source(source_record)
    else:
        try:
            source = runtime.resolve_source_entry(source_record.source_id)
        except KeyError:
            source = runtime._source_entry_from_legacy_source(source_record)
    return {
        **source,
        "is_default": bool(source_record.is_primary),
    }


def operational_source_summary(source_id: str | None = None) -> dict:
    runtime = _runtime_module()
    source_record = runtime.ensure_operational_source_record(source_id)
    source = runtime._source_entry_from_legacy_source(source_record)
    path = Path(source["resolved_path"])
    exists = path.exists()
    return {
        "source_id": source_record.source_id,
        "label": source_record.label or source_record.source_id,
        "status": source_record.status or "registered",
        "is_default": bool(source_record.is_primary),
        "notes": source_record.notes or "",
        "path": path,
        "resolved_path": path,
        "exists": exists,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if exists else None,
        "sha256": runtime._sha256(path) if exists else None,
    }


def operational_source_status(source_id: str | None = None) -> dict:
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    base_status = {
        "source_id": "",
        "label": "",
        "registry_default_source_id": "",
        "resolution_kind": "operational_source_unavailable",
        "used_registry_fallback": False,
        "has_bootstrap_warning": False,
        "warning_message": "",
        "bootstrap_logged_at": "",
        "exists": False,
    }

    if requested_source_id:
        try:
            source_record = LegacySource.objects.filter(source_id=requested_source_id).first()
        except (OperationalError, ProgrammingError):
            source_record = None
        if source_record is not None:
            source = runtime._source_entry_from_legacy_source(source_record)
            path = Path(source["resolved_path"])
            exists = path.exists()
            bootstrap_log = runtime._latest_operational_source_bootstrap_log(source_record)
            warning_message = (bootstrap_log.change_note or "").strip() if bootstrap_log is not None else ""
            return {
                **base_status,
                "source_id": source_record.source_id,
                "label": source_record.label or source_record.source_id,
                "status": source_record.status or "registered",
                "is_default": bool(source_record.is_primary),
                "notes": source_record.notes or "",
                "path": path,
                "resolved_path": path,
                "exists": exists,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if exists else None,
                "sha256": runtime._sha256(path) if exists else None,
                "registry_default_source_id": (
                    (bootstrap_log.after_payload.get("registry_default_source_id") or "").strip()
                    if bootstrap_log is not None
                    else ""
                ),
                "resolution_kind": "explicit_db_source",
                "has_bootstrap_warning": bootstrap_log is not None,
                "warning_message": warning_message,
                "bootstrap_logged_at": (
                    bootstrap_log.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if bootstrap_log is not None
                    else ""
                ),
            }
        try:
            summary = runtime.source_summary(requested_source_id)
        except runtime._REGISTRY_ERRORS:
            return {
                **base_status,
                "source_id": requested_source_id,
                "resolution_kind": "operational_source_unavailable",
                "has_bootstrap_warning": True,
                "warning_message": (
                    f"通常運用 source {requested_source_id} を解決できません。"
                    " DB と registry を確認してください。"
                ),
            }
        return {
            **base_status,
            **summary,
            "registry_default_source_id": "",
            "resolution_kind": "explicit_registry_source",
        }

    primary = runtime._primary_legacy_source_record()
    if primary is not None:
        source = runtime._source_entry_from_legacy_source(primary)
        path = Path(source["resolved_path"])
        exists = path.exists()
        bootstrap_log = runtime._latest_operational_source_bootstrap_log(primary)
        warning_message = (bootstrap_log.change_note or "").strip() if bootstrap_log is not None else ""
        resolution_kind = "db_primary" if bootstrap_log is None else "bootstrapped_db_primary"
        return {
            **base_status,
            "source_id": primary.source_id,
            "label": primary.label or primary.source_id,
            "status": primary.status or "registered",
            "is_default": bool(primary.is_primary),
            "notes": primary.notes or "",
            "path": path,
            "resolved_path": path,
            "exists": exists,
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if exists else None,
            "sha256": runtime._sha256(path) if exists else None,
            "registry_default_source_id": (
                (bootstrap_log.after_payload.get("registry_default_source_id") or "").strip()
                if bootstrap_log is not None
                else ""
            ),
            "resolution_kind": resolution_kind,
            "used_registry_fallback": bootstrap_log is not None,
            "has_bootstrap_warning": bootstrap_log is not None,
            "warning_message": warning_message,
            "bootstrap_logged_at": (
                bootstrap_log.created_at.strftime("%Y-%m-%d %H:%M:%S") if bootstrap_log is not None else ""
            ),
        }

    try:
        summary = runtime.source_summary(None)
    except runtime._REGISTRY_ERRORS:
        return {
            **base_status,
            "resolution_kind": "operational_source_unavailable",
            "has_bootstrap_warning": True,
            "warning_message": (
                "DB primary が未整備で、registry default も解決できません。"
                "通常運用 source を確定できない状態です。"
            ),
        }
    warning_message = runtime._operational_source_warning_message(
        summary["source_id"],
        summary.get("source_id"),
    )
    return {
        **base_status,
        **summary,
        "registry_default_source_id": summary["source_id"],
        "resolution_kind": "registry_bootstrap_required",
        "used_registry_fallback": True,
        "has_bootstrap_warning": True,
        "warning_message": warning_message,
    }
