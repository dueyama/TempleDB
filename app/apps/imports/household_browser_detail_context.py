from __future__ import annotations

from datetime import date, timedelta

from . import browser_dataset, canonical_population, runtime_shared
from .household_memorial_candidate_actions import build_household_rinju_records
from .household_memorial_candidates_runtime import (
    _attach_action_to_memorial_candidates,
    _build_memorial_candidates,
    _decorate_memorial_members,
    _parse_input_date,
)


def _runtime_module():
    from . import household_browser_detail_runtime

    return household_browser_detail_runtime


def _load_household_browser_context_dataset(source_id: str, snapshot_id: str) -> dict:
    runtime = _runtime_module()
    return runtime._load_household_browser_summary_dataset(source_id, snapshot_id, data_backend="db")


def _legacy_build_household_browser_context(
    source_id: str | None = None,
    query: str = "",
    household_id: str | None = None,
    candidate_from: str | None = None,
    candidate_to: str | None = None,
    kana_group: str | None = None,
    data_backend: str = "db",
    include_memorial_search: bool = False,
    auto_select_first: bool = True,
) -> dict:
    del data_backend
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    if requested_source_id is None:
        active_source_id = runtime.resolve_runtime_source_entry()["source_id"]
        context_source = runtime.source_summary(active_source_id)
        context_registered_sources = runtime.registered_sources(active_source_id)
    else:
        active_source_id = runtime_shared._clean_value(requested_source_id)
        context_source = {
            "source_id": active_source_id,
            "label": active_source_id,
            "status": "registered",
        }
        context_registered_sources = []
    requested_group_key = kana_group if kana_group in runtime.HOUSEHOLD_KANA_GROUP_KEYS else None
    selected_group_key = "all" if runtime_shared._search_text(query) else (requested_group_key or "a")
    if household_id and requested_group_key is None:
        selected_group_key = "all"
    latest_export = runtime.latest_export_snapshot(active_source_id)
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    period_start = _parse_input_date(candidate_from) or date.today()
    period_end = _parse_input_date(candidate_to) or (period_start + timedelta(days=365))
    if period_end < period_start:
        period_start, period_end = period_end, period_start
    if canonical_batch is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "source": context_source,
            "query": query,
            "include_memorial_search": include_memorial_search,
            "kana_group": selected_group_key,
            "kana_groups": [],
            "selected_group_label": runtime.HOUSEHOLD_KANA_GROUP_LABELS[selected_group_key],
            "candidate_from": period_start.isoformat(),
            "candidate_to": period_end.isoformat(),
            "results": [],
            "selected_household": None,
            "detail": None,
            "message": "検索対象の現行台帳が見つかりません。",
            "data_backend": "db",
        }

    canonical_snapshot_id = canonical_batch.prepared_snapshot_id or ""
    dataset = _load_household_browser_context_dataset(
        active_source_id,
        canonical_snapshot_id,
    )
    households = dataset["households"]
    filtered_households = runtime._filter_households(
        households,
        query,
        selected_group_key,
        household_details=dataset.get("household_details"),
        memorial_search_index=dataset.get("memorial_search_index"),
        include_memorial_search=include_memorial_search,
    )
    kana_groups = runtime._build_household_group_buttons(
        households,
        filtered_households,
        selected_group_key,
    )
    selected_household_id = household_id or (
        filtered_households[0]["household_id"] if filtered_households and auto_select_first else None
    )
    if selected_household_id and not any(
        row["household_id"] == selected_household_id for row in filtered_households
    ):
        selected_household_id = (
            filtered_households[0]["household_id"] if filtered_households and auto_select_first else None
        )
    detail = None
    if selected_household_id:
        detail = dataset.get("household_details", {}).get(selected_household_id)
        if detail is None:
            detail = browser_dataset._build_household_browser_detail_from_summary_dataset(
                dataset,
                selected_household_id,
            )
    detail_context = None
    if detail is not None:
        memorial_members = _decorate_memorial_members(
            detail["memorial_members"],
            dataset["memorial_rules"],
            period_start,
            period_end,
            detail.get("events", []),
        )
        display_current_members = runtime._exclude_head_person_from_member_list(
            detail.get("current_members", []),
            detail.get("head_person_id", ""),
        )
        display_memorial_members = runtime._exclude_head_person_from_member_list(
            memorial_members,
            detail.get("head_person_id", ""),
        )
        on_demand_candidates = _build_memorial_candidates(
            memorial_members,
            dataset["memorial_rules"],
            period_start,
            period_end,
        )
        on_demand_candidates = _attach_action_to_memorial_candidates(
            on_demand_candidates,
            detail.get("events", []),
        )
        detail_context = {
            **detail,
            "summary": {
                **detail.get("summary", {}),
                "current_count": len(display_current_members),
                "memorial_count": len(display_memorial_members),
            },
            "household_fields": runtime._household_browser_household_fields(
                active_source_id,
                selected_household_id or "",
                detail.get("household_fields", []),
                detail.get("head_person_fields", []),
            ),
            "postal_delivery_summary": runtime._household_browser_postal_delivery_summary(
                active_source_id,
                selected_household_id or "",
                detail.get("household_fields", []),
                detail.get("head_person_fields", []),
                detail.get("current_members", []),
            ),
            "head_ledger_status": runtime._household_head_ledger_status(
                detail.get("summary", {}).get("name", ""),
                detail.get("head_person_fields", []),
                detail.get("current_members", []),
                detail.get("memorial_members", []),
            ),
            "current_members": display_current_members,
            "memorial_members": display_memorial_members,
            "on_demand_candidates": on_demand_candidates,
            "rinju_records": build_household_rinju_records(memorial_members, detail.get("events", [])),
            "candidate_period": {
                "from": period_start.isoformat(),
                "to": period_end.isoformat(),
            },
        }
        detail_context["extinct_action"] = runtime._household_browser_extinct_action(
            household_name=detail_context.get("summary", {}).get("name", ""),
            head_person_fields=detail.get("head_person_fields", []),
            current_members=display_current_members,
            head_ledger_status=detail_context["head_ledger_status"],
        )

    return {
        "available": True,
        "selected_source_id": active_source_id,
        "registered_sources": context_registered_sources,
        "source": context_source,
        "latest_export": latest_export,
        "canonical_batch": canonical_batch,
        "canonical_snapshot_id": canonical_snapshot_id,
        "latest_import": runtime.latest_import_batch_summary(active_source_id),
        "query": query,
        "include_memorial_search": include_memorial_search,
        "kana_group": selected_group_key,
        "kana_groups": kana_groups,
        "selected_group_label": runtime.HOUSEHOLD_KANA_GROUP_LABELS[selected_group_key],
        "candidate_from": period_start.isoformat(),
        "candidate_to": period_end.isoformat(),
        "results": filtered_households,
        "selected_household": selected_household_id,
        "detail": detail_context,
        "result_count": len(filtered_households),
        "data_backend": dataset["data_backend"],
    }


__all__ = [
    "_legacy_build_household_browser_context",
    "_load_household_browser_context_dataset",
]
