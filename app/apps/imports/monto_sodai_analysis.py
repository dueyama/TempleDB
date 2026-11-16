from __future__ import annotations

import csv

from django.db import transaction

from . import canonical_population, monto_sodai_sources
from .auxiliary_input_support import (
    AUXILIARY_WORKSPACE_HINT,
    MONTO_SODAI_FILE_NAME,
    _normalize_auxiliary_household_name,
    _normalize_auxiliary_postal_code,
)
from .auxiliary_role_support import (
    _monto_sodai_candidate_payload,
    _monto_sodai_candidates_for_entry,
)
from .models import FAMILY_CATEGORY_CURRENT, Person
from .runtime_shared import _clean_value


def analyze_monto_sodai_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    csv_path = monto_sodai_sources.latest_auxiliary_monto_sodai_csv_path(folder_name=folder_name)
    if csv_path is None:
        return {
            "available": False,
            "selected_folder_name": folder_name or "",
            "available_folders": [
                item["folder_name"]
                for item in monto_sodai_sources.list_auxiliary_monto_sodai_csv_candidates()
            ],
            "csv_path": "",
            "matched_rows": [],
            "unmatched_rows": [],
            "ambiguous_rows": [],
            "skipped_rows": [],
            "matched_count": 0,
            "unmatched_count": 0,
            "ambiguous_count": 0,
            "skipped_count": 0,
        }

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        raise ValueError("総代一覧を反映する対象の現行台帳がありません。")

    people = list(
        Person.objects.select_related("household")
        .filter(
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
        )
        .order_by(
            "household__head_person__kana",
            "household__head_person__name",
            "kana",
            "name",
            "person_uid",
        )
    )
    people_by_name: dict[str, list[Person]] = {}
    for person in people:
        normalized_name = _normalize_auxiliary_household_name(person.name)
        if normalized_name:
            people_by_name.setdefault(normalized_name, []).append(person)

    matched_rows: list[dict] = []
    unmatched_rows: list[dict] = []
    ambiguous_rows: list[dict] = []
    skipped_rows: list[dict] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader, start=1):
            raw_name = _clean_value(row[0] if len(row) > 0 else "")
            normalized_name = _normalize_auxiliary_household_name(raw_name)
            entry = {
                "row_number": row_index,
                "name": raw_name,
                "postal_code": _normalize_auxiliary_postal_code(row[1] if len(row) > 1 else ""),
                "address_line1": _clean_value(row[2] if len(row) > 2 else ""),
                "address_line2": _clean_value(row[3] if len(row) > 3 else ""),
                "phone": _clean_value(row[4] if len(row) > 4 else ""),
            }
            if not normalized_name:
                skipped_rows.append({**entry, "skip_reason": "氏名なし"})
                continue
            matched_people = _monto_sodai_candidates_for_entry(
                entry,
                people_by_name.get(normalized_name, []),
            )
            if not matched_people:
                unmatched_rows.append({**entry, "candidate_people": []})
                continue
            if len(matched_people) > 1:
                ambiguous_rows.append(
                    {
                        **entry,
                        "candidate_people": [
                            _monto_sodai_candidate_payload(person) for person in matched_people
                        ],
                    }
                )
                continue
            person = matched_people[0]
            matched_rows.append(
                {
                    **entry,
                    "matched_person": person,
                    "matched_person_display": _monto_sodai_candidate_payload(person),
                }
            )

    return {
        "available": True,
        "selected_folder_name": csv_path.parent.name,
        "available_folders": [
            item["folder_name"]
            for item in monto_sodai_sources.list_auxiliary_monto_sodai_csv_candidates()
        ],
        "csv_path": str(csv_path),
        "matched_rows": matched_rows,
        "unmatched_rows": unmatched_rows,
        "ambiguous_rows": ambiguous_rows,
        "skipped_rows": skipped_rows,
        "matched_count": len(matched_rows),
        "unmatched_count": len(unmatched_rows),
        "ambiguous_count": len(ambiguous_rows),
        "skipped_count": len(skipped_rows),
    }


@transaction.atomic
def import_monto_sodai_assignments(
    source_id: str,
    *,
    folder_name: str | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    from apps.office.api import assign_monto_sodai_to_person

    analysis = analyze_monto_sodai_rows(source_id, folder_name=folder_name)
    if not analysis["available"]:
        raise FileNotFoundError(
            f"{MONTO_SODAI_FILE_NAME} が {AUXILIARY_WORKSPACE_HINT} 配下に見つかりません。"
        )

    assigned_count = 0
    already_assigned_count = 0
    for entry in analysis["matched_rows"]:
        person: Person = entry["matched_person"]
        if not assign_monto_sodai_to_person(
            person,
            editor_label=editor_label,
            change_note=change_note,
        ):
            already_assigned_count += 1
            continue
        assigned_count += 1

    return {
        "csv_path": analysis["csv_path"],
        "selected_folder_name": analysis["selected_folder_name"],
        "assigned_count": assigned_count,
        "already_assigned_count": already_assigned_count,
        "matched_count": analysis["matched_count"],
        "unmatched_count": analysis["unmatched_count"],
        "ambiguous_count": analysis["ambiguous_count"],
        "skipped_count": analysis["skipped_count"],
        "unmatched_names": [entry["name"] for entry in analysis["unmatched_rows"][:10]],
        "ambiguous_names": [entry["name"] for entry in analysis["ambiguous_rows"][:10]],
    }
