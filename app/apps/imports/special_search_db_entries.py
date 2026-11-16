from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Substr, Trim
from django.db.utils import OperationalError, ProgrammingError

from . import (
    browser_dataset_member_rows,
    browser_dataset_model_rows,
    canonical_population,
    model_households,
    special_search_dataset_entries,
)
from .models import FAMILY_CATEGORY_CURRENT, ImportBatch, Person
from .runtime_shared import (
    _clean_value,
    _display_value,
    _int_sort,
    _join_values,
    _parse_iso_date,
    _sort_text,
)


def build_recent_death_search_entries(
    *,
    source_id: str | None,
    latest_batch: ImportBatch | None,
) -> list[dict]:
    if not source_id or latest_batch is None:
        return []

    today = special_search_dataset_entries._runtime_timezone().localdate()
    cutoff = today - timedelta(days=365)
    try:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
        people = list(
            Person.objects.select_related("household", "household__head_person")
            .annotate(
                normalized_death_date_raw=Substr(Trim("death_date_raw"), 1, 10),
                normalized_legacy_death_date=Substr(
                    Trim(KeyTextTransform("命日", "raw_record")),
                    1,
                    10,
                ),
            )
            .filter(
                Q(death_date__gte=cutoff)
                | Q(normalized_death_date_raw__gte=cutoff.isoformat())
                | Q(normalized_legacy_death_date__gte=cutoff.isoformat()),
                deleted_at__isnull=True,
                household__deleted_at__isnull=True,
            )
            .exclude(family_category=FAMILY_CATEGORY_CURRENT)
            .order_by()
        )
    except (OperationalError, ProgrammingError):
        return []

    unresolved_household_ids = {
        person.household_id
        for person in people
        if person.household.head_person_id is None
        or person.household.head_person is None
        or person.household.head_person.deleted_at is not None
    }
    active_people_by_household: dict[int, list[Person]] = {}
    if unresolved_household_ids:
        for active_person in (
            Person.objects.filter(
                household_id__in=unresolved_household_ids,
                deleted_at__isnull=True,
            )
            .only("id", "household_id", "person_uid", "name", "kana")
            .order_by("household_id", "person_uid", "id")
        ):
            active_people_by_household.setdefault(
                active_person.household_id,
                [],
            ).append(active_person)

    entries = []
    for person in people:
        row = browser_dataset_model_rows._person_row_from_model(person)
        if browser_dataset_member_rows._is_placeholder_person_row(row):
            continue
        if not browser_dataset_member_rows._is_memorial_person(row):
            continue
        death_date_text = _display_value(row.get("命日"))
        death_date = _parse_iso_date(death_date_text)
        if death_date is None or death_date < cutoff:
            continue
        entries.append(
            {
                "household_id": person.household.household_uid,
                "household_name": model_households.bulk_safe_display_head_name(
                    person.household,
                    active_people_by_household.get(person.household_id, []),
                ),
                "person_id": _clean_value(row.get("家族ID")),
                "person_name": _clean_value(row.get("氏名")),
                "kana": _clean_value(row.get("ﾌﾘｶﾞﾅ")),
                "relationship": _clean_value(row.get("続柄")),
                "kaimyo": _clean_value(row.get("戒名")),
                "death_date": death_date_text,
                "age_at_death": _clean_value(row.get("享年")),
                "age_unit": _clean_value(row.get("享年単位")) or "歳",
                "note": _join_values(row.get("個人備考"), row.get("故人備考")),
                "status_label": "過去1年",
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["death_date"]),
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
        reverse=True,
    )
