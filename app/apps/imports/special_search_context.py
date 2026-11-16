from __future__ import annotations

from . import canonical_population
from .quality_runtime_shared import (
    _load_household_browser_dataset,
    latest_export_snapshot,
    resolve_runtime_source_entry,
    source_summary,
)
from .runtime_shared import _search_text


def _build_special_search_context(
    source_id: str | None = None,
    *,
    search_key: str | None = None,
    query: str = "",
    data_backend: str = "db",
    data_quality_context_builder,
    search_definitions: list[dict],
    resolve_key_fn,
    build_entries_fn,
    entry_matches_fn,
    data_quality_total_count_fn,
    build_counts_fn=None,
    build_selected_entries_fn=None,
) -> dict:
    del source_id
    source = resolve_runtime_source_entry()
    active_source_id = source["source_id"]
    latest_export = latest_export_snapshot(active_source_id)
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    snapshot_id = provenance_batch.prepared_snapshot_id if provenance_batch is not None else ""
    selected_search_key = resolve_key_fn(search_key)
    data_quality_context = (
        data_quality_context_builder(
            source_id=active_source_id,
            query=query,
        )
        if selected_search_key == "data_quality"
        else None
    )
    use_optimized_path = (
        build_counts_fn is not None
        and build_selected_entries_fn is not None
        and provenance_batch is not None
    )
    if not use_optimized_path:
        dataset = _load_household_browser_dataset(active_source_id, snapshot_id)
        data_quality_full_context = data_quality_context_builder(
            source_id=active_source_id,
            query="",
        )
        results_by_key = {
            definition["key"]: build_entries_fn(
                definition["key"],
                dataset,
                source_id=active_source_id,
                latest_batch=provenance_batch,
            )
            for definition in search_definitions
            if definition["key"] != "data_quality"
        }
        count_by_key = {
            definition["key"]: (
                data_quality_total_count_fn(data_quality_full_context)
                if definition["key"] == "data_quality"
                else len(results_by_key.get(definition["key"], []))
            )
            for definition in search_definitions
        }
        results = list(results_by_key.get(selected_search_key, []))
        selected_data_backend = dataset["data_backend"]
    else:
        count_by_key = build_counts_fn(
            source_id=active_source_id,
            latest_batch=provenance_batch,
        )
        if selected_search_key == "data_quality":
            results = []
            selected_data_backend = (
                data_quality_context.get("data_backend", data_backend)
                if data_quality_context is not None
                else data_backend
            )
        else:
            selected_payload = build_selected_entries_fn(
                selected_search_key,
                source_id=active_source_id,
                snapshot_id=snapshot_id,
                latest_batch=provenance_batch,
                data_backend=data_backend,
            )
            results = list(selected_payload["results"])
            selected_data_backend = selected_payload["data_backend"]
    if query and selected_search_key != "data_quality":
        needle = _search_text(query)
        results = [
            entry
            for entry in results
            if entry_matches_fn(entry, needle, search_key=selected_search_key)
        ]

    context = {
        "available": True,
        "selected_source_id": active_source_id,
        "source": source_summary(active_source_id),
        "latest_export": latest_export,
        "canonical_batch": provenance_batch,
        "canonical_snapshot_id": snapshot_id,
        "query": query,
        "selected_search_key": selected_search_key,
        "search_options": [
            {
                **definition,
                "selected": definition["key"] == selected_search_key,
                "result_count": count_by_key.get(definition["key"], 0),
            }
            for definition in search_definitions
        ],
        "results": results,
        "result_count": len(results),
        "data_backend": selected_data_backend,
    }
    if data_quality_context is not None:
        context.update(
            {
                "same_name_groups": data_quality_context["same_name_groups"],
                "same_name_group_count": data_quality_context["same_name_group_count"],
                "missing_death_date_members": data_quality_context["missing_death_date_members"],
                "missing_death_date_count": data_quality_context["missing_death_date_count"],
                "unknown_gender_members": data_quality_context["unknown_gender_members"],
                "unknown_gender_count": data_quality_context["unknown_gender_count"],
                "homyo_order_issue_members": data_quality_context["homyo_order_issue_members"],
                "homyo_order_issue_count": data_quality_context["homyo_order_issue_count"],
                "import_issue_breakdown": data_quality_context["import_issue_breakdown"],
                "import_issue_total": data_quality_context["import_issue_total"],
                "memorial_member_total": data_quality_context["memorial_member_total"],
            }
        )
    return context
