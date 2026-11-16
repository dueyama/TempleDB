from __future__ import annotations

from apps.imports.models import District, DistrictMemberSheetState, RecordEditLog

from .record_history_mutations import _create_record_edit_log


def serialize_district(district: District) -> dict:
    return {
        "id": district.pk,
        "name": district.name,
        "short_name": district.short_name,
        "sort_order": district.sort_order,
        "is_active": district.is_active,
        "notes": district.notes,
    }


def record_district_change(
    district: District,
    *,
    source_id: str,
    before_data: dict,
    editor_label: str = "system",
    change_note: str = "",
) -> RecordEditLog | None:
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.DISTRICT,
        record=district,
        source_id=source_id,
        record_label=district.name,
        before_data=before_data,
        after_data=serialize_district(district),
        editor_label=(editor_label or "").strip() or "system",
        change_note=change_note,
    )


def serialize_district_member_sheet(state: DistrictMemberSheetState) -> dict:
    district = state.district
    return {
        "id": state.pk,
        "source_id": state.source.source_id,
        "district_id": district.pk,
        "district_name": district.name,
        "district_short_name": district.short_name,
        "district_sort_order": district.sort_order,
        "district_is_active": district.is_active,
        "district_notes": district.notes,
        "manual_note": state.manual_note,
        "last_printed_member_snapshot": state.last_printed_member_snapshot,
        "last_printed_prepared_snapshot_id": state.last_printed_prepared_snapshot_id,
        "last_printed_at": state.last_printed_at,
    }


def record_district_member_sheet_change(
    state: DistrictMemberSheetState,
    *,
    before_data: dict,
    editor_label: str = "system",
    change_note: str = "",
) -> RecordEditLog | None:
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.DISTRICT_MEMBER_SHEET,
        record=state,
        source_id=state.source.source_id,
        record_label=f"{state.district.name} 地区メンバー一覧",
        before_data=before_data,
        after_data=serialize_district_member_sheet(state),
        editor_label=(editor_label or "").strip() or "system",
        change_note=change_note,
    )
