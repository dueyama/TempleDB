from __future__ import annotations

from django.utils import timezone

from . import browser_dataset, data_science_runtime, source_runtime


def _runtime_timezone():
    return timezone


def _load_household_browser_dataset(
    source_id: str,
    snapshot_id: str,
    *,
    data_backend: str = "db",
) -> dict:
    return browser_dataset._load_household_browser_dataset(
        source_id,
        snapshot_id,
        data_backend=data_backend,
    )


def latest_export_snapshot(source_id: str) -> dict | None:
    return source_runtime.latest_export_snapshot(source_id)


def latest_succeeded_import_batch(source_id: str, *, snapshot_id: str | None = None):
    return source_runtime.latest_succeeded_import_batch(source_id, snapshot_id=snapshot_id)


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    return source_runtime.registered_sources(selected_source_id)


def resolve_runtime_source_entry() -> dict:
    return source_runtime.resolve_runtime_source_entry()


def source_summary(source_id: str | None = None) -> dict:
    return source_runtime.source_summary(source_id)


def _member_field_value(member: dict, label: str) -> str:
    return data_science_runtime._member_field_value(member, label)


def _homyo_order_issue(member: dict) -> dict | None:
    return data_science_runtime._homyo_order_issue(member)


def _normalize_gender(value: str) -> str:
    return data_science_runtime._normalize_gender(value)


__all__ = [
    "_homyo_order_issue",
    "_load_household_browser_dataset",
    "_member_field_value",
    "_normalize_gender",
    "_runtime_timezone",
    "latest_export_snapshot",
    "latest_succeeded_import_batch",
    "registered_sources",
    "resolve_runtime_source_entry",
    "source_summary",
]
