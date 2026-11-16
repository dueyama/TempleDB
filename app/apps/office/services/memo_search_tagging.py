from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from apps.imports.models import MemoTag, MemoTagAssignment

from .memo_search_assignments import _assignment_map, _entry_assignment_key
from .memo_search_note_entries import _memo_entries
from .memo_search_scope import _resolve_search_scope
from .memo_search_shared import (
    MAX_AUTO_TAG_AI_CALLS_PER_RUN,
    MAX_AUTO_TAG_NOTES_PER_RUN,
    MAX_DYNAMIC_MEMO_TAGS,
    MEMO_TAG_SEEDS,
    RULE_TAG_PATTERNS,
    MemoTagWorkItem,
    _dedupe_text_list,
    _excerpt,
    _note_checksum,
)


def sync_auto_memo_tags(
    *,
    source_id: str | None = None,
    include_history: bool = False,
    limit: int | None = None,
    force: bool = False,
    ensure_seed_tags: Callable[[], None],
    ai_client_factory: Callable[[], Any],
    memo_entries_loader: Callable[..., list[dict[str, Any]]] = _memo_entries,
    assignment_map_loader: Callable[[], dict[tuple[int, int, str], list[MemoTagAssignment]]] = _assignment_map,
    entry_assignment_key: Callable[[dict[str, Any]], tuple[int, int, str]] = _entry_assignment_key,
    max_auto_tag_notes_per_run: int = MAX_AUTO_TAG_NOTES_PER_RUN,
    max_auto_tag_ai_calls_per_run: int = MAX_AUTO_TAG_AI_CALLS_PER_RUN,
) -> dict[str, Any]:
    ensure_seed_tags()
    ai_client = ai_client_factory()
    resolved_source_id, visible_batch = _resolve_search_scope(
        source_id=source_id,
        include_history=include_history,
    )
    entries = memo_entries_loader(
        source_id=resolved_source_id,
        visible_batch=visible_batch,
        include_history=include_history,
        include_assignments=False,
    )
    assignment_map = assignment_map_loader()
    ai_calls_remaining = max_auto_tag_ai_calls_per_run
    active_tag_map = {
        tag.label: tag for tag in MemoTag.objects.filter(is_active=True).order_by("label", "id")
    }
    seed_labels = list(active_tag_map.keys())
    dynamic_remaining = max(
        MAX_DYNAMIC_MEMO_TAGS - MemoTag.objects.filter(origin=MemoTag.Origin.AI, is_active=True).count(),
        0,
    )
    process_limit = limit if limit is not None else max_auto_tag_notes_per_run
    stats = {
        "total_count": len(entries),
        "queued_count": 0,
        "processed_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "remaining_count": 0,
        "created_tag_count": 0,
        "assigned_tag_count": 0,
        "ai_used": False,
        "ai_available": ai_client.available,
        "ai_processed_count": 0,
        "ai_deferred_count": 0,
    }
    work_items: list[MemoTagWorkItem] = []
    for entry in entries:
        existing_assignments = assignment_map.get(entry_assignment_key(entry), [])
        checksum = _note_checksum(entry["text"])
        existing_checksum = existing_assignments[0].note_checksum if existing_assignments else ""
        if existing_assignments and existing_checksum == checksum and not force:
            stats["skipped_count"] += 1
            continue
        work_items.append(
            MemoTagWorkItem(
                entry=entry,
                checksum=checksum,
                existing_assignments=existing_assignments,
                rule_labels=_rule_labels(entry["text"]),
            )
        )
    work_items.sort(key=lambda item: 0 if not item.existing_assignments else 1)
    stats["queued_count"] = len(work_items)
    remaining_items = work_items[process_limit:] if process_limit >= 0 else []
    stats["remaining_count"] = len(remaining_items)
    stats["ai_deferred_count"] = sum(
        1
        for item in remaining_items
        if ai_client.available and (force or not item.rule_labels)
    )
    for item in work_items[:process_limit]:
        entry = item.entry
        selected_by_source = {
            label: MemoTagAssignment.SourceKind.RULE for label in item.rule_labels
        }
        should_use_ai = bool(
            ai_client.available and (force or not item.rule_labels) and ai_calls_remaining > 0
        )
        if ai_client.available and not should_use_ai and not item.rule_labels:
            stats["ai_deferred_count"] += 1
        used_ai_for_entry = False
        if should_use_ai:
            from .memo_search_client import OpenAIResponsesError

            stats["ai_used"] = True
            ai_calls_remaining -= 1
            stats["ai_processed_count"] += 1
            try:
                ai_payload = ai_client.suggest_tags(
                    note_type_label=entry["note_label"],
                    note_text=entry["text"],
                    existing_labels=seed_labels,
                    rule_labels=item.rule_labels,
                )
            except OpenAIResponsesError:
                ai_payload = None
            if ai_payload is not None:
                for label in _dedupe_text_list(ai_payload.get("selected_labels") or []):
                    normalized = _normalize_tag_label(label)
                    if not normalized:
                        continue
                    selected_by_source[normalized] = MemoTagAssignment.SourceKind.AI
                    used_ai_for_entry = True
                for label in _dedupe_text_list(ai_payload.get("proposed_new_labels") or []):
                    normalized = _normalize_tag_label(label)
                    if not normalized:
                        continue
                    tag, created = _ensure_dynamic_tag(normalized, remaining=dynamic_remaining)
                    if tag is None:
                        continue
                    if created:
                        dynamic_remaining = max(dynamic_remaining - 1, 0)
                        stats["created_tag_count"] += 1
                        seed_labels.append(tag.label)
                        active_tag_map[tag.label] = tag
                    selected_by_source[tag.label] = MemoTagAssignment.SourceKind.AI
                    used_ai_for_entry = True
        selected_labels = list(selected_by_source.keys())
        confidence = 0.8 if used_ai_for_entry else None
        with transaction.atomic():
            MemoTagAssignment.objects.filter(
                content_type_id=entry["content_type_id"],
                object_id=entry["object_id"],
                field_name=entry["field_name"],
            ).delete()
            assignments = []
            for label in selected_labels:
                tag = active_tag_map.get(label)
                if tag is None:
                    continue
                assignments.append(
                    MemoTagAssignment(
                        tag=tag,
                        content_type_id=entry["content_type_id"],
                        object_id=entry["object_id"],
                        field_name=entry["field_name"],
                        note_type=entry["note_type"],
                        note_label=entry["note_label"],
                        legacy_source_id=entry["legacy_source_id"],
                        legacy_household_id=entry["legacy_household_id"],
                        legacy_person_id=entry["legacy_person_id"],
                        legacy_schedule_id=entry["legacy_schedule_id"],
                        source_kind=selected_by_source[label],
                        confidence=confidence,
                        note_checksum=item.checksum,
                        note_excerpt=_excerpt(entry["text"]),
                    )
                )
            MemoTagAssignment.objects.bulk_create(assignments)
        stats["processed_count"] += 1
        stats["updated_count"] += 1
        stats["assigned_tag_count"] += len(selected_labels)
    return stats


