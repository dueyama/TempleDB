from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final

from django.db.models import QuerySet

from apps.imports import canonical_population, source_runtime
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_LABELS,
    FAMILY_CATEGORY_MEMORIAL,
    Household,
    Person,
)

from .household_editing_core import _household_display_head_name
from .person_search import (
    PERSON_SEARCH_LEDGER_ALL,
    PERSON_SEARCH_LEDGER_CURRENT,
    PERSON_SEARCH_LEDGER_MEMORIAL,
    build_person_search_context,
)

DEFAULT_AI_SEARCH_LIMIT: Final[int] = 10
MAX_AI_SEARCH_LIMIT: Final[int] = 25
MAX_HOUSEHOLD_SUMMARY_PEOPLE: Final[int] = 50

_LEDGER_FILTERS: Final[set[str]] = {
    PERSON_SEARCH_LEDGER_ALL,
    PERSON_SEARCH_LEDGER_CURRENT,
    PERSON_SEARCH_LEDGER_MEMORIAL,
}
_REDACTED_HOUSEHOLD_FIELDS: Final[tuple[str, ...]] = (
    "postal_code",
    "address_line1",
    "address_line2",
    "address_line3",
    "phone",
    "fax",
    "mobile",
    "email",
    "notes",
    "raw_record",
)
_REDACTED_PERSON_FIELDS: Final[tuple[str, ...]] = (
    "person_note",
    "deceased_note",
    "raw_record",
)


def search_templedb_people(
    query: str,
    ledger: str = PERSON_SEARCH_LEDGER_ALL,
    limit: int = DEFAULT_AI_SEARCH_LIMIT,
) -> dict:
    normalized_query = _clean_text(query)
    normalized_ledger = _normalize_ledger(ledger)
    normalized_limit = _normalize_limit(limit)
    scope = _current_ai_scope()
    if not scope["available"]:
        return {
            **_public_scope(scope),
            "query": normalized_query,
            "selected_ledger": normalized_ledger,
            "limit": normalized_limit,
            "needs_search": bool(not normalized_query),
            "results": [],
            "result_count": 0,
            "returned_count": 0,
            "truncated_count": 0,
        }
    if not normalized_query:
        return {
            **_public_scope(scope),
            "query": normalized_query,
            "selected_ledger": normalized_ledger,
            "limit": normalized_limit,
            "needs_search": True,
            "results": [],
            "result_count": 0,
            "returned_count": 0,
            "truncated_count": 0,
        }

    context = build_person_search_context(query=normalized_query, ledger=normalized_ledger)
    if not context.get("available", False):
        return {
            **_public_scope(scope),
            "available": False,
            "reason": "search_unavailable",
            "message": str(context.get("message") or "検索対象を解決できません。"),
            "query": normalized_query,
            "selected_ledger": normalized_ledger,
            "limit": normalized_limit,
            "needs_search": False,
            "results": [],
            "result_count": 0,
            "returned_count": 0,
            "truncated_count": 0,
        }

    raw_results = list(context.get("results") or [])
    returned_results = [_person_search_result(row) for row in raw_results[:normalized_limit]]
    result_count = int(context.get("result_count") or 0)
    return {
        **_public_scope(scope),
        "query": normalized_query,
        "selected_ledger": normalized_ledger,
        "limit": normalized_limit,
        "needs_search": False,
        "results": returned_results,
        "result_count": result_count,
        "returned_count": len(returned_results),
        "truncated_count": max(result_count - len(returned_results), 0),
    }


def get_templedb_household_summary(household_id: str) -> dict:
    normalized_household_id = _clean_text(household_id)
    scope = _current_ai_scope()
    if not scope["available"]:
        return {
            **_public_scope(scope),
            "household_id": normalized_household_id,
            "household": None,
            "people": [],
        }
    if not normalized_household_id:
        return {
            **_public_scope(scope),
            "available": False,
            "reason": "empty_household_id",
            "message": "household_id を指定してください。",
            "household_id": normalized_household_id,
            "household": None,
            "people": [],
        }

    household = (
        Household.objects.select_related("head_person", "batch")
        .filter(
            household_uid=normalized_household_id,
            deleted_at__isnull=True,
        )
        .first()
    )
    if household is None:
        return {
            **_public_scope(scope),
            "available": False,
            "reason": "household_not_found",
            "message": "指定された household_id は現行台帳に見つかりません。",
            "household_id": normalized_household_id,
            "household": None,
            "people": [],
        }

    people = list(_household_people_queryset(household)[:MAX_HOUSEHOLD_SUMMARY_PEOPLE])
    people_rows = [_household_person_row(person) for person in people]
    current_count = sum(1 for person in people if person.family_category == FAMILY_CATEGORY_CURRENT)
    memorial_count = sum(
        1 for person in people if person.family_category == FAMILY_CATEGORY_MEMORIAL
    )
    return {
        **_public_scope(scope),
        "household_id": normalized_household_id,
        "household": {
            "legacy_household_id": household.household_uid,
            "head_name": _household_display_head_name(household) or household.household_uid,
            "head_person_id": (
                household.head_person.person_uid
                if household.head_person_id and household.head_person is not None
                else ""
            ),
            "ledger_category": household.ledger_category or "",
            "people_count": len(people_rows),
            "current_people_count": current_count,
            "memorial_people_count": memorial_count,
            "redacted_fields": list(_REDACTED_HOUSEHOLD_FIELDS),
        },
        "people": people_rows,
        "people_limit": MAX_HOUSEHOLD_SUMMARY_PEOPLE,
        "truncated_people_count": max(
            _household_people_queryset(household).count() - len(people_rows),
            0,
        ),
    }


