from __future__ import annotations

from collections.abc import Callable

from . import quality_runtime_shared, special_search_db_entries
from .models import ImportBatch

_DATABASE_ONLY_KEYS = {
    "postal_non_head_recipient",
    "active_people_in_deleted_households",
    "deleted_head_person_households",
    "legacy_schedules",
}


def build_selected_special_search_entries(
    search_key: str,
    *,
    source_id: str,
    snapshot_id: str,
    latest_batch: ImportBatch,
    data_backend: str,
    build_entries_fn: Callable,
) -> dict:
    # The historical special-search context always used the canonical DB path.
    # Keep that compatibility contract while the public signature still carries
    # data_backend.
    del data_backend
    if search_key == "recent_deaths":
        return {
            "results": special_search_db_entries.build_recent_death_search_entries(
                source_id=source_id,
                latest_batch=latest_batch,
            ),
            "data_backend": "db",
        }

    if search_key in _DATABASE_ONLY_KEYS:
        dataset = {"data_backend": "db", "household_details": {}}
    else:
        dataset = quality_runtime_shared._load_household_browser_dataset(
            source_id,
            snapshot_id,
        )
    return {
        "results": build_entries_fn(
            search_key,
            dataset,
            source_id=source_id,
            latest_batch=latest_batch,
        ),
        "data_backend": dataset["data_backend"],
    }
