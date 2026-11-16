from __future__ import annotations

from . import canonical_population
from .auxiliary_input_support import (
    AUXILIARY_WORKSPACE_HINT,
    POSTAL_FILE_NAME,
)
from .auxiliary_postal_compare_support import (
    _build_postal_compare_csv_rows,
    _build_postal_compare_db_rows,
    _compare_postal_compare_rows,
)
from .auxiliary_role_support import _hand_delivery_household_candidate_payload
from .models import Household
from .runtime_shared import (
    _clean_value,
)


def _runtime_module():
    from . import auxiliary_postal

    return auxiliary_postal


def build_postal_compare_context(source_id: str, *, folder_name: str | None = None) -> dict:
    runtime = _runtime_module()
    csv_path = runtime.latest_auxiliary_postal_csv_path(folder_name=folder_name)
    available_folders = [item["folder_name"] for item in runtime.list_auxiliary_postal_csv_candidates()]
    if csv_path is None:
        return {
            "available": False,
            "error_message": f"{POSTAL_FILE_NAME} が {AUXILIARY_WORKSPACE_HINT} 配下に見つかりません。",
            "selected_folder_name": folder_name or "",
            "available_folders": available_folders,
            "csv_path": "",
            "db_rows": [],
            "csv_rows": [],
            "exact_matches": [],
            "field_mismatches": [],
            "csv_only": [],
            "db_only": [],
            "summary": {
                "db_count": 0,
                "csv_count": 0,
                "exact_count": 0,
                "mismatch_count": 0,
                "csv_only_count": 0,
                "db_only_count": 0,
            },
        }

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        return {
            "available": False,
            "error_message": "比較対象の現行台帳がありません。",
            "selected_folder_name": csv_path.parent.name,
            "available_folders": available_folders,
            "csv_path": str(csv_path),
            "db_rows": [],
            "csv_rows": [],
            "exact_matches": [],
            "field_mismatches": [],
            "csv_only": [],
            "db_only": [],
            "summary": {
                "db_count": 0,
                "csv_count": 0,
                "exact_count": 0,
                "mismatch_count": 0,
                "csv_only_count": 0,
                "db_only_count": 0,
            },
        }

    csv_rows = _build_postal_compare_csv_rows(csv_path)
    db_rows = _build_postal_compare_db_rows(
        source_id,
        provenance_batch,
        canonical_scope=True,
    )
    exact_matches, field_mismatches, csv_only, db_only = _compare_postal_compare_rows(
        db_rows=db_rows,
        csv_rows=csv_rows,
    )
    return {
        "available": True,
        "error_message": "",
        "selected_folder_name": csv_path.parent.name,
        "available_folders": available_folders,
        "csv_path": str(csv_path),
        "db_rows": db_rows,
        "csv_rows": csv_rows,
        "exact_matches": exact_matches,
        "field_mismatches": field_mismatches,
        "csv_only": csv_only,
        "db_only": db_only,
        "summary": {
            "db_count": len(db_rows),
            "csv_count": len(csv_rows),
            "exact_count": len(exact_matches),
            "mismatch_count": len(field_mismatches),
            "csv_only_count": len(csv_only),
            "db_only_count": len(db_only),
        },
    }


def search_households_for_postal_review(source_id: str, query: str, *, limit: int = 20) -> list[dict]:
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        return []
    lowered_query = _clean_value(query).lower()
    if not lowered_query:
        return []
    matched_households: list[dict] = []
    households = sorted(
        Household.objects.filter(deleted_at__isnull=True),
        key=lambda household: (
            _clean_value(household.display_head_name_kana()),
            _clean_value(household.display_head_name()),
            _clean_value(household.household_uid),
        ),
    )
    for household in households:
        haystacks = [
            household.household_uid,
            household.display_head_name(),
            household.display_head_name_kana(),
            household.postal_code,
            household.address_line1,
            household.address_line2,
            household.address_line3,
            household.phone,
        ]
        if any(lowered_query in (_clean_value(value).lower()) for value in haystacks):
            matched_households.append(_hand_delivery_household_candidate_payload(household))
        if len(matched_households) >= limit:
            break
    return matched_households
