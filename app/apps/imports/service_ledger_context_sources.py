from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population, source_runtime


def _runtime_module():
    from . import service_ledger_runtime

    return service_ledger_runtime


def _resolve_service_ledger_source_context(source_id: str | None) -> dict:
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    if requested_source_id is None:
        active_source_id = runtime.resolve_runtime_source_entry()["source_id"]
        context_source = runtime.source_summary(active_source_id)
        context_registered_sources = runtime.registered_sources(active_source_id)
    else:
        active_source_id = source_runtime.operational_source_id(requested_source_id)
        context_source = source_runtime.operational_source_summary(active_source_id)
        context_registered_sources = []
    return {
        "active_source_id": active_source_id,
        "source": context_source,
        "registered_sources": context_registered_sources,
    }


def _service_ledger_unavailable_context(
    *,
    active_source_id: str,
    context_source: dict,
    query: str,
    message: str,
    latest_export: dict | None = None,
) -> dict:
    context = {
        "available": False,
        "selected_source_id": active_source_id,
        "source": context_source,
        "query": query,
        "message": message,
    }
    if latest_export is not None:
        context["latest_export"] = latest_export
    return context


def _load_service_ledger_dataset_and_schedules(active_source_id: str) -> dict:
    runtime = _runtime_module()
    latest_export = runtime.latest_export_snapshot(active_source_id)
    try:
        batch = canonical_population.canonical_provenance_import_batch(
            source_id=active_source_id,
        )
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "latest_export": latest_export,
            "latest_batch": None,
            "dataset": None,
            "schedules": None,
            "message": "DB の法要データを読み出せませんでした。",
        }
    if batch is None:
        return {
            "available": False,
            "latest_export": latest_export,
            "latest_batch": None,
            "dataset": None,
            "schedules": None,
            "message": "検索対象の現行台帳が見つかりません。",
        }
    snapshot_id = batch.prepared_snapshot_id or ""
    try:
        dataset = runtime._load_household_browser_dataset(
            active_source_id,
            snapshot_id,
            data_backend="db",
            canonical_population_checked=True,
        )
        schedules = runtime._load_service_ledger_schedules(
            batch,
            canonical_population_checked=True,
        )
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "latest_export": latest_export,
            "latest_batch": batch,
            "dataset": None,
            "schedules": None,
            "message": "DB の法要データを読み出せませんでした。",
        }
    return {
        "available": True,
        "latest_export": latest_export,
        "latest_batch": batch,
        "dataset": dataset,
        "schedules": schedules,
        "message": "",
    }


def _resolve_home_service_ledger_batch(
    source_id: str | None = None,
    *,
    latest_export: dict | None = None,
    batch=None,
    canonical_population_checked: bool = False,
):
    runtime = _runtime_module()
    if canonical_population_checked:
        return {
            "available": batch is not None,
            "latest_export": latest_export,
            "latest_batch": batch,
            "message": "",
        }

    resolved_batch = None
    resolved_latest_export = latest_export
    requested_source_id = source_id
    if requested_source_id is None and batch is not None:
        requested_source_id = batch.source.source_id
    active_source_id = source_runtime.operational_source_id(requested_source_id)
    resolved_latest_export = resolved_latest_export or runtime.latest_export_snapshot(
        active_source_id
    )
    try:
        resolved_batch = canonical_population.canonical_provenance_import_batch(
            source_id=active_source_id,
        )
    except (OperationalError, ProgrammingError):
        resolved_batch = None
    if resolved_batch is None:
        return {
            "available": False,
            "latest_export": resolved_latest_export,
            "latest_batch": None,
            "message": "",
        }
    return {
        "available": True,
        "latest_export": resolved_latest_export,
        "latest_batch": resolved_batch,
        "message": "",
    }


def _load_home_service_ledger_schedules(batch) -> dict:
    runtime = _runtime_module()
    try:
        schedules = runtime._load_service_ledger_schedules(
            batch,
            canonical_population_checked=True,
        )
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "schedules": [],
        }
    return {
        "available": True,
        "schedules": schedules,
    }


def _load_service_target_people_or_empty(batch) -> list:
    runtime = _runtime_module()
    try:
        return runtime._load_service_target_people(
            batch,
            canonical_population_checked=True,
        )
    except (OperationalError, ProgrammingError):
        return []
