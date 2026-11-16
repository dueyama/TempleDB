from __future__ import annotations

from .browser_dataset_sqlite_loaders import (
    _load_household_browser_dataset_from_sqlite,
    _load_household_browser_summary_dataset_from_sqlite,
)


def _dataset_runtime_module():
    from . import household_browser_dataset_runtime

    return household_browser_dataset_runtime


def _latest_export_snapshot(source_id: str) -> dict | None:
    return _dataset_runtime_module().latest_export_snapshot(source_id)


def _latest_succeeded_import_batch(source_id: str, *, snapshot_id: str | None = None):
    return _dataset_runtime_module().latest_succeeded_import_batch(
        source_id,
        snapshot_id=snapshot_id,
    )


def _empty_household_browser_dataset() -> dict:
    return {
        "households": [],
        "household_details": {},
        "memorial_rules": [],
        "same_name_groups": {},
        "same_name_group_total": 0,
    }


def _empty_household_browser_summary_dataset() -> dict:
    return {
        "households": [],
        "household_rows": {},
        "households_by_id": {},
        "persons_by_household": {},
        "events_by_household": {},
        "memorial_search_index": {},
        "memorial_rules": [],
        "same_name_groups": {},
        "same_name_group_total": 0,
    }


def _runtime_data_backend(data_backend: str | None) -> str:
    backend = (data_backend or "db").strip().lower()
    if backend in {"", "auto", "db"}:
        return "db"
    raise ValueError(f"household browser runtime only supports db backend: {data_backend}")


def _load_household_browser_dataset(
    source_id: str,
    snapshot_id: str,
    *,
    data_backend: str = "db",
    canonical_population_checked: bool = False,
) -> dict:
    _runtime_data_backend(data_backend)
    dataset = _load_household_browser_dataset_from_sqlite(
        source_id,
        snapshot_id,
        None,
        canonical_population_checked=canonical_population_checked,
    )

    return {
        **dataset,
        "data_backend": "db",
    }


def _load_household_browser_summary_dataset(
    source_id: str,
    snapshot_id: str,
    *,
    data_backend: str = "db",
    canonical_population_checked: bool = False,
) -> dict:
    _runtime_data_backend(data_backend)
    dataset = _load_household_browser_summary_dataset_from_sqlite(
        source_id,
        snapshot_id,
        None,
        canonical_population_checked=canonical_population_checked,
    )
    return {
        **dataset,
        "data_backend": "db",
    }
