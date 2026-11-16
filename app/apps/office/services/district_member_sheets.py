from __future__ import annotations

from datetime import date

from django.db.utils import OperationalError, ProgrammingError

from apps.imports import canonical_population, memorial_notice_runtime
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    HOUSEHOLD_DELIVERY_NONE,
    HOUSEHOLD_DELIVERY_POSTAL,
    District,
    DistrictMemberSheetState,
    Household,
    HouseholdProfile,
    Person,
)
from apps.imports.runtime_shared import _clean_value, _int_sort, _sort_text

from .district_authority import _district_profile_map_for_households


def _district_member_sheet_snapshot(*, household: Household, is_district_officer: bool) -> dict:
    return {
        "household_id": household.household_uid,
        "head_person_id": household.head_person.person_uid if household.head_person_id else "",
        "name": _clean_value(household.display_head_name()),
        "kana": _clean_value(household.display_head_name_kana()),
        "is_district_officer": bool(is_district_officer),
    }


def _district_member_sheet_label(snapshot: dict) -> str:
    name = _clean_value(snapshot.get("name")) or _clean_value(snapshot.get("household_id"))
    prefix = "※" if snapshot.get("is_district_officer") else ""
    return f"{prefix}{name}"


def _district_member_removed_reason(
    *,
    district: District,
    snapshot: dict,
    current_households_by_id: dict[str, Household],
    current_profile_map: dict[str, HouseholdProfile],
) -> str:
    household_id = _clean_value(snapshot.get("household_id"))
    current_household = current_households_by_id.get(household_id)
    if current_household is None:
        return "現在帳から外れた"
    profile = current_profile_map.get(current_household.household_uid)
    if profile is None:
        return "送付区分未設定"
    if profile.delivery_method == HOUSEHOLD_DELIVERY_POSTAL:
        return "郵送へ変更"
    if profile.delivery_method == HOUSEHOLD_DELIVERY_NONE:
        return "送付しないへ変更"
    if profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT:
        return HOUSEHOLD_DELIVERY_LABELS.get(profile.delivery_method, "地区一覧から外れた")
    if profile.district_id and profile.district_id != district.id and profile.district is not None:
        return f"{profile.district.name}へ変更"
    if profile.district_id and profile.district_id != district.id:
        return "別地区へ変更"
    return "地区一覧から外れた"


def _district_member_auto_notes(
    *,
    district: District,
    previous_snapshot: list[dict],
    current_snapshot: list[dict],
    current_households_by_id: dict[str, Household],
    current_profile_map: dict[str, HouseholdProfile],
) -> list[str]:
    previous_by_key = {
        _clean_value(row.get("household_id")): row
        for row in previous_snapshot
        if _clean_value(row.get("household_id"))
    }
    current_by_key = {
        _clean_value(row.get("household_id")): row
        for row in current_snapshot
        if _clean_value(row.get("household_id"))
    }
    removed_labels = []
    for key in previous_by_key:
        if key in current_by_key:
            continue
        snapshot = previous_by_key[key]
        label = _district_member_sheet_label(snapshot)
        reason = _district_member_removed_reason(
            district=district,
            snapshot=snapshot,
            current_households_by_id=current_households_by_id,
            current_profile_map=current_profile_map,
        )
        removed_labels.append(f"{label}（{reason}）")
    added_labels = [
        _district_member_sheet_label(current_by_key[key])
        for key in current_by_key
        if key not in previous_by_key
    ]
    notes: list[str] = []
    if removed_labels:
        notes.append("前回から外れた: " + "、".join(removed_labels))
    if added_labels:
        notes.append("今回追加: " + "、".join(added_labels))
    return notes


