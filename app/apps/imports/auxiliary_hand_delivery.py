from __future__ import annotations

import csv

from django.db import transaction

import apps.office.api as office_api

from . import canonical_population
from .auxiliary_input_support import (
    AUXILIARY_WORKSPACE_HINT,
    HAND_DELIVERY_FILE_NAME,
    HAND_DELIVERY_SKIP_DISTRICTS,
    _list_auxiliary_csv_candidates,
    _normalize_auxiliary_district_name,
    _normalize_auxiliary_household_name,
    _parse_auxiliary_sort_order,
)
from .auxiliary_role_support import _hand_delivery_household_candidate_payload
from .district_authority import (
    _district_officer_person_from_household,
    assign_district_officer_to_person,
    clear_district_officer_flags_for_household,
)
from .models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    HandDeliveryReviewResolution,
    Household,
    HouseholdProfile,
    LegacySource,
    Person,
)
from .runtime_shared import _clean_value


def list_auxiliary_hand_delivery_csv_candidates() -> list[dict]:
    return _list_auxiliary_csv_candidates(HAND_DELIVERY_FILE_NAME)


def latest_auxiliary_hand_delivery_csv_path(folder_name: str | None = None):
    candidates = list_auxiliary_hand_delivery_csv_candidates()
    if folder_name:
        selected = next((item for item in candidates if item["folder_name"] == folder_name), None)
        return selected["csv_path"] if selected else None
    return candidates[0]["csv_path"] if candidates else None