def _current_ai_scope() -> dict:
    try:
        source_id = source_runtime.operational_source_id()
    except (KeyError, RuntimeError) as exc:
        return {
            "available": False,
            "reason": "source_unavailable",
            "message": str(exc) or "運用中の source が見つかりません。",
            "source_id": "",
            "batch_id": "",
            "prepared_snapshot_id": "",
        }

    batch = canonical_population.canonical_provenance_import_batch(source_id=source_id)
    if batch is None:
        return {
            "available": False,
            "reason": "batch_unavailable",
            "message": "検索対象の現行台帳が見つかりません。",
            "source_id": source_id,
            "batch_id": "",
            "prepared_snapshot_id": "",
        }
    return {
        "available": True,
        "reason": "",
        "message": "",
        "source_id": source_id,
        "batch_id": str(batch.batch_uuid),
        "prepared_snapshot_id": batch.prepared_snapshot_id or "",
        "_batch": batch,
    }


def _public_scope(scope: dict) -> dict:
    return {key: value for key, value in scope.items() if not key.startswith("_")}


def _household_people_queryset(household: Household) -> QuerySet[Person]:
    return (
        Person.objects.select_related("deceased_profile")
        .filter(household=household, deleted_at__isnull=True)
        .order_by("family_category", "person_uid", "id")
    )


def _household_person_row(person: Person) -> dict:
    profile = getattr(person, "deceased_profile", None)
    death_date = person.death_date or getattr(profile, "death_date", None)
    kaimyo = (person.kaimyo or "").strip() or (getattr(profile, "kaimyo", "") or "").strip()
    return {
        "legacy_person_id": person.person_uid,
        "name": (person.name or "").strip() or person.person_uid,
        "kana": (person.kana or "").strip(),
        "relationship_label": (person.relationship_label or "").strip(),
        "ledger_key": person.family_category or "",
        "ledger_label": FAMILY_CATEGORY_LABELS.get(person.family_category, "未設定"),
        "is_deceased": bool(person.is_deceased),
        "death_date": _json_date(death_date),
        "kaimyo": kaimyo,
        "age_at_death": person.age_at_death,
        "redacted_fields": list(_REDACTED_PERSON_FIELDS),
    }


def _person_search_result(row: dict) -> dict:
    return {
        "legacy_household_id": _string(row.get("legacy_household_id")),
        "household_name": _string(row.get("household_name")),
        "legacy_person_id": _string(row.get("legacy_person_id")),
        "name": _string(row.get("name")),
        "kana": _string(row.get("kana")),
        "relationship_label": _string(row.get("relationship_label")),
        "ledger_key": _string(row.get("ledger_key")),
        "ledger_label": _string(row.get("ledger_label")),
        "is_memorial": bool(row.get("is_memorial")),
        "death_date": _json_date(row.get("death_date")),
        "kaimyo": _string(row.get("kaimyo")),
    }


def _normalize_ledger(value: str | None) -> str:
    normalized = _clean_text(value).lower()
    if normalized in _LEDGER_FILTERS:
        return normalized
    return PERSON_SEARCH_LEDGER_ALL


def _normalize_limit(value: int | str | None) -> int:
    try:
        parsed = int(value) if value is not None else DEFAULT_AI_SEARCH_LIMIT
    except (TypeError, ValueError):
        parsed = DEFAULT_AI_SEARCH_LIMIT
    return min(max(parsed, 1), MAX_AI_SEARCH_LIMIT)


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _string(value: object) -> str:
    return str(value or "").strip()


def _json_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _string(value)
