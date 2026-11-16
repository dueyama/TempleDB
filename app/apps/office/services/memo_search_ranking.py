from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .memo_search_entity_entries import _entity_entries
from .memo_search_note_entries import _memo_entries
from .memo_search_query import _query_focus_keywords
from .memo_search_shared import (
    MAX_AI_RERANK_CANDIDATES,
    QueryPlan,
    _search_text,
)


def _search_entries(
    *,
    source_id: str,
    visible_batch: Any,
    include_history: bool,
    memo_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries = _entity_entries(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
    )
    entries.extend(memo_entries)
    entries.sort(key=lambda item: item["sort_key"], reverse=True)
    return entries


def _load_candidate_entries(
    *,
    source_id: str,
    visible_batch: Any,
    include_history: bool,
    result_kinds: set[str],
    note_types: set[str] | None,
    date_from: str,
    date_to: str,
    memo_entries_loader: Callable[..., list[dict[str, Any]]] = _memo_entries,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    memo_entries = (
        memo_entries_loader(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
            note_types=note_types,
            date_from=date_from,
            date_to=date_to,
        )
        if "memo" in result_kinds
        else []
    )
    entries = list(
        _entity_entries(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
            result_kinds=result_kinds,
            date_from=date_from,
            date_to=date_to,
        )
    )
    entries.extend(memo_entries)
    entries.sort(key=lambda item: item["sort_key"], reverse=True)
    return entries, memo_entries


def _smart_search_results(
    entries: list[dict[str, Any]],
    *,
    query: str,
    plan: QueryPlan,
) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    raw_query = _search_text(query)
    focus_keywords = [_search_text(keyword) for keyword in _query_focus_keywords(query)]
    for entry in entries:
        entry_tag_labels = {tag["label"] for tag in entry["tags"]}
        entry_search_text = _entry_search_text(entry)
        focus_hits = sum(1 for keyword in focus_keywords if keyword in entry_search_text)
        if focus_keywords and focus_hits == 0:
            continue
        tag_overlap = entry_tag_labels.intersection(plan.selected_labels)
        label_hits = sum(1 for label in plan.selected_labels if _search_text(label) in entry_search_text)
        keyword_hits = 0
        for keyword in plan.keywords:
            if _search_text(keyword) in entry_search_text:
                keyword_hits += 1
        raw_query_hit = bool(raw_query and raw_query in entry_search_text)
        date_hit = bool(
            (plan.date_from or plan.date_to)
            and _entry_matches_date_range(entry, date_from=plan.date_from, date_to=plan.date_to)
        )
        evidence_score = 0
        evidence_score += focus_hits * 7
        evidence_score += len(tag_overlap) * 8
        evidence_score += label_hits * 5
        evidence_score += keyword_hits * 3
        if raw_query_hit:
            evidence_score += 4
        if date_hit:
            evidence_score += 4
        if evidence_score <= 0:
            continue
        score = evidence_score
        if entry["result_kind"] in plan.result_kinds:
            score += 1
        if entry["note_type"] in plan.selected_note_types:
            score += 4
        if score > 0:
            entry["search_score"] = score
            scored.append((score, entry))
    scored.sort(key=lambda item: (item[0], item[1]["sort_key"]), reverse=True)
    return [entry for _, entry in scored]


def _text_search_results(entries: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    needle = _search_text(query)
    keywords = [_search_text(value) for value in _query_focus_keywords(query)]
    keywords = [keyword for keyword in keywords if keyword]
    if not needle and not keywords:
        return entries
    results = []
    for entry in entries:
        entry_text = _entry_search_text(entry)
        if keywords:
            if all(keyword in entry_text for keyword in keywords):
                results.append(entry)
            continue
        if needle in entry_text:
            results.append(entry)
    results.sort(key=lambda item: item["sort_key"], reverse=True)
    return results


def _apply_plan_filters(entries: list[dict[str, Any]], *, plan: QueryPlan) -> list[dict[str, Any]]:
    filtered = list(entries)
    if plan.result_kinds:
        filtered = [entry for entry in filtered if entry["result_kind"] in plan.result_kinds]
    filtered = _filter_entries_by_date_range(filtered, date_from=plan.date_from, date_to=plan.date_to)
    return filtered


def _filter_entries_by_date_range(
    entries: list[dict[str, Any]],
    *,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    normalized_from = date_from.strip()
    normalized_to = date_to.strip()
    if not normalized_from and not normalized_to:
        return entries
    return [
        entry
        for entry in entries
        if _entry_matches_date_range(entry, date_from=normalized_from, date_to=normalized_to)
    ]


def _entry_matches_date_range(entry: dict[str, Any], *, date_from: str, date_to: str) -> bool:
    event_date = str(entry.get("event_date") or "").strip()
    if not event_date:
        return False
    if date_from and event_date < date_from:
        return False
    if date_to and event_date > date_to:
        return False
    return True


def _maybe_ai_rerank_results(
    results: list[dict[str, Any]],
    *,
    query: str,
    ai_client: Any,
) -> list[dict[str, Any]]:
    from .memo_search_client import OpenAIResponsesError

    if not results or len(results) <= 1 or not ai_client.available:
        return results
    if not hasattr(ai_client, "rerank_search_results"):
        return results
    candidate_entries = results[:MAX_AI_RERANK_CANDIDATES]
    keyed_candidates = {
        f"c{index}": entry for index, entry in enumerate(candidate_entries, start=1)
    }
    try:
        ordered_keys = ai_client.rerank_search_results(query=query, entries=candidate_entries)
    except OpenAIResponsesError:
        return results
    reranked = [keyed_candidates[key] for key in ordered_keys if key in keyed_candidates]
    if not reranked:
        return results
    reranked_ids = {_result_identity(entry) for entry in reranked}
    remaining = [entry for entry in results if _result_identity(entry) not in reranked_ids]
    return reranked + remaining


def _result_identity(entry: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(entry.get("result_kind") or ""),
        str(entry.get("household_id") or ""),
        str(entry.get("person_id") or ""),
        str(entry.get("schedule_id") or ""),
        str(entry.get("note_type") or ""),
        str(entry.get("batch_snapshot_id") or ""),
    )


def _entry_search_text(entry: dict[str, Any]) -> str:
    return _search_text(
        " ".join(
            [
                entry.get("kind_label", ""),
                entry["title"],
                entry["note_label"],
                entry["text"],
                entry["household_id"],
                entry["household_name"],
                entry["person_id"],
                entry["person_name"],
                entry["schedule_id"],
                entry.get("event_date", ""),
                " ".join(tag["label"] for tag in entry["tags"]),
            ]
        )
    )
