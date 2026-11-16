from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

from .memo_search_shared import (
    NOTE_TYPE_DEFINITIONS,
    NOTE_TYPE_QUERY_ALIASES,
    RESULT_KIND_DEFINITIONS,
    RESULT_KIND_QUERY_ALIASES,
    SEARCH_KEYWORD_STOPWORDS,
    SEARCH_KEYWORD_SUFFIXES,
    TAG_QUERY_ALIASES,
    QueryPlan,
    _dedupe_text_list,
    _search_text,
)


def _query_plan(
    *,
    query: str,
    ai_client: Any,
    entries: list[dict[str, Any]],
    tag_options: list[dict[str, Any]],
) -> QueryPlan:
    from .memo_search_client import OpenAIResponsesError

    del entries
    fallback_plan = _fallback_query_plan(query=query, tag_options=tag_options)
    if ai_client.available:
        try:
            ai_plan = ai_client.plan_query(
                query=query,
                tag_labels=[option["label"] for option in tag_options],
                note_types=[
                    {"key": key, "label": definition["label"]} for key, definition in NOTE_TYPE_DEFINITIONS.items()
                ],
                result_kinds=[
                    {"key": key, "label": definition["label"]}
                    for key, definition in RESULT_KIND_DEFINITIONS.items()
                ],
            )
            return _merge_query_plans(fallback_plan=fallback_plan, ai_plan=ai_plan)
        except OpenAIResponsesError:
            pass
    return fallback_plan


def _fallback_query_plan(*, query: str, tag_options: list[dict[str, Any]]) -> QueryPlan:
    date_from, date_to = _resolve_query_date_range(query)
    normalized_query = _search_text(query)
    selected_labels = [
        option["label"]
        for option in tag_options
        if _query_contains_any(normalized_query, [option["label"], *TAG_QUERY_ALIASES.get(option["label"], [])])
    ]
    selected_note_types = [
        key
        for key, definition in NOTE_TYPE_DEFINITIONS.items()
        if _query_contains_any(
            normalized_query,
            [definition["label"], *NOTE_TYPE_QUERY_ALIASES.get(key, [])],
        )
    ]
    result_kinds = [
        key
        for key, definition in RESULT_KIND_DEFINITIONS.items()
        if _query_contains_any(
            normalized_query,
            [definition["label"], *RESULT_KIND_QUERY_ALIASES.get(key, [])],
        )
    ]
    fallback_keywords = _clean_search_keywords([query, *re.split(r"\s+", query.strip())])[:6]
    return QueryPlan(
        intent_summary="",
        result_kinds=_dedupe_text_list(result_kinds),
        selected_labels=_dedupe_text_list(selected_labels),
        selected_note_types=_dedupe_text_list(selected_note_types),
        keywords=fallback_keywords,
        date_from=date_from,
        date_to=date_to,
        used_ai=False,
        model="",
    )


def _merge_query_plans(*, fallback_plan: QueryPlan, ai_plan: QueryPlan) -> QueryPlan:
    return QueryPlan(
        intent_summary=ai_plan.intent_summary or fallback_plan.intent_summary,
        result_kinds=_dedupe_text_list(ai_plan.result_kinds + fallback_plan.result_kinds),
        selected_labels=_dedupe_text_list(ai_plan.selected_labels + fallback_plan.selected_labels),
        selected_note_types=_dedupe_text_list(ai_plan.selected_note_types + fallback_plan.selected_note_types),
        keywords=_clean_search_keywords(ai_plan.keywords + fallback_plan.keywords),
        date_from=ai_plan.date_from or fallback_plan.date_from,
        date_to=ai_plan.date_to or fallback_plan.date_to,
        used_ai=ai_plan.used_ai,
        model=ai_plan.model,
    )


