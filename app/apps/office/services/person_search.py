from __future__ import annotations

import re
from typing import Final

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce, Replace

from apps.imports import canonical_population
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_LABELS,
    FAMILY_CATEGORY_MEMORIAL,
    Person,
)
from apps.imports.source_runtime import operational_source_id

from .household_editing_core import _household_display_head_name

PERSON_SEARCH_LEDGER_ALL: Final[str] = "all"
PERSON_SEARCH_LEDGER_CURRENT: Final[str] = "current"
PERSON_SEARCH_LEDGER_MEMORIAL: Final[str] = "memorial"
PERSON_SEARCH_RENDER_LIMIT: Final[int] = 100

PERSON_SEARCH_LEDGER_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    (PERSON_SEARCH_LEDGER_ALL, "すべて"),
    (PERSON_SEARCH_LEDGER_CURRENT, "現在帳"),
    (PERSON_SEARCH_LEDGER_MEMORIAL, "過去帳"),
)


def build_person_search_context(
    *,
    query: str = "",
    ledger: str = PERSON_SEARCH_LEDGER_ALL,
) -> dict:
    normalized_query = (query or "").strip()
    selected_ledger = _normalized_ledger_filter(ledger)
    ledger_options = _ledger_options(selected_ledger)

    try:
        active_source_id = operational_source_id()
    except KeyError:
        return {
            "available": False,
            "message": "運用中の source が見つかりません。",
            "query": normalized_query,
            "selected_ledger": selected_ledger,
            "ledger_options": ledger_options,
            "results": [],
            "result_count": 0,
            "rendered_result_count": 0,
            "truncated_result_count": 0,
            "needs_search": not normalized_query,
        }

    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if canonical_batch is None:
        return {
            "available": False,
            "message": "検索対象の現行台帳が見つかりません。",
            "query": normalized_query,
            "selected_ledger": selected_ledger,
            "ledger_options": ledger_options,
            "results": [],
            "result_count": 0,
            "rendered_result_count": 0,
            "truncated_result_count": 0,
            "needs_search": not normalized_query,
        }

    if not normalized_query:
        return {
            "available": True,
            "message": "",
            "query": normalized_query,
            "selected_ledger": selected_ledger,
            "ledger_options": ledger_options,
            "results": [],
            "result_count": 0,
            "rendered_result_count": 0,
            "truncated_result_count": 0,
            "needs_search": True,
        }

    queryset = _base_person_queryset()
    queryset = _apply_ledger_filter(queryset, selected_ledger)
    queryset = _apply_text_query(queryset, normalized_query)
    queryset = queryset.annotate(
        ledger_rank=Case(
            When(family_category=FAMILY_CATEGORY_CURRENT, then=Value(0)),
            When(family_category=FAMILY_CATEGORY_MEMORIAL, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("ledger_rank", "household__household_uid", "person_uid", "id")

    total_count = queryset.count()
    people = list(queryset[:PERSON_SEARCH_RENDER_LIMIT])
    results = [_person_search_row(person) for person in people]

    return {
        "available": True,
        "message": "",
        "query": normalized_query,
        "selected_ledger": selected_ledger,
        "ledger_options": ledger_options,
        "results": results,
        "result_count": total_count,
        "rendered_result_count": len(results),
        "truncated_result_count": max(total_count - len(results), 0),
        "needs_search": False,
    }


def _base_person_queryset() -> QuerySet[Person]:
    return Person.objects.filter(
        deleted_at__isnull=True,
        household__deleted_at__isnull=True,
    ).select_related("household", "deceased_profile")


def _normalized_ledger_filter(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {
        PERSON_SEARCH_LEDGER_CURRENT,
        PERSON_SEARCH_LEDGER_MEMORIAL,
    }:
        return normalized
    return PERSON_SEARCH_LEDGER_ALL


def _ledger_options(selected_ledger: str) -> list[dict[str, object]]:
    return [
        {
            "key": key,
            "label": label,
            "selected": key == selected_ledger,
        }
        for key, label in PERSON_SEARCH_LEDGER_OPTIONS
    ]


def _apply_ledger_filter(queryset: QuerySet[Person], selected_ledger: str) -> QuerySet[Person]:
    if selected_ledger == PERSON_SEARCH_LEDGER_CURRENT:
        return queryset.filter(family_category=FAMILY_CATEGORY_CURRENT)
    if selected_ledger == PERSON_SEARCH_LEDGER_MEMORIAL:
        return queryset.filter(family_category=FAMILY_CATEGORY_MEMORIAL)
    return queryset


def _apply_text_query(queryset: QuerySet[Person], query: str) -> QuerySet[Person]:
    queryset = queryset.annotate(
        name_compact=_compact_text_expression("name"),
        kana_compact=_compact_text_expression("kana"),
        relationship_label_compact=_compact_text_expression("relationship_label"),
        kaimyo_compact=_compact_text_expression("kaimyo"),
        deceased_profile_kaimyo_compact=_compact_text_expression("deceased_profile__kaimyo"),
    )
    terms = [term for term in re.split(r"\s+", query) if term]
    for term in terms:
        compact_term = _compact_text_value(term)
        queryset = queryset.filter(
            Q(person_uid__icontains=term)
            | Q(name__icontains=term)
            | Q(kana__icontains=term)
            | Q(relationship_label__icontains=term)
            | Q(kaimyo__icontains=term)
            | Q(deceased_profile__kaimyo__icontains=term)
            | Q(name_compact__icontains=compact_term)
            | Q(kana_compact__icontains=compact_term)
            | Q(relationship_label_compact__icontains=compact_term)
            | Q(kaimyo_compact__icontains=compact_term)
            | Q(deceased_profile_kaimyo_compact__icontains=compact_term)
        )
    return queryset


def _compact_text_expression(field_name: str):
    return Replace(
        Replace(Coalesce(field_name, Value("")), Value(" "), Value("")),
        Value("　"),
        Value(""),
    )


def _compact_text_value(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _person_search_row(person: Person) -> dict[str, object]:
    ledger_label = FAMILY_CATEGORY_LABELS.get(person.family_category, "未設定")
    ledger_key = {
        FAMILY_CATEGORY_CURRENT: PERSON_SEARCH_LEDGER_CURRENT,
        FAMILY_CATEGORY_MEMORIAL: PERSON_SEARCH_LEDGER_MEMORIAL,
    }.get(person.family_category, "other")
    profile = getattr(person, "deceased_profile", None)
    household_name = _household_display_head_name(person.household) or person.household.household_uid
    death_date = person.death_date or getattr(profile, "death_date", None)
    kaimyo = (person.kaimyo or "").strip() or (getattr(profile, "kaimyo", "") or "").strip()
    return {
        "household_id": person.household.household_uid,
        "person_id": person.person_uid,
        "name": (person.name or "").strip() or person.person_uid,
        "ledger_key": ledger_key,
        "ledger_label": ledger_label,
        "is_memorial": person.family_category == FAMILY_CATEGORY_MEMORIAL,
        "legacy_person_id": person.person_uid,
        "relationship_label": (person.relationship_label or "").strip(),
        "household_name": household_name,
        "legacy_household_id": person.household.household_uid,
        "kana": (person.kana or "").strip(),
        "death_date": death_date,
        "kaimyo": kaimyo,
    }
