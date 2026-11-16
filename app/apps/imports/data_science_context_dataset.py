from __future__ import annotations

from django.db.models import Count, Q
from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population
from .data_science_shared import (
    _load_household_browser_dataset as _load_household_browser_dataset,
)
from .data_science_shared import (
    latest_export_snapshot,
    registered_sources,
    resolve_runtime_source_entry,
    source_summary,
)
from .models import ImportBatch, ImportIssue, Person

__all__ = [
    "latest_import_issue_breakdown",
]


def _resolved_data_science_dataset_context(
    source_id: str | None = None,
    data_backend: str = "db",
) -> dict:
    del source_id, data_backend
    source_entry = resolve_runtime_source_entry()
    active_source_id = source_entry["source_id"]
    latest_export = latest_export_snapshot(active_source_id)
    dataset = None
    dataset_error = ""
    provenance_batch = None
    try:
        provenance_batch = canonical_population.canonical_provenance_import_batch(
            source_id=active_source_id,
        )
        if provenance_batch is None:
            dataset_error = "検索対象の現行台帳が見つかりません。"
        else:
            dataset = _load_data_science_dataset_from_db(provenance_batch)
    except (OperationalError, ProgrammingError):
        dataset_error = "DB の過去帳データを読み出せませんでした。"
    return {
        "active_source_id": active_source_id,
        "source_entry": source_entry,
        "source_summary": source_summary(active_source_id),
        "registered_sources": registered_sources(active_source_id),
        "latest_export": latest_export,
        "canonical_batch": provenance_batch,
        "canonical_snapshot_id": (
            provenance_batch.prepared_snapshot_id if provenance_batch is not None else ""
        ),
        "dataset": dataset,
        "dataset_error": dataset_error,
    }


def _memorial_person_filter() -> Q:
    return (
        Q(is_deceased=True)
        | Q(death_date__isnull=False)
        | ~Q(death_date_raw="")
        | ~Q(kaimyo="")
        | ~Q(kaimyo_kana="")
        | ~Q(age_at_death_raw="")
        | Q(age_at_death__isnull=False)
        | ~Q(deceased_note="")
        | Q(hatsubon_flag=True)
        | Q(memorial_notice_opt_out=True)
    )


def _household_display_name(row: dict) -> str:
    if row["household__head_person__name"]:
        return row["household__head_person__name"]
    return row["household__household_uid"] or ""


def _person_age_at_death_display(row: dict) -> str:
    if row["age_at_death"] is not None:
        return str(row["age_at_death"])
    return ""


def _person_death_date_display(row: dict) -> str:
    if row["death_date"] is not None:
        return row["death_date"].isoformat()
    return ""


def _data_science_member_from_person(row: dict) -> dict:
    household_name = _household_display_name(row)
    death_date_display = _person_death_date_display(row)
    return {
        "person_id": row["person_uid"],
        "household_id": row["household__household_uid"],
        "household_name": household_name,
        "name": row["name"],
        "kana": row["kana"],
        "relationship": row["relationship_label"],
        "death_date": death_date_display,
        "death_date_display": death_date_display,
        "death_date_iso": death_date_display,
        "death_date_raw": row["death_date_raw"],
        "kaimyo": row["kaimyo"],
        "age_at_death": _person_age_at_death_display(row),
        "age_at_death_raw": row["age_at_death_raw"],
        "age_unit": row["age_unit"] or "歳",
        "display_fields": [
            {
                "label": "性別",
                "value": row["gender"],
            }
        ],
    }


def _load_data_science_dataset_from_db(batch: ImportBatch) -> dict:
    del batch
    people = (
        Person.objects.filter(
            deleted_at__isnull=True,
        )
        .filter(_memorial_person_filter())
        .values(
            "person_uid",
            "name",
            "kana",
            "relationship_label",
            "gender",
            "is_deceased",
            "death_date_raw",
            "death_date",
            "kaimyo",
            "age_at_death_raw",
            "age_at_death",
            "age_unit",
            "household__household_uid",
            "household__head_person__name",
        )
        .order_by("household__household_uid", "person_uid", "id")
    )
    household_details: dict[str, dict] = {}
    for person in people.iterator(chunk_size=1000):
        household_id = person["household__household_uid"]
        household_name = _household_display_name(person)
        detail = household_details.setdefault(
            household_id,
            {
                "summary": {
                    "household_id": household_id,
                    "name": household_name,
                    "memorial_count": 0,
                },
                "memorial_members": [],
            },
        )
        detail["memorial_members"].append(_data_science_member_from_person(person))
        detail["summary"]["memorial_count"] = len(detail["memorial_members"])

    return {
        "households": list(household_details.values()),
        "household_details": household_details,
        "data_backend": "db",
    }


def latest_import_issue_breakdown(source_id: str) -> list[dict]:
    try:
        batch = canonical_population.canonical_provenance_import_batch(
            source_id=source_id,
        )
    except (OperationalError, ProgrammingError):
        return []
    if batch is None:
        return []
    return list(
        ImportIssue.objects.filter(batch=batch)
        .values("severity", "code")
        .annotate(count=Count("id"))
        .order_by("-count", "severity", "code")
    )
