from __future__ import annotations

from typing import Any

from django.db import OperationalError, ProgrammingError
from django.utils import timezone as timezone

from apps.imports import source_runtime

from .memo_search_assignments import _assignment_map, _entry_assignment_key
from .memo_search_catalog import (
    _note_type_options as _note_type_options,
)
from .memo_search_catalog import (
    _result_kind_options as _result_kind_options,
)
from .memo_search_catalog import (
    _summary_note_type_options,
    _summary_result_kind_options,
    _summary_tag_options,
)
from .memo_search_catalog import (
    _tag_options as _tag_options,
)
from .memo_search_catalog import (
    build_memo_tag_catalog_context as _build_memo_tag_catalog_context_impl,
)
from .memo_search_client import OpenAIResponsesClient
from .memo_search_client import OpenAIResponsesError as OpenAIResponsesError
from .memo_search_entity_entries import _entity_entries as _entity_entries
from .memo_search_note_entries import _memo_entries, _memo_entry_count
from .memo_search_query import (
    _clean_search_keywords as _clean_search_keywords,
)
from .memo_search_query import (
    _fallback_query_plan as _fallback_query_plan,
)
from .memo_search_query import (
    _merge_query_plans as _merge_query_plans,
)
from .memo_search_query import (
    _normalize_search_keyword as _normalize_search_keyword,
)
from .memo_search_query import (
    _plan_note_type_labels,
    _plan_result_labels,
    _query_plan,
    _query_prefers_memo_results,
    _requested_note_types,
    _requested_result_kinds,
    _resolve_query_date_range,
)
from .memo_search_query import (
    _query_contains_any as _query_contains_any,
)
from .memo_search_query import (
    _query_focus_keywords as _query_focus_keywords,
)
from .memo_search_query import (
    _resolve_query_event_dates as _resolve_query_event_dates,
)
from .memo_search_ranking import (
    _apply_plan_filters,
    _filter_entries_by_date_range,
    _maybe_ai_rerank_results,
    _smart_search_results,
    _text_search_results,
)
from .memo_search_ranking import (
    _entry_matches_date_range as _entry_matches_date_range,
)
from .memo_search_ranking import (
    _entry_search_text as _entry_search_text,
)
from .memo_search_ranking import (
    _load_candidate_entries as _load_candidate_entries_impl,
)
from .memo_search_ranking import (
    _result_identity as _result_identity,
)
from .memo_search_ranking import (
    _search_entries as _search_entries_impl,
)
from .memo_search_scope import (
    _resolve_search_scope,
)
from .memo_search_scope import (
    _resolve_search_source_id as _resolve_search_source_id,
)
from .memo_search_scope import (
    _scoped_households as _scoped_households,
)
from .memo_search_scope import (
    _scoped_people as _scoped_people,
)
from .memo_search_scope import (
    _scoped_service_schedules as _scoped_service_schedules,
)
from .memo_search_scope import (
    _scoped_visit_notes as _scoped_visit_notes,
)
from .memo_search_shared import (
    DEFAULT_MEMO_AI_MODELS as DEFAULT_MEMO_AI_MODELS,
)
from .memo_search_shared import (
    MAX_AI_NEW_TAGS_PER_NOTE as MAX_AI_NEW_TAGS_PER_NOTE,
)
from .memo_search_shared import (
    MAX_AI_RERANK_CANDIDATES as MAX_AI_RERANK_CANDIDATES,
)
from .memo_search_shared import (
    MAX_AI_TAGS_PER_NOTE as MAX_AI_TAGS_PER_NOTE,
)
from .memo_search_shared import (
    MAX_AUTO_TAG_AI_CALLS_PER_RUN,
    MAX_AUTO_TAG_NOTES_PER_RUN,
    MAX_RENDERED_SEARCH_RESULTS,
    RESULT_KIND_DEFINITIONS,
    SEARCH_MODE_CHOICES,
    QueryPlan,
)
from .memo_search_shared import (
    MAX_DYNAMIC_MEMO_TAGS as MAX_DYNAMIC_MEMO_TAGS,
)
from .memo_search_shared import (
    MEMO_TAG_SEEDS as MEMO_TAG_SEEDS,
)
from .memo_search_shared import (
    NOTE_TYPE_DEFINITIONS as NOTE_TYPE_DEFINITIONS,
)
from .memo_search_shared import (
    NOTE_TYPE_QUERY_ALIASES as NOTE_TYPE_QUERY_ALIASES,
)
from .memo_search_shared import (
    OPENAI_QUERY_TIMEOUT_SECONDS as OPENAI_QUERY_TIMEOUT_SECONDS,
)
from .memo_search_shared import (
    OPENAI_RERANK_TIMEOUT_SECONDS as OPENAI_RERANK_TIMEOUT_SECONDS,
)
from .memo_search_shared import (
    OPENAI_RESPONSES_URL as OPENAI_RESPONSES_URL,
)
from .memo_search_shared import (
    OPENAI_TAG_TIMEOUT_SECONDS as OPENAI_TAG_TIMEOUT_SECONDS,
)
from .memo_search_shared import (
    OPENAI_TIMEOUT_SECONDS as OPENAI_TIMEOUT_SECONDS,
)
from .memo_search_shared import (
    RESULT_KIND_QUERY_ALIASES as RESULT_KIND_QUERY_ALIASES,
)
from .memo_search_shared import (
    RULE_TAG_PATTERNS as RULE_TAG_PATTERNS,
)
from .memo_search_shared import (
    SEARCH_KEYWORD_STOPWORDS as SEARCH_KEYWORD_STOPWORDS,
)
from .memo_search_shared import (
    SEARCH_KEYWORD_SUFFIXES as SEARCH_KEYWORD_SUFFIXES,
)
from .memo_search_shared import (
    TAG_QUERY_ALIASES as TAG_QUERY_ALIASES,
)
from .memo_search_shared import (
    MemoTagWorkItem as MemoTagWorkItem,
)
from .memo_search_shared import (
    _date_to_text as _date_to_text,
)
from .memo_search_shared import (
    _dedupe_text_list as _dedupe_text_list,
)
from .memo_search_shared import (
    _excerpt as _excerpt,
)
from .memo_search_shared import (
    _note_checksum as _note_checksum,
)
from .memo_search_shared import (
    _search_text as _search_text,
)
from .memo_search_tagging import (
    _ensure_dynamic_tag as _ensure_dynamic_tag,
)
from .memo_search_tagging import (
    _normalize_tag_label as _normalize_tag_label,
)
from .memo_search_tagging import (
    _rule_labels as _rule_labels,
)
from .memo_search_tagging import (
    _unique_tag_slug as _unique_tag_slug,
)
from .memo_search_tagging import (
    ensure_seed_memo_tags as _ensure_seed_memo_tags_impl,
)
from .memo_search_tagging import (
    sync_auto_memo_tags as _sync_auto_memo_tags_impl,
)