def _clean_search_keywords(values: list[str]) -> list[str]:
    cleaned_values: list[str] = []
    for value in _dedupe_text_list(values):
        cleaned_value = _normalize_search_keyword(value)
        normalized = _search_text(cleaned_value)
        if not normalized:
            continue
        if normalized in SEARCH_KEYWORD_STOPWORDS:
            continue
        if len(normalized) <= 1:
            continue
        cleaned_values.append(cleaned_value)
    return cleaned_values


def _query_focus_keywords(query: str) -> list[str]:
    fragments = re.split(r"\s+|[、,，/]+|について|に関する|の|を|が|は|と|へ|で", query.strip())
    cleaned_fragments = _clean_search_keywords(fragments)
    if cleaned_fragments:
        return cleaned_fragments
    return _clean_search_keywords([query])


def _normalize_search_keyword(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"^(一昨日|昨日|今日|明日|明後日)の", "", cleaned)
    for suffix in SEARCH_KEYWORD_SUFFIXES:
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    return cleaned


def _query_contains_any(normalized_query: str, candidates: list[str]) -> bool:
    for candidate in candidates:
        normalized_candidate = _search_text(candidate)
        if normalized_candidate and normalized_candidate in normalized_query:
            return True
    return False


def _query_prefers_memo_results(query: str) -> bool:
    normalized_query = _search_text(query)
    if not _query_contains_any(
        normalized_query,
        [RESULT_KIND_DEFINITIONS["memo"]["label"], *RESULT_KIND_QUERY_ALIASES.get("memo", [])],
    ):
        return False
    explicit_non_memo = any(
        _query_contains_any(
            normalized_query,
            [RESULT_KIND_DEFINITIONS[key]["label"], *RESULT_KIND_QUERY_ALIASES.get(key, [])],
        )
        for key in ("household", "person", "schedule")
    )
    return not explicit_non_memo


def _requested_result_kinds(
    *,
    selected_result_kind: str,
    selected_note_type: str,
    plan: QueryPlan | None,
) -> set[str]:
    if selected_result_kind:
        result_kinds = {selected_result_kind}
    elif plan is not None and plan.result_kinds:
        result_kinds = set(plan.result_kinds)
    else:
        result_kinds = set(RESULT_KIND_DEFINITIONS.keys())
    if selected_note_type or (plan is not None and plan.selected_note_types):
        result_kinds.add("memo")
    return result_kinds


def _requested_note_types(*, selected_note_type: str, plan: QueryPlan | None) -> set[str] | None:
    if selected_note_type:
        return {selected_note_type}
    del plan
    return None


def _plan_result_labels(plan: QueryPlan | None) -> list[str]:
    if plan is None:
        return []
    return [RESULT_KIND_DEFINITIONS.get(key, {}).get("label", key) for key in plan.result_kinds]


def _plan_note_type_labels(plan: QueryPlan | None) -> list[str]:
    if plan is None:
        return []
    return [NOTE_TYPE_DEFINITIONS.get(key, {}).get("label", key) for key in plan.selected_note_types]


def _resolve_query_date_range(query: str) -> tuple[str, str]:
    resolved_dates = sorted(_resolve_query_event_dates(query))
    if not resolved_dates:
        return "", ""
    return resolved_dates[0], resolved_dates[-1]


def _resolve_query_event_dates(query: str) -> set[str]:
    text = str(query or "").strip()
    if not text:
        return set()
    today = timezone.localdate()
    candidates: set[date] = set()
    relative_patterns = [
        (["一昨日", "おととい"], today - timedelta(days=2)),
        (["昨日", "きのう"], today - timedelta(days=1)),
        (["今日", "本日", "きょう"], today),
        (["明日", "あした", "あす"], today + timedelta(days=1)),
        (["明後日", "あさって"], today + timedelta(days=2)),
    ]
    for labels, resolved in relative_patterns:
        if any(label in text for label in labels):
            candidates.add(resolved)
    for match in re.finditer(r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})", text):
        try:
            candidates.add(
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    for match in re.finditer(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", text):
        try:
            candidates.add(date(today.year, int(match.group("month")), int(match.group("day"))))
        except ValueError:
            continue
    return {value.isoformat() for value in candidates}