@transaction.atomic
def import_hand_delivery_district_assignments(
    source_id: str,
    *,
    folder_name: str | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    analysis = analyze_hand_delivery_district_rows(source_id, folder_name=folder_name)
    if not analysis["available"]:
        raise FileNotFoundError(
            f"{HAND_DELIVERY_FILE_NAME} が {AUXILIARY_WORKSPACE_HINT} 配下に見つかりません。"
        )

    source_record = LegacySource.objects.get(source_id=source_id)
    created_districts = 0
    updated_districts = 0
    assigned_households = 0
    officer_updates = 0
    contact_updates = 0
    officer_by_district: dict[str, Person] = {}
    touched_districts: dict[str, District] = {}
    # Lock all matched households before any District writes/appointments, in a stable order.
    households_by_pk = {
        household.pk: household
        for household in Household.objects.select_for_update(of=("self",)).filter(
            pk__in=[entry["matched_household"].pk for entry in analysis["matched_rows"]],
        ).order_by("pk")
    }

    for entry in analysis["matched_rows"]:
        district_name = entry["district_name"]
        household = households_by_pk[entry["matched_household"].pk]
        district_defaults = {
            "short_name": district_name,
            "sort_order": entry["sort_order"],
        }
        district, created = District.objects.get_or_create(name=district_name, defaults=district_defaults)
        before_district = {} if created else office_api.serialize_district(district)
        if created:
            created_districts += 1
        else:
            update_fields: list[str] = []
            if district.short_name != district_name:
                district.short_name = district_name
                update_fields.append("short_name")
            desired_sort_order = district_defaults["sort_order"]
            if desired_sort_order and district.sort_order != desired_sort_order:
                district.sort_order = desired_sort_order
                update_fields.append("sort_order")
            if update_fields:
                update_fields.append("updated_at")
                district.save(update_fields=update_fields)
                updated_districts += 1
        district_change_note = (
            f"手配りCSV {analysis['selected_folder_name']}/{HAND_DELIVERY_FILE_NAME} から地区情報を反映"
        )
        if change_note:
            district_change_note += f"。{change_note}"
        office_api.record_district_change(
            district,
            source_id=source_id,
            before_data=before_district,
            editor_label=editor_label,
            change_note=district_change_note,
        )
        touched_districts[district_name] = district

        household_update_fields: list[str] = []
        desired_postal_code = entry["postal_code"]
        desired_address_line1 = entry["address_line1"]
        desired_address_line2 = entry["address_line2"]
        desired_phone = entry["phone"]
        if desired_postal_code and household.postal_code != desired_postal_code:
            household.postal_code = desired_postal_code
            household_update_fields.append("postal_code")
        if desired_address_line1 and household.address_line1 != desired_address_line1:
            household.address_line1 = desired_address_line1
            household_update_fields.append("address_line1")
        if desired_address_line2 and household.address_line2 != desired_address_line2:
            household.address_line2 = desired_address_line2
            household_update_fields.append("address_line2")
        if desired_phone and household.phone != desired_phone:
            household.phone = desired_phone
            household_update_fields.append("phone")
        if household_update_fields:
            household_update_fields.append("updated_at")
            household.save(update_fields=household_update_fields)
            contact_updates += 1

        previous_profile = HouseholdProfile.objects.filter(
            source=source_record,
            household_uid=household.household_uid,
        ).first()
        if previous_profile is not None and (
            previous_profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
            or previous_profile.district_id != district.pk
        ):
            cleared_people = clear_district_officer_flags_for_household(
                source_id,
                household,
                editor_label=editor_label,
                change_note=change_note,
            )
            if cleared_people:
                officer_updates += 1

        HouseholdProfile.objects.update_or_create(
            source=source_record,
            household_uid=household.household_uid,
            defaults={
                "delivery_method": HOUSEHOLD_DELIVERY_DISTRICT,
                "district": district,
                "household_name_snapshot": household.display_head_name(),
                "household_name_kana_snapshot": household.display_head_name_kana(),
            },
        )
        assigned_households += 1

        if entry["is_officer"]:
            officer_person = _district_officer_person_from_household(household)
            if officer_person is not None:
                officer_by_district[district_name] = officer_person

    for district_name, _district in touched_districts.items():
        officer_person = officer_by_district.get(district_name)
        if officer_person is None:
            continue
        assignment = assign_district_officer_to_person(
            source_id,
            officer_person,
            editor_label=editor_label,
            change_note=change_note,
        )
        if assignment["changed"]:
            officer_updates += 1

    return {
        "csv_path": analysis["csv_path"],
        "selected_folder_name": analysis["selected_folder_name"],
        "created_districts": created_districts,
        "updated_districts": updated_districts,
        "assigned_households": assigned_households,
        "officer_updates": officer_updates,
        "contact_updates": contact_updates,
        "skipped_rows": analysis["skipped_count"],
        "unmatched_names": [entry["head_name"] for entry in analysis["unmatched_rows"][:10]],
        "ambiguous_names": [entry["head_name"] for entry in analysis["ambiguous_rows"][:10]],
        "unmatched_count": analysis["unmatched_count"],
        "ambiguous_count": analysis["ambiguous_count"],
    }


def analyze_hand_delivery_district_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    csv_path = latest_auxiliary_hand_delivery_csv_path(folder_name=folder_name)
    if csv_path is None:
        return {
            "available": False,
            "selected_folder_name": folder_name or "",
            "available_folders": [item["folder_name"] for item in list_auxiliary_hand_delivery_csv_candidates()],
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
        raise ValueError("地区割当を反映する対象の現行台帳がありません。")

    households = sorted(
        Household.objects.filter(deleted_at__isnull=True),
        key=lambda household: (
            _clean_value(household.display_head_name_kana()),
            _clean_value(household.display_head_name()),
            _clean_value(household.household_uid),
        ),
    )
    households_by_name: dict[str, list[Household]] = {}
    for household in households:
        normalized_display_name = _normalize_auxiliary_household_name(
            household.display_head_name()
        )
        if normalized_display_name:
            households_by_name.setdefault(normalized_display_name, []).append(household)

    selected_folder_name = csv_path.parent.name
    resolution_rows = HandDeliveryReviewResolution.objects.filter(
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
            district_name = _normalize_auxiliary_district_name(row[1] if len(row) > 1 else "")
            raw_head_name = _clean_value(row[3] if len(row) > 3 else "")
            head_name = _normalize_auxiliary_household_name(raw_head_name)
            entry = {
                "row_number": row_index,
                "sort_order": _parse_auxiliary_sort_order(row[0] if len(row) > 0 else "", row_index),
                "district_name": district_name,
                "role_mark": _clean_value(row[2] if len(row) > 2 else ""),
                "is_officer": _clean_value(row[2] if len(row) > 2 else "") == "★",
                "head_name": raw_head_name,
                "postal_code": _clean_value(row[4] if len(row) > 4 else ""),
                "address_line1": _clean_value(row[5] if len(row) > 5 else ""),
                "address_line2": _clean_value(row[6] if len(row) > 6 else ""),
                "phone": _clean_value(row[7] if len(row) > 7 else ""),
            }
            resolution = resolution_map.get(row_index)
            if not district_name or not head_name:
                skipped_rows.append({**entry, "skip_reason": "必須項目不足"})
                continue
            if head_name == _normalize_auxiliary_household_name("サンプル寺院"):
                skipped_rows.append({**entry, "skip_reason": "サンプル行"})
                continue
            if district_name in HAND_DELIVERY_SKIP_DISTRICTS:
                skipped_rows.append({**entry, "skip_reason": "除外地区"})
                continue

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
                ambiguous_entry = {
                        **entry,
                        "candidate_households": [
                            _hand_delivery_household_candidate_payload(item)
                            for item in matched_households
                        ],
                    "is_processed": resolution is not None,
                    "resolution": resolution,
                }
                ambiguous_rows.append(ambiguous_entry)
                if resolution is not None:
                    processed_rows.append(
                        {
                            **ambiguous_entry,
                            "current_match_status": "同名曖昧",
                        }
                    )
                continue
            household = matched_households[0]
            matched_entry = {
                **entry,
                "matched_household": household,
                "matched_household_display": _hand_delivery_household_candidate_payload(household),
            }
            matched_rows.append(matched_entry)
            if resolution is not None:
                processed_rows.append(
                    {
                        **entry,
                        "resolution": resolution,
                        "current_match_status": "一致",
                        "matched_household_display": _hand_delivery_household_candidate_payload(
                            household
                        ),
                    }
                )

    return {
        "available": True,
        "selected_folder_name": selected_folder_name,
        "available_folders": [item["folder_name"] for item in list_auxiliary_hand_delivery_csv_candidates()],
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