def build_memo_search_context(
    *,
    source_id: str | None = None,
    query: str = "",
    selected_tag_slug: str = "",
    selected_note_type: str = "",
    selected_result_kind: str = "",
    search_mode: str = "smart",
    include_history: bool = False,
) -> dict[str, Any]:
    try:
        resolved_source_id, visible_batch = _resolve_search_scope(
            source_id=source_id,
            include_history=include_history,
        )
        ensure_seed_memo_tags()
        from apps.imports.models import MemoTag

        total_tag_count = MemoTag.objects.filter(is_active=True).count()
        dynamic_tag_count = MemoTag.objects.filter(origin=MemoTag.Origin.AI, is_active=True).count()
        ai_client = OpenAIResponsesClient()
        normalized_search_mode = _normalize_search_mode(search_mode, ai_available=ai_client.available)
        active_conditions = bool(
            query.strip() or selected_tag_slug or selected_note_type or selected_result_kind
        )
        if not active_conditions:
            memo_entry_count = _memo_entry_count(
                source_id=resolved_source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            )
            result_kind_options = _summary_result_kind_options(
                memo_entry_count,
                source_id=resolved_source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            )
            note_type_options = _summary_note_type_options(
                source_id=resolved_source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            )
            tag_options = _summary_tag_options()
            total_entry_count = sum(option["count"] for option in result_kind_options)
            return {
                "available": True,
                "message": "",
                "query": query,
                "results": [],
                "result_count": 0,
                "rendered_result_count": 0,
                "truncated_result_count": 0,
                "needs_search": True,
                "memo_entry_count": memo_entry_count,
                "total_tag_count": total_tag_count,
                "dynamic_tag_count": dynamic_tag_count,
                "tag_options": [
                    {**option, "selected": option["slug"] == selected_tag_slug} for option in tag_options
                ],
                "selected_tag_slug": selected_tag_slug,
                "note_type_options": [
                    {**option, "selected": option["key"] == selected_note_type} for option in note_type_options
                ],
                "selected_note_type": selected_note_type,
                "result_kind_options": [
                    {**option, "selected": option["key"] == selected_result_kind}
                    for option in result_kind_options
                ],
                "selected_result_kind": selected_result_kind,
                "search_modes": [
                    {**mode, "selected": mode["key"] == normalized_search_mode} for mode in SEARCH_MODE_CHOICES
                ],
                "selected_search_mode": normalized_search_mode,
                "include_history": include_history,
                "visible_batch_snapshot_id": visible_batch.prepared_snapshot_id if visible_batch else "",
                "ai_available": ai_client.available,
                "ai_plan": None,
                "ai_plan_result_labels": [],
                "ai_plan_note_type_labels": [],
                "total_entry_count": total_entry_count,
                "selected_source_id": resolved_source_id,
            }

        plan = None
        if query.strip() and normalized_search_mode == "smart":
            plan = _query_plan(
                query=query,
                ai_client=ai_client,
                entries=[],
                tag_options=_summary_tag_options(),
            )
        memo_only_query = bool(
            query.strip() and not selected_result_kind and _query_prefers_memo_results(query)
        )
        if memo_only_query and plan is not None:
            plan = QueryPlan(
                intent_summary=plan.intent_summary,
                result_kinds=["memo"],
                selected_labels=plan.selected_labels,
                selected_note_types=plan.selected_note_types,
                keywords=plan.keywords,
                date_from=plan.date_from,
                date_to=plan.date_to,
                used_ai=plan.used_ai,
                model=plan.model,
            )
        if normalized_search_mode == "smart":
            date_from = plan.date_from if plan is not None else ""
            date_to = plan.date_to if plan is not None else ""
        else:
            date_from, date_to = _resolve_query_date_range(query)

        load_result_kinds = _requested_result_kinds(
            selected_result_kind=selected_result_kind,
            selected_note_type=selected_note_type,
            plan=plan,
        )
        if memo_only_query:
            load_result_kinds = {"memo"}
        load_note_types = _requested_note_types(
            selected_note_type=selected_note_type,
            plan=plan,
        )
        entries, memo_entries = _load_candidate_entries(
            source_id=resolved_source_id,
            visible_batch=visible_batch,
            include_history=include_history,
            result_kinds=load_result_kinds,
            note_types=load_note_types,
            date_from=date_from,
            date_to=date_to,
        )
        tag_options = _summary_tag_options()
        note_type_options = _summary_note_type_options(
            source_id=resolved_source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        )
        result_kind_options = _summary_result_kind_options(
            _memo_entry_count(
                source_id=resolved_source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ),
            source_id=resolved_source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        )
        results = list(entries)
        if selected_tag_slug:
            results = [entry for entry in results if selected_tag_slug in {tag["slug"] for tag in entry["tags"]}]
        if selected_note_type:
            results = [entry for entry in results if entry["note_type"] == selected_note_type]
        if selected_result_kind:
            results = [entry for entry in results if entry["result_kind"] == selected_result_kind]
        if query.strip():
            if normalized_search_mode == "smart":
                results = _apply_plan_filters(results, plan=plan)
                results = _smart_search_results(results, query=query, plan=plan)
                if not results and not selected_result_kind and not memo_only_query:
                    entries, memo_entries = _load_candidate_entries(
                        source_id=resolved_source_id,
                        visible_batch=visible_batch,
                        include_history=include_history,
                        result_kinds=set(RESULT_KIND_DEFINITIONS.keys()),
                        note_types=None,
                        date_from=date_from,
                        date_to=date_to,
                    )
                    results = list(entries)
                    if selected_tag_slug:
                        results = [
                            entry for entry in results if selected_tag_slug in {tag["slug"] for tag in entry["tags"]}
                        ]
                    if selected_note_type:
                        results = [entry for entry in results if entry["note_type"] == selected_note_type]
                    results = _filter_entries_by_date_range(results, date_from=date_from, date_to=date_to)
                    results = _smart_search_results(results, query=query, plan=plan)
                results = _maybe_ai_rerank_results(results, query=query, ai_client=ai_client)
            else:
                results = _filter_entries_by_date_range(results, date_from=date_from, date_to=date_to)
                results = _text_search_results(results, query=query)
        else:
            results.sort(key=lambda item: item["sort_key"], reverse=True)
        total_result_count = len(results)
        results = results[:MAX_RENDERED_SEARCH_RESULTS]
        return {
            "available": True,
            "message": "",
            "query": query,
            "results": results,
            "result_count": total_result_count,
            "rendered_result_count": len(results),
            "truncated_result_count": max(total_result_count - len(results), 0),
            "needs_search": False,
            "memo_entry_count": len(memo_entries),
            "total_tag_count": total_tag_count,
            "dynamic_tag_count": dynamic_tag_count,
            "tag_options": [
                {**option, "selected": option["slug"] == selected_tag_slug} for option in tag_options
            ],
            "selected_tag_slug": selected_tag_slug,
            "note_type_options": [
                {**option, "selected": option["key"] == selected_note_type} for option in note_type_options
            ],
            "selected_note_type": selected_note_type,
            "result_kind_options": [
                {**option, "selected": option["key"] == selected_result_kind}
                for option in result_kind_options
            ],
            "selected_result_kind": selected_result_kind,
            "search_modes": [
                {**mode, "selected": mode["key"] == normalized_search_mode} for mode in SEARCH_MODE_CHOICES
            ],
            "selected_search_mode": normalized_search_mode,
            "include_history": include_history,
            "visible_batch_snapshot_id": visible_batch.prepared_snapshot_id if visible_batch else "",
            "ai_available": ai_client.available,
            "ai_plan": plan,
            "ai_plan_result_labels": _plan_result_labels(plan),
            "ai_plan_note_type_labels": _plan_note_type_labels(plan),
            "total_entry_count": len(entries),
            "selected_source_id": resolved_source_id,
        }
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "message": "メモタグ関連のテーブルがまだありません。migrate 後に使えます。",
            "query": query,
            "results": [],
            "result_count": 0,
            "rendered_result_count": 0,
            "truncated_result_count": 0,
            "needs_search": True,
            "memo_entry_count": 0,
            "total_tag_count": 0,
            "dynamic_tag_count": 0,
            "tag_options": [],
            "selected_tag_slug": selected_tag_slug,
            "note_type_options": [],
            "selected_note_type": selected_note_type,
            "result_kind_options": [],
            "selected_result_kind": selected_result_kind,
            "search_modes": [
                {**mode, "selected": mode["key"] == "text"} for mode in SEARCH_MODE_CHOICES
            ],
            "selected_search_mode": "text",
            "include_history": include_history,
            "visible_batch_snapshot_id": "",
            "ai_available": False,
            "ai_plan": None,
            "ai_plan_result_labels": [],
            "ai_plan_note_type_labels": [],
            "total_entry_count": 0,
            "selected_source_id": source_id or source_runtime.operational_source_id(),
        }


