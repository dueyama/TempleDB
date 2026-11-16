from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Max
from django.utils import timezone

from apps.imports.models import (
    DistrictMemberSheetState,
    HandDeliveryReviewResolution,
    ImportBatch,
    MemoTag,
    PostalReviewResolution,
)

from .memo_search_scope import (
    _resolve_search_scope,
    _scoped_households,
    _scoped_people,
    _scoped_service_schedules,
    _scoped_visit_notes,
)
from .memo_search_shared import NOTE_TYPE_DEFINITIONS, RESULT_KIND_DEFINITIONS, _search_text


def build_memo_tag_catalog_context(
    *,
    source_id: str | None = None,
    query: str = "",
    ensure_seed_memo_tags: Callable[[], None],
) -> dict[str, Any]:
    resolved_source_id, _visible_batch = _resolve_search_scope(source_id=source_id, include_history=False)
    try:
        ensure_seed_memo_tags()
        queryset = MemoTag.objects.filter(is_active=True).annotate(
            assignment_count=Count("assignments", distinct=True),
            latest_assignment_at=Max("assignments__updated_at"),
        )
        if query.strip():
            normalized_query = _search_text(query)
            queryset = [
                tag
                for tag in queryset
                if normalized_query in _search_text(" ".join([tag.label, tag.description, tag.get_origin_display()]))
            ]
        else:
            queryset = list(queryset)
        tags = sorted(queryset, key=lambda tag: (-tag.assignment_count, tag.label))
        return {
            "available": True,
            "message": "",
            "query": query,
            "tags": [
                {
                    "slug": tag.slug,
                    "label": tag.label,
                    "description": tag.description,
                    "origin": tag.origin,
                    "origin_label": tag.get_origin_display(),
                    "assignment_count": tag.assignment_count,
                    "latest_assignment_label": (
                        timezone.localtime(tag.latest_assignment_at).strftime("%Y-%m-%d %H:%M")
                        if tag.latest_assignment_at
                        else ""
                    ),
                }
                for tag in tags
            ],
            "tag_count": len(tags),
            "seed_tag_count": MemoTag.objects.filter(origin=MemoTag.Origin.SEED, is_active=True).count(),
            "dynamic_tag_count": MemoTag.objects.filter(origin=MemoTag.Origin.AI, is_active=True).count(),
            "selected_source_id": resolved_source_id,
        }
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "message": "メモタグ関連のテーブルがまだありません。migrate 後に使えます。",
            "query": query,
            "tags": [],
            "tag_count": 0,
            "seed_tag_count": 0,
            "dynamic_tag_count": 0,
            "selected_source_id": resolved_source_id,
        }


def _tag_options(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for tag in entry["tags"]:
            current = counts.setdefault(
                tag["slug"],
                {
                    "slug": tag["slug"],
                    "label": tag["label"],
                    "count": 0,
                },
            )
            current["count"] += 1
    return sorted(counts.values(), key=lambda item: (-item["count"], item["label"]))


def _note_type_options(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = defaultdict(int)
    for entry in entries:
        counts[entry["note_type"]] += 1
    options = []
    for key, definition in NOTE_TYPE_DEFINITIONS.items():
        options.append(
            {
                "key": key,
                "label": definition["label"],
                "count": counts.get(key, 0),
            }
        )
    return options


def _result_kind_options(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = defaultdict(int)
    for entry in entries:
        counts[entry["result_kind"]] += 1
    return [
        {
            "key": key,
            "label": definition["label"],
            "count": counts.get(key, 0),
        }
        for key, definition in RESULT_KIND_DEFINITIONS.items()
    ]


def _summary_result_kind_options(
    memo_entry_count: int,
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
) -> list[dict[str, Any]]:
    counts = {
        "household": _scoped_households(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).count(),
        "person": _scoped_people(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).count(),
        "schedule": _scoped_service_schedules(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).count(),
        "memo": memo_entry_count,
    }
    return [
        {
            "key": key,
            "label": definition["label"],
            "count": counts.get(key, 0),
        }
        for key, definition in RESULT_KIND_DEFINITIONS.items()
    ]


def _summary_note_type_options(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
) -> list[dict[str, Any]]:
    counts = {
        "household_note": _scoped_households(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(notes__exact="").count(),
        "person_note": _scoped_people(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(person_note__exact="").count(),
        "deceased_note": _scoped_people(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(deceased_note__exact="").count(),
        "service_schedule_note": _scoped_service_schedules(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(notes__exact="").count(),
        "visit_note_body": _scoped_visit_notes(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(body__exact="").count(),
        "visit_note_next_action": _scoped_visit_notes(
            source_id=source_id,
            visible_batch=visible_batch,
            include_history=include_history,
        ).exclude(next_action__exact="").count(),
        "postal_review_note": PostalReviewResolution.objects.filter(source__source_id=source_id)
        .exclude(note__exact="")
        .count(),
        "hand_delivery_review_note": HandDeliveryReviewResolution.objects.filter(source__source_id=source_id)
        .exclude(note__exact="")
        .count(),
        "district_member_sheet_note": DistrictMemberSheetState.objects.filter(source__source_id=source_id)
        .exclude(manual_note__exact="")
        .count(),
    }
    return [
        {
            "key": key,
            "label": definition["label"],
            "count": counts.get(key, 0),
        }
        for key, definition in NOTE_TYPE_DEFINITIONS.items()
    ]


def _summary_tag_options(limit: int = 50) -> list[dict[str, Any]]:
    tags = (
        MemoTag.objects.filter(is_active=True)
        .annotate(count=Count("assignments", distinct=True))
        .order_by("-count", "label")[:limit]
    )
    return [
        {
            "slug": tag.slug,
            "label": tag.label,
            "count": tag.count,
        }
        for tag in tags
    ]