def ensure_seed_memo_tags() -> None:
    for seed in MEMO_TAG_SEEDS:
        label = seed["label"]
        MemoTag.objects.get_or_create(
            label=label,
            defaults={
                "slug": _unique_tag_slug(label),
                "description": seed["description"],
                "origin": MemoTag.Origin.SEED,
                "is_active": True,
            },
        )


def _rule_labels(text: str) -> list[str]:
    normalized_text = (text or "").strip()
    labels = []
    for label, patterns in RULE_TAG_PATTERNS.items():
        if any(re.search(pattern, normalized_text, flags=re.IGNORECASE) for pattern in patterns):
            labels.append(label)
    return _dedupe_text_list(labels)


def _ensure_dynamic_tag(label: str, *, remaining: int) -> tuple[MemoTag | None, bool]:
    existing = MemoTag.objects.filter(label=label).order_by("id").first()
    if existing is not None:
        return existing, False
    if remaining <= 0:
        return None, False
    return (
        MemoTag.objects.create(
            label=label,
            slug=_unique_tag_slug(label),
            description="AIが提案したメモタグ",
            origin=MemoTag.Origin.AI,
            is_active=True,
        ),
        True,
    )


def _unique_tag_slug(label: str) -> str:
    base_slug = slugify(label, allow_unicode=True) or hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
    slug = base_slug
    index = 2
    while MemoTag.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def _normalize_tag_label(value: str) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "").strip())
    cleaned = cleaned.replace("　", "")
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 16:
        return ""
    if re.search(r"[0-9,./:_-]", cleaned):
        return ""
    if re.search(r"[「」『』（）()\\[\\]{}]", cleaned):
        return ""
    return cleaned
