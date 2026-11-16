from __future__ import annotations

from datetime import date

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population, source_runtime
from .data_science_demographic_completeness import _normalize_gender
from .data_science_shared import _clean_value
from .models import Person

DEATH_DEMOGRAPHICS_CSV_COLUMNS = ("往生年月日", "往生年齢", "性別")

__all__ = [
    "DEATH_DEMOGRAPHICS_CSV_COLUMNS",
    "build_death_demographics_csv_rows",
]


def _age_at_death_csv_value(person: Person) -> str:
    if person.age_at_death is not None:
        return str(person.age_at_death)
    return _clean_value(person.age_at_death_raw)


def build_death_demographics_csv_rows(
    *,
    start_date: date,
    end_date: date,
) -> dict:
    source_entry = source_runtime.resolve_runtime_source_entry()
    source_id = source_entry["source_id"]
    batch = canonical_population.canonical_provenance_import_batch(source_id=source_id)
    snapshot_id = batch.prepared_snapshot_id if batch is not None else ""
    if batch is None:
        return {
            "available": False,
            "message": "検索対象の現行台帳が見つかりません。",
            "rows": [],
            "source_id": source_id,
            "snapshot_id": snapshot_id,
        }

    try:
        people = (
            Person.objects.filter(
                deleted_at__isnull=True,
                death_date__gte=start_date,
                death_date__lte=end_date,
            )
            .exclude(death_date__isnull=True)
            .order_by("death_date", "household__household_uid", "person_uid", "id")
        )
        rows = [
            {
                "往生年月日": person.death_date.isoformat() if person.death_date else "",
                "往生年齢": _age_at_death_csv_value(person),
                "性別": _normalize_gender(person.gender),
            }
            for person in people
        ]
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "message": "DB の過去帳データを読み出せませんでした。",
            "rows": [],
            "source_id": source_id,
            "snapshot_id": snapshot_id,
        }

    return {
        "available": True,
        "message": "",
        "rows": rows,
        "source_id": source_id,
        "snapshot_id": snapshot_id,
    }
