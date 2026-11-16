from __future__ import annotations

from .models import LegacySource, SourceOperationLog


def _runtime_module():
    from . import operational_source_runtime

    return operational_source_runtime


def _operational_source_warning_message(
    source_id: str,
    registry_default_id: str | None,
) -> str:
    registry_label = (registry_default_id or "未設定").strip() or "未設定"
    return (
        f"DB primary が未整備だったため registry default ({registry_label}) から "
        f"{source_id} を自動補完しました。通常運用では DB の LegacySource.is_primary を正として"
        "確認が必要です。"
    )


def _bootstrap_operational_source_from_registry() -> LegacySource:
    runtime = _runtime_module()
    summary = runtime.source_summary(None)
    source_record = runtime._ensure_legacy_source_from_registry(None, force_primary=True)
    warning_message = _operational_source_warning_message(
        source_record.source_id,
        summary.get("source_id"),
    )
    runtime._source_runtime_module().logger.warning(warning_message)
    try:
        runtime.log_source_operation(
            source_id=source_record.source_id,
            operation_kind=SourceOperationLog.OperationKind.OPERATIONAL_SOURCE_BOOTSTRAP,
            before_payload={
                "requested_source_id": "",
                "has_db_primary_source": False,
                "registry_default_source_id": summary.get("source_id") or "",
                "resolution_kind": "registry_bootstrap_required",
                "used_registry_fallback": True,
            },
            after_payload={
                "source_id": source_record.source_id,
                "registry_default_source_id": summary.get("source_id") or "",
                "resolution_kind": "bootstrapped_db_primary",
                "used_registry_fallback": True,
                "is_primary": True,
            },
            editor_label="system",
            change_note=warning_message,
        )
    except runtime._DB_LOOKUP_ERRORS:
        pass
    return source_record


def ensure_operational_source_record(source_id: str | None = None) -> LegacySource:
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    if requested_source_id:
        existing = LegacySource.objects.filter(source_id=requested_source_id).first()
        if existing is not None:
            return existing
        return runtime._ensure_legacy_source_from_registry(requested_source_id, force_primary=False)
    primary = runtime._primary_legacy_source_record()
    if primary is not None:
        return primary
    return _bootstrap_operational_source_from_registry()
