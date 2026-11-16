from __future__ import annotations

from django.utils import timezone

from . import source_runtime


def _runtime_timezone():
    return timezone


def latest_export_snapshot(source_id: str) -> dict | None:
    return source_runtime.latest_export_snapshot(source_id)


def latest_import_batch_summary(source_id: str) -> dict | None:
    return source_runtime.latest_import_batch_summary(source_id)


def latest_succeeded_import_batch(source_id: str, *, snapshot_id: str | None = None):
    return source_runtime.latest_succeeded_import_batch(source_id, snapshot_id=snapshot_id)


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    return source_runtime.registered_sources(selected_source_id)


def resolve_runtime_source_entry() -> dict:
    return source_runtime.resolve_runtime_source_entry()


def source_summary(source_id: str | None = None) -> dict:
    return source_runtime.source_summary(source_id)


__all__ = [
    "_runtime_timezone",
    "latest_export_snapshot",
    "latest_import_batch_summary",
    "latest_succeeded_import_batch",
    "registered_sources",
    "resolve_runtime_source_entry",
    "source_summary",
]
