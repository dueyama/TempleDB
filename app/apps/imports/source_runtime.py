from __future__ import annotations

import logging
from pathlib import Path

from django.db.utils import OperationalError, ProgrammingError

from config.runtime_paths import (
    analysis_root as runtime_analysis_root,  # noqa: F401
)
from config.runtime_paths import (
    exports_root as runtime_exports_root,  # noqa: F401
)
from config.runtime_paths import (
    prepared_root as runtime_prepared_root,  # noqa: F401
)
from config.source_registry import (
    default_source_id as registry_default_source_id,  # noqa: F401
)
from config.source_registry import (
    get_source,
)
from config.source_registry import (
    list_sources as list_sources,
)
from config.source_registry import (
    remove_source as registry_remove_source,  # noqa: F401
)
from config.source_registry import (
    set_default_source as registry_set_default_source,  # noqa: F401
)
from config.source_registry import (
    upsert_source as upsert_source,
)

from . import operational_source_runtime, source_operation_runtime, source_registry_runtime
from .models import ImportBatch, LegacySource

logger = logging.getLogger(__name__)
_REGISTRY_ERRORS = source_registry_runtime._REGISTRY_ERRORS


_current_base_dir = source_registry_runtime._current_base_dir
_json = source_registry_runtime._json
_timestamp = source_registry_runtime._timestamp
_analysis_snapshot_id = source_registry_runtime._analysis_snapshot_id
_sha256 = source_registry_runtime._sha256


def base_dir() -> Path:
    from config.runtime_paths import tenant_root

    return tenant_root()


def runtime_source_id() -> str:
    return get_source(None)["source_id"]


_registry_source_entry = source_registry_runtime._registry_source_entry
_resolved_source_path = source_registry_runtime._resolved_source_path
current_source_path = source_registry_runtime.current_source_path


def ensure_operational_source_record(source_id: str | None = None) -> LegacySource:
    return operational_source_runtime.ensure_operational_source_record(source_id)


def operational_source_id(source_id: str | None = None) -> str:
    return operational_source_runtime.operational_source_id(source_id)


def resolve_operational_source_entry(source_id: str | None = None) -> dict:
    return operational_source_runtime.resolve_operational_source_entry(source_id)


operational_source_summary = operational_source_runtime.operational_source_summary


def operational_source_status(source_id: str | None = None) -> dict:
    return operational_source_runtime.operational_source_status(source_id)


def resolve_runtime_source_entry() -> dict:
    try:
        return resolve_operational_source_entry()
    except RuntimeError:
        return resolve_source_entry()


def resolve_source_entry(source_id: str | None = None) -> dict:
    return source_registry_runtime.resolve_source_entry(source_id)


remove_registered_source = source_registry_runtime.remove_registered_source
source_mdb_path = source_registry_runtime.source_mdb_path
export_root = source_registry_runtime.export_root
prepared_root = source_registry_runtime.prepared_root
analysis_root = source_registry_runtime.analysis_root
analysis_dir = source_registry_runtime.analysis_dir
build_home_context_payload = source_operation_runtime.build_home_context_payload
private_sources_root = source_registry_runtime.private_sources_root
originaldb_root = source_registry_runtime.originaldb_root
_source_input_roots = source_registry_runtime._source_input_roots
_relative_source_workspace_path = source_registry_runtime._relative_source_workspace_path
_display_path = source_registry_runtime._display_path
_suggest_source_id = source_registry_runtime._suggest_source_id
discover_source_files = source_registry_runtime.discover_source_files
discover_originaldb_mdbs = source_registry_runtime.discover_originaldb_mdbs
register_source_file = source_registry_runtime.register_source_file
register_originaldb_source = source_registry_runtime.register_originaldb_source
set_default_source = source_registry_runtime.set_default_source


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    requested_source_id = (selected_source_id or "").strip() or None
    try:
        return source_registry_runtime.registered_sources(requested_source_id)
    except _REGISTRY_ERRORS:
        if requested_source_id is not None:
            try:
                source_record = LegacySource.objects.filter(source_id=requested_source_id).first()
            except (OperationalError, ProgrammingError):
                source_record = None
            if source_record is None:
                raise
            summary = operational_source_summary(requested_source_id)
        else:
            summary = operational_source_summary(None)
        return [
            {
                **summary,
                "selected": True,
            }
        ]


def source_summary(source_id: str | None = None):
    requested_source_id = (source_id or "").strip() or None
    if requested_source_id is not None:
        try:
            source_record = LegacySource.objects.filter(source_id=requested_source_id).first()
        except (OperationalError, ProgrammingError):
            source_record = None
        if source_record is not None:
            return operational_source_summary(requested_source_id)
    try:
        return source_registry_runtime.source_summary(requested_source_id)
    except _REGISTRY_ERRORS:
        if requested_source_id is None:
            return operational_source_summary(None)
        raise


def latest_export_snapshot(source_id: str) -> dict | None:
    return source_operation_runtime.latest_export_snapshot(source_id)


recent_export_snapshots = source_operation_runtime.recent_export_snapshots
latest_prepared_snapshot = source_operation_runtime.latest_prepared_snapshot
analysis_summary = source_operation_runtime.analysis_summary
latest_import_batch_summary = source_operation_runtime.latest_import_batch_summary
latest_import_batch = source_operation_runtime.latest_import_batch
import_batch_summary = source_operation_runtime.import_batch_summary
_ensure_source_record_for_logging = source_operation_runtime._ensure_source_record_for_logging
log_source_operation = source_operation_runtime.log_source_operation
recent_source_operation_entries = source_operation_runtime.recent_source_operation_entries


def latest_succeeded_import_batch(
    source_id: str,
    snapshot_id: str | None = None,
    raise_db_errors: bool = False,
) -> ImportBatch | None:
    return source_operation_runtime.latest_succeeded_import_batch(
        source_id,
        snapshot_id=snapshot_id,
        raise_db_errors=raise_db_errors,
    )


recent_import_batches = source_operation_runtime.recent_import_batches