def build_district_member_sheet_context(
    source_id: str,
    *,
    include_memorial_notice_marker: bool = False,
) -> dict:
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if provenance_batch is None:
        return {
            "available": False,
            "error_message": "印刷対象の現行台帳がありません。",
            "sheets": [],
            "sheet_count": 0,
            "prepared_snapshot_id": "",
            "include_memorial_notice_marker": include_memorial_notice_marker,
            "memorial_notice_marker_count": 0,
            "memorial_notice_marker_warning": "",
            "memorial_notice_target_year": date.today().year + 1,
        }

    memorial_notice_target_year = date.today().year + 1
    memorial_notice_target_household_ids: set[str] = set()
    memorial_notice_marker_warning = ""
    if include_memorial_notice_marker:
        memorial_notice_target_household_ids = (
            memorial_notice_runtime._household_ids_with_memorial_notice_targets(
                source_id,
                year=memorial_notice_target_year,
            )
        )

    try:
        districts = list(District.objects.filter(is_active=True).order_by("sort_order", "name"))
        current_households = list(
            Household.objects.select_related("head_person")
            .filter(deleted_at__isnull=True)
            .order_by("household_uid")
        )
        current_people = list(
            Person.objects.select_related("household").filter(
                deleted_at__isnull=True,
                family_category=FAMILY_CATEGORY_CURRENT,
            ).order_by("household__household_uid", "person_uid")
        )
        household_ids = [household.household_uid for household in current_households]
        profile_map = _district_profile_map_for_households(source_id, household_ids)
        states_by_district = {
            state.district_id: state
            for state in DistrictMemberSheetState.objects.filter(
                source__source_id=source_id,
                district__in=districts,
            ).select_related("district")
        }
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "error_message": "地区メンバー一覧のデータ取得に失敗しました。",
            "sheets": [],
            "sheet_count": 0,
            "prepared_snapshot_id": provenance_batch.prepared_snapshot_id,
        }

    members_by_district: dict[int, list[dict]] = {}
    current_households_by_id = {
        household.household_uid: household
        for household in current_households
    }
    district_officer_household_ids = {
        person.household.household_uid
        for person in current_people
        if person.is_district_officer
    }
    current_profile_map = {
        household_id: profile_map[household_id]
        for household_id in profile_map
    }
    for household in current_households:
        profile = profile_map.get(household.household_uid)
        if (
            profile is None
            or profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
            or profile.district_id is None
        ):
            continue
        head_name = _clean_value(household.display_head_name()) or household.household_uid
        head_kana = _clean_value(household.display_head_name_kana())
        is_district_officer = household.household_uid in district_officer_household_ids
        members_by_district.setdefault(profile.district_id, []).append(
            {
                "household_id": household.household_uid,
                "head_person_id": household.head_person.person_uid if household.head_person_id else "",
                "name": head_name,
                "kana": head_kana,
                "display_name": f"{'※' if is_district_officer else ''}{head_name}",
                "is_district_officer": is_district_officer,
                "has_memorial_notice_target": household.household_uid in memorial_notice_target_household_ids,
            }
        )

    for _district_id, rows in members_by_district.items():
        rows.sort(
            key=lambda item: (
                _sort_text(item.get("kana") or item.get("name")),
                _sort_text(item.get("name")),
                _int_sort(item.get("household_id")),
                _int_sort(item.get("person_id")),
            )
        )

    sheets: list[dict] = []
    for district in districts:
        members = members_by_district.get(district.id, [])
        current_snapshot = [
            {
                "household_id": row["household_id"],
                "head_person_id": row["head_person_id"],
                "name": row["name"],
                "kana": row["kana"],
                "is_district_officer": row["is_district_officer"],
            }
            for row in members
        ]
        state = states_by_district.get(district.id)
        previous_snapshot = []
        if state is not None and isinstance(state.last_printed_member_snapshot, list):
            previous_snapshot = state.last_printed_member_snapshot
        sheets.append(
            {
                "district_id": district.id,
                "district_name": district.name,
                "district_short_name": _clean_value(district.short_name) or district.name,
                "members": members,
                "member_count": len(members),
                "manual_note": state.manual_note if state is not None else "",
                "auto_notes": _district_member_auto_notes(
                    district=district,
                    previous_snapshot=previous_snapshot,
                    current_snapshot=current_snapshot,
                    current_households_by_id=current_households_by_id,
                    current_profile_map=current_profile_map,
                ),
                "last_printed_at": state.last_printed_at if state is not None else None,
                "last_printed_prepared_snapshot_id": (
                    state.last_printed_prepared_snapshot_id if state is not None else ""
                ),
                "member_snapshot": current_snapshot,
            }
        )

    return {
        "available": True,
        "error_message": "",
        "sheets": sheets,
        "sheet_count": len(sheets),
        "prepared_snapshot_id": provenance_batch.prepared_snapshot_id,
        "include_memorial_notice_marker": include_memorial_notice_marker,
        "memorial_notice_marker_count": sum(
            1
            for sheet in sheets
            for member in sheet["members"]
            if member.get("has_memorial_notice_target")
        ),
        "memorial_notice_marker_warning": memorial_notice_marker_warning,
        "memorial_notice_target_year": memorial_notice_target_year,
    }