build_universal_search_context = build_memo_search_context


def build_memo_tag_catalog_context(*, source_id: str | None = None, query: str = "") -> dict[str, Any]:
    return _build_memo_tag_catalog_context_impl(
        source_id=source_id,
        query=query,
        ensure_seed_memo_tags=ensure_seed_memo_tags,
    )


def sync_auto_memo_tags(
    *,
    source_id: str | None = None,
    include_history: bool = False,
    limit: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return _sync_auto_memo_tags_impl(
        source_id=source_id,
        include_history=include_history,
        limit=limit,
        force=force,
        ensure_seed_tags=ensure_seed_memo_tags,
        ai_client_factory=OpenAIResponsesClient,
        memo_entries_loader=_memo_entries,
        assignment_map_loader=_assignment_map,
        entry_assignment_key=_entry_assignment_key,
        max_auto_tag_notes_per_run=MAX_AUTO_TAG_NOTES_PER_RUN,
        max_auto_tag_ai_calls_per_run=MAX_AUTO_TAG_AI_CALLS_PER_RUN,
    )


def ensure_seed_memo_tags() -> None:
    _ensure_seed_memo_tags_impl()


def _load_candidate_entries(
    *,
    source_id: str,
    visible_batch: Any,
    include_history: bool,
    result_kinds: set[str],
    note_types: set[str] | None,
    date_from: str,
    date_to: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _load_candidate_entries_impl(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
        result_kinds=result_kinds,
        note_types=note_types,
        date_from=date_from,
        date_to=date_to,
        memo_entries_loader=_memo_entries,
    )


def _search_entries(
    *,
    source_id: str,
    visible_batch: Any,
    include_history: bool,
    memo_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _search_entries_impl(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
        memo_entries=memo_entries,
    )


def _normalize_search_mode(search_mode: str, *, ai_available: bool) -> str:
    valid_modes = {mode["key"] for mode in SEARCH_MODE_CHOICES}
    if search_mode in valid_modes:
        if search_mode == "smart" and not ai_available:
            return "text"
        return search_mode
    return "smart" if ai_available else "text"
