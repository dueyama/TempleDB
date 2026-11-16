from __future__ import annotations

import csv

from . import canonical_population
from .auxiliary_input_support import (
    _normalize_auxiliary_household_name,
    _normalize_auxiliary_postal_code,
)
from .auxiliary_postal_support import (
    POSTAL_SKIP_CLASSIFICATIONS,
    _is_postal_imported_category,
    _postal_auxiliary_signature_from_entry,
    _postal_auxiliary_signature_from_household,
)
from .auxiliary_role_support import _hand_delivery_household_candidate_payload
from .models import Household, HouseholdProfile, PostalReviewResolution
from .runtime_shared import _clean_value


def _runtime_module():
    from . import auxiliary_postal

    return auxiliary_postal


def analyze_postal_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    runtime = _runtime_module()
    csv_path = runtime.latest_auxiliary_postal_csv_path(folder_name=folder_name)
    if csv_path is None:
        return {
            "available": False,
            "selected_folder_name": folder_name or "",
            "available_folders": [item["folder_name"] for item in runtime.list_auxiliary_postal_csv_candidates()],
            "csv_path": "",
            "matched_rows": [],
            "processed_rows": [],
            "unmatched_rows": [],
            "review_rows": [],
            "ambiguous_rows": [],
            "skipped_rows": [],
            "matched_count": 0,
            "processed_count": 0,
            "unmatched_count": 0,
            "processed_unmatched_count": 0,
            "pending_unmatched_count": 0,
            "ambiguous_count": 0,
            "skipped_count": 0,
        }

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        raise ValueError("郵送区分を反映する対象の現行台帳がありません。")

    households = sorted(
        Household.objects.filter(deleted_at__isnull=True),
        key=lambda household: (
            _clean_value(household.display_head_name_kana()),
            _clean_value(household.display_head_name()),
            _clean_value(household.household_uid),
        ),
    )
    households_by_name: dict[str, list[Household]] = {}
    auxiliary_postal_households_by_name: dict[str, list[Household]] = {}
    auxiliary_postal_households_by_signature: dict[tuple[str, str, str, str, str], Household] = {}
    for household in households:
        normalized_display_name = _normalize_auxiliary_household_name(household.display_head_name())
        if normalized_display_name:
            households_by_name.setdefault(normalized_display_name, []).append(household)
            if household.source_table == "auxiliary_postal_household":
                auxiliary_postal_households_by_name.setdefault(normalized_display_name, []).append(household)
                auxiliary_postal_households_by_signature[
                    _postal_auxiliary_signature_from_household(household)
                ] = household

    selected_folder_name = csv_path.parent.name
    resolution_rows = PostalReviewResolution.objects.filter(
        source__source_id=source_id,
        folder_name=selected_folder_name,
    ).order_by("row_number")
    resolution_map = {
        row.row_number: {
            "kind": row.resolution_kind,
            "label": row.get_resolution_kind_display(),
            "legacy_household_id": row.selected_household_uid,
            "entry_head_name": row.entry_head_name,
            "target_household_name_snapshot": row.target_household_name_snapshot,
            "editor_label": row.editor_label,
            "note": row.note,
            "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M"),
        }
        for row in resolution_rows
    }
    profile_rows = HouseholdProfile.objects.filter(
        source__source_id=source_id,
        delivery_method=runtime.HOUSEHOLD_DELIVERY_POSTAL,
    ).order_by("household_uid")

    matched_rows: list[dict] = []
    processed_rows: list[dict] = []
    unmatched_rows: list[dict] = []
    ambiguous_rows: list[dict] = []
    skipped_rows: list[dict] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader, start=1):
            if row_index == 1:
                continue
            raw_head_name = _clean_value(row[0] if len(row) > 0 else "")
            head_name = _normalize_auxiliary_household_name(raw_head_name)
            classification = _clean_value(row[4] if len(row) > 4 else "")
            entry = {
                "row_number": row_index,
                "head_name": raw_head_name,
                "postal_code": _normalize_auxiliary_postal_code(row[1] if len(row) > 1 else ""),
                "address_line1": _clean_value(row[2] if len(row) > 2 else ""),
                "address_line2": _clean_value(row[3] if len(row) > 3 else ""),
                "classification": classification,
                "phone": _clean_value(row[5] if len(row) > 5 else ""),
                "note": _clean_value(row[13] if len(row) > 13 else ""),
            }
            if not head_name:
                skipped_rows.append({**entry, "skip_reason": "氏名なし"})
                continue
            if head_name == _normalize_auxiliary_household_name("サンプル寺院"):
                skipped_rows.append({**entry, "skip_reason": "ダミー行"})
                continue
            if classification in POSTAL_SKIP_CLASSIFICATIONS:
                skipped_rows.append({**entry, "skip_reason": f"{classification} 対象外"})
                continue

            resolution = resolution_map.get(row_index)
            if resolution is None:
                inferred_profile = next(
                    (
                        profile
                        for profile in profile_rows
                        if _normalize_auxiliary_household_name(profile.mailing_name) == head_name
                        and _clean_value(profile.mailing_postal_code) == entry["postal_code"]
                        and _clean_value(profile.mailing_address_line1) == entry["address_line1"]
                        and _clean_value(profile.mailing_address_line2) == entry["address_line2"]
                        and _clean_value(profile.mailing_phone) == entry["phone"]
                    ),
                    None,
                )
                if inferred_profile is not None:
                    resolution = {
                        "kind": PostalReviewResolution.ResolutionKind.MAILING_OVERRIDE,
                        "label": PostalReviewResolution.ResolutionKind.MAILING_OVERRIDE.label,
                        "legacy_household_id": inferred_profile.household_uid,
                        "entry_head_name": inferred_profile.mailing_name,
                        "target_household_name_snapshot": inferred_profile.household_name_snapshot,
                        "editor_label": "",
                        "note": "既存の別郵送先設定と一致",
                        "updated_at": inferred_profile.updated_at.strftime("%Y-%m-%d %H:%M"),
                        "inferred": True,
                    }

            if _is_postal_imported_category(classification):
                matched_household = auxiliary_postal_households_by_signature.get(
                    _postal_auxiliary_signature_from_entry(entry)
                )
                if matched_household is not None:
                    matched_households = [matched_household]
                else:
                    matched_households = auxiliary_postal_households_by_name.get(head_name, [])
            else:
                matched_households = households_by_name.get(head_name, [])
            if not matched_households:
                unmatched_rows.append(
                    {
                        **entry,
                        "candidate_households": [],
                        "is_processed": resolution is not None,
                        "resolution": resolution,
                    }
                )
                continue
            if len(matched_households) > 1:
                if resolution is not None:
                    processed_rows.append(
                        {
                            **entry,
                            "resolution": resolution,
                            "current_match_status": "同名曖昧",
                            "candidate_households": [
                                _hand_delivery_household_candidate_payload(item)
                                for item in matched_households
                            ],
                        }
                    )
                ambiguous_rows.append(
                    {
                        **entry,
                        "candidate_households": [
                            _hand_delivery_household_candidate_payload(item)
                            for item in matched_households
                        ],
                    }
                )
                continue
            if resolution is not None:
                processed_rows.append(
                    {
                        **entry,
                        "resolution": resolution,
                        "current_match_status": "一致",
                        "matched_household_display": _hand_delivery_household_candidate_payload(
                            matched_households[0]
                        ),
                    }
                )
            matched_rows.append(
                {
                    **entry,
                    "matched_household": matched_households[0],
                    "matched_household_display": _hand_delivery_household_candidate_payload(
                        matched_households[0]
                    ),
                }
            )

    return {
        "available": True,
        "selected_folder_name": selected_folder_name,
        "available_folders": [item["folder_name"] for item in runtime.list_auxiliary_postal_csv_candidates()],
        "csv_path": str(csv_path),
        "matched_rows": matched_rows,
        "processed_rows": processed_rows,
        "unmatched_rows": unmatched_rows,
        "review_rows": sorted(
            [
                *unmatched_rows,
                *[{**item, "is_processed": True} for item in processed_rows],
            ],
            key=lambda item: item["row_number"],
        ),
        "ambiguous_rows": ambiguous_rows,
        "skipped_rows": skipped_rows,
        "matched_count": len(matched_rows),
        "processed_count": len(processed_rows),
        "unmatched_count": len(unmatched_rows),
        "processed_unmatched_count": sum(1 for item in unmatched_rows if item.get("is_processed")),
        "pending_unmatched_count": sum(1 for item in unmatched_rows if not item.get("is_processed")),
        "ambiguous_count": len(ambiguous_rows),
        "skipped_count": len(skipped_rows),
    }
