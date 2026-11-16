from __future__ import annotations

from django.db import transaction

import apps.office.api as office_api

from . import canonical_population
from .auxiliary_input_support import (
    AUXILIARY_WORKSPACE_HINT,
    POSTAL_FILE_NAME,
)
from .auxiliary_postal_import_support import (
    _create_postal_import_household,
    _is_postal_imported_category,
    _ledger_category_label,
    _postal_imported_ledger_category,
)
from .models import Household, LegacySource
from .runtime_shared import _clean_value


def _runtime_module():
    from . import auxiliary_postal

    return auxiliary_postal


@transaction.atomic
def import_postal_assignments(
    source_id: str, *, folder_name: str | None = None,
    editor_label: str = "", change_note: str = "",
) -> dict:
    runtime = _runtime_module()
    analysis = runtime.analyze_postal_rows(source_id, folder_name=folder_name)
    if not analysis["available"]:
        raise FileNotFoundError(f"{POSTAL_FILE_NAME} が {AUXILIARY_WORKSPACE_HINT} 配下に見つかりません。")

    source_record = LegacySource.objects.get(source_id=source_id)
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        raise ValueError("郵送区分を反映する対象の現行台帳がありません。")
    assigned_households = 0
    created_households = 0
    contact_updates = 0
    change_note = (change_note or "").strip() or (
        f"郵送CSV {analysis['selected_folder_name'] or POSTAL_FILE_NAME} を反映"
    )

    for entry in analysis["matched_rows"]:
        household: Household = entry["matched_household"]
        ledger_category = _postal_imported_ledger_category(entry.get("classification"))
        contacts_changed = office_api.apply_household_postal_assignment(
            household=household,
            source_record=source_record,
            contact_values={field: entry[field] for field in (
                "postal_code", "address_line1", "address_line2", "phone",
            )},
            ledger_category=ledger_category,
            raw_record_updates={
                "台帳区分": _ledger_category_label(ledger_category),
                "郵送名簿区分": _clean_value(entry.get("classification")),
            } if ledger_category else None,
            editor_label=editor_label,
            change_note=change_note,
        )
        contact_updates += int(contacts_changed)
        assigned_households += 1

    for entry in analysis["unmatched_rows"]:
        if not _is_postal_imported_category(entry.get("classification")):
            continue
        if entry.get("is_processed"):
            continue
        household = _create_postal_import_household(
            batch=provenance_batch,
            source_record=source_record,
            entry=entry,
        )
        office_api.record_postal_household_creation(
            household=household,
            source_record=source_record,
            editor_label=editor_label,
            change_note=f"{change_note}（{entry['head_name']} から婦人会の家を作成）",
        )
        created_households += 1

    return {
        "csv_path": analysis["csv_path"],
        "selected_folder_name": analysis["selected_folder_name"],
        "assigned_households": assigned_households,
        "created_households": created_households,
        "contact_updates": contact_updates,
        "skipped_rows": analysis["skipped_count"],
        "unmatched_names": [entry["head_name"] for entry in analysis["unmatched_rows"][:10]],
        "ambiguous_names": [entry["head_name"] for entry in analysis["ambiguous_rows"][:10]],
        "unmatched_count": analysis["unmatched_count"],
        "ambiguous_count": analysis["ambiguous_count"],
    }
