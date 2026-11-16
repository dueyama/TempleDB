from __future__ import annotations

from .models import Household


def _office_module():
    from apps.office.services import district_member_sheets

    return district_member_sheets


def _district_member_sheet_snapshot(*, household: Household, is_district_officer: bool) -> dict:
    return _office_module()._district_member_sheet_snapshot(
        household=household,
        is_district_officer=is_district_officer,
    )


def _district_member_sheet_label(snapshot: dict) -> str:
    return _office_module()._district_member_sheet_label(snapshot)


def _district_member_removed_reason(
    *,
    district,
    snapshot: dict,
    current_households_by_id: dict[str, object],
    current_profile_map: dict[str, object],
) -> str:
    return _office_module()._district_member_removed_reason(
        district=district,
        snapshot=snapshot,
        current_households_by_id=current_households_by_id,
        current_profile_map=current_profile_map,
    )


def _district_member_auto_notes(
    *,
    district,
    previous_snapshot: list[dict],
    current_snapshot: list[dict],
    current_households_by_id: dict[str, object],
    current_profile_map: dict[str, object],
) -> list[str]:
    return _office_module()._district_member_auto_notes(
        district=district,
        previous_snapshot=previous_snapshot,
        current_snapshot=current_snapshot,
        current_households_by_id=current_households_by_id,
        current_profile_map=current_profile_map,
    )


def build_district_member_sheet_context(
    source_id: str,
    *,
    include_memorial_notice_marker: bool = False,
) -> dict:
    return _office_module().build_district_member_sheet_context(
        source_id,
        include_memorial_notice_marker=include_memorial_notice_marker,
    )


__all__ = [
    "_district_member_sheet_snapshot",
    "_district_member_sheet_label",
    "_district_member_removed_reason",
    "_district_member_auto_notes",
    "build_district_member_sheet_context",
]
