from __future__ import annotations

from . import (
    data_quality_runtime,
    special_search_batch_entries,
    special_search_catalog,
    special_search_context,
    special_search_counts,
    special_search_dataset_entries,
    special_search_selected_entries,
)
from .models import ImportBatch

SPECIAL_SEARCH_DEFINITIONS = special_search_catalog.SPECIAL_SEARCH_DEFINITIONS


def _build_special_search_entries(
    search_key: str,
    dataset: dict,
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    return special_search_catalog._build_special_search_entries(
        search_key,
        dataset,
        source_id=source_id,
        latest_batch=latest_batch,
        auto_generated_kana_builder=_build_auto_generated_kana_search_entries,
        kaimyo_contains_builder=_build_kaimyo_contains_search_entries,
        memorial_notice_opt_out_builder=_build_memorial_notice_opt_out_search_entries,
        recent_death_builder=_build_recent_death_search_entries,
        postal_non_head_recipient_builder=_build_postal_non_head_recipient_search_entries,
        memorial_head_person_builder=_build_memorial_head_person_search_entries,
        active_people_in_deleted_households_builder=_build_active_people_in_deleted_households_search_entries,
        deleted_head_person_households_builder=_build_deleted_head_person_household_search_entries,
        legacy_schedule_builder=_build_legacy_schedule_search_entries,
    )


def _build_auto_generated_kana_search_entries(dataset: dict) -> list[dict]:
    return special_search_dataset_entries._build_auto_generated_kana_search_entries(dataset)


def _build_kaimyo_contains_search_entries(dataset: dict) -> list[dict]:
    return special_search_dataset_entries._build_kaimyo_contains_search_entries(dataset)


def _build_memorial_notice_opt_out_search_entries(dataset: dict) -> list[dict]:
    return special_search_dataset_entries._build_memorial_notice_opt_out_search_entries(dataset)


def _build_recent_death_search_entries(dataset: dict) -> list[dict]:
    return special_search_dataset_entries._build_recent_death_search_entries(dataset)


def _build_memorial_head_person_search_entries(dataset: dict) -> list[dict]:
    return special_search_dataset_entries._build_memorial_head_person_search_entries(dataset)


def _build_postal_non_head_recipient_search_entries(
    *,
    source_id: str | None = None,
    latest_batch: ImportBatch | None = None,
) -> list[dict]:
    return special_search_batch_entries._build_postal_non_head_recipient_search_entries(
        source_id=source_id,
        latest_batch=latest_batch,
    )


def _build_active_people_in_deleted_households_search_entries(
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    return special_search_batch_entries._build_active_people_in_deleted_households_search_entries(
        source_id=source_id,
        latest_batch=latest_batch,
    )


def _build_deleted_head_person_household_search_entries(
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    return special_search_batch_entries._build_deleted_head_person_household_search_entries(
        source_id=source_id,
        latest_batch=latest_batch,
    )


def _build_legacy_schedule_search_entries(
    dataset: dict,
    *,
    source_id: str | None = None,
    latest_batch=None,
) -> list[dict]:
    return special_search_batch_entries._build_legacy_schedule_search_entries(
        dataset,
        source_id=source_id,
        latest_batch=latest_batch,
    )


def _build_special_search_context(
    source_id: str | None = None,
    *,
    search_key: str | None = None,
    query: str = "",
    data_backend: str = "db",
    data_quality_context_builder,
) -> dict:
    return special_search_context._build_special_search_context(
        source_id=source_id,
        search_key=search_key,
        query=query,
        data_backend=data_backend,
        data_quality_context_builder=data_quality_context_builder,
        search_definitions=SPECIAL_SEARCH_DEFINITIONS,
        resolve_key_fn=_resolve_special_search_key,
        build_entries_fn=_build_special_search_entries,
        entry_matches_fn=_special_search_entry_matches,
        data_quality_total_count_fn=_data_quality_total_count,
        build_counts_fn=_build_special_search_counts,
        build_selected_entries_fn=_build_selected_special_search_entries,
    )


def _build_special_search_counts(
    *,
    source_id: str | None,
    latest_batch: ImportBatch | None,
) -> dict[str, int]:
    return special_search_counts.build_special_search_counts(
        source_id=source_id,
        latest_batch=latest_batch,
    )


def _build_selected_special_search_entries(
    search_key: str,
    *,
    source_id: str,
    snapshot_id: str,
    latest_batch: ImportBatch,
    data_backend: str,
) -> dict:
    return special_search_selected_entries.build_selected_special_search_entries(
        search_key,
        source_id=source_id,
        snapshot_id=snapshot_id,
        latest_batch=latest_batch,
        data_backend=data_backend,
        build_entries_fn=_build_special_search_entries,
    )


def _legacy_build_special_search_context(
    source_id: str | None = None,
    *,
    search_key: str | None = None,
    query: str = "",
    data_backend: str = "db",
) -> dict:
    return _build_special_search_context(
        source_id=source_id,
        search_key=search_key,
        query=query,
        data_backend=data_backend,
        data_quality_context_builder=data_quality_runtime._legacy_build_data_quality_context,
    )


def _resolve_special_search_key(search_key: str | None) -> str:
    return special_search_catalog._resolve_special_search_key(
        search_key,
        special_search_definitions=SPECIAL_SEARCH_DEFINITIONS,
    )


def _data_quality_total_count(context: dict) -> int:
    return special_search_catalog._data_quality_total_count(context)


def _special_search_entry_matches(entry: dict, needle: str, *, search_key: str | None = None) -> bool:
    return special_search_catalog._special_search_entry_matches(
        entry,
        needle,
        search_key=search_key,
    )


__all__ = [
    "SPECIAL_SEARCH_DEFINITIONS",
    "_build_special_search_entries",
    "_legacy_build_special_search_context",
]
