from __future__ import annotations

from . import canonical_population
from .quality_runtime_shared import (
    _homyo_order_issue,
    _member_field_value,
    _normalize_gender,
)
from .runtime_shared import _int_sort, _search_text, _sort_text


def _runtime_module():
    from . import data_quality_runtime

    return data_quality_runtime


def build_data_quality_context(
    source_id: str | None = None,
    query: str = "",
    data_backend: str = "db",
) -> dict:
    return _legacy_build_data_quality_context(
        source_id=source_id,
        query=query,
        data_backend=data_backend,
    )


def _legacy_build_data_quality_context(
    source_id: str | None = None,
    query: str = "",
    data_backend: str = "db",
) -> dict:
    del source_id, data_backend
    runtime = _runtime_module()
    source = runtime.resolve_runtime_source_entry()
    active_source_id = source["source_id"]
    latest_export = runtime.latest_export_snapshot(active_source_id)
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    snapshot_id = canonical_batch.prepared_snapshot_id if canonical_batch is not None else ""
    dataset = runtime._load_household_browser_dataset(active_source_id, snapshot_id)
    same_name_groups = runtime._decorate_same_name_groups(dataset)
    missing_death_date_members = sorted(
        (
            {
                "person_id": member["person_id"],
                "household_id": member["household_id"],
                "household_name": member.get("household_name", ""),
                "name": member["name"],
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "member_type_label": member.get("member_type_label", ""),
                "kaimyo": member.get("kaimyo", ""),
                "note": member.get("note", ""),
            }
            for detail in dataset["household_details"].values()
            for member in detail["memorial_members"]
            if not member.get("death_date")
        ),
        key=lambda item: (
            _sort_text(item["name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )
    unknown_gender_members = sorted(
        (
            {
                "person_id": member["person_id"],
                "household_id": member["household_id"],
                "household_name": member.get("household_name", ""),
                "name": member["name"],
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "member_type_label": member.get("member_type_label", ""),
                "gender": _normalize_gender(_member_field_value(member, "性別")),
                "raw_gender": _member_field_value(member, "性別"),
                "kaimyo": member.get("kaimyo", ""),
                "death_date": member.get("death_date", ""),
                "note": member.get("note", ""),
            }
            for detail in dataset["household_details"].values()
            for member in (detail["current_members"] + detail["memorial_members"])
            if _normalize_gender(_member_field_value(member, "性別")) == "不明"
        ),
        key=lambda item: (
            _sort_text(item["name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )
    address_line2_overlap_households = runtime._address_line2_duplicate_candidates(active_source_id)
    homyo_order_issue_members = sorted(
        (
            issue
            for detail in dataset["household_details"].values()
            for member in detail["memorial_members"]
            if (issue := _homyo_order_issue(member)) is not None
        ),
        key=lambda item: (
            _sort_text(item["kaimyo"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )
    import_issue_breakdown = runtime.latest_import_issue_breakdown(active_source_id)
    if query:
        needle = _search_text(query)
        same_name_groups = [
            group
            for group in same_name_groups
            if needle in _search_text(group["display_name"])
            or any(
                needle in _search_text(value)
                for member in group["members"]
                for value in (
                    member.get("household_name"),
                    member.get("relationship"),
                    member.get("household_role_label"),
                    member.get("household_member_summary"),
                    member.get("current_member_names_preview"),
                    member.get("memorial_member_names_preview"),
                    member.get("death_date"),
                    member.get("kaimyo"),
                    member.get("note"),
                )
            )
            or any(
                needle in _search_text(value)
                for household in group.get("households", [])
                for value in (
                    household.get("household_name"),
                    household.get("head_name"),
                    household.get("address"),
                    household.get("phone"),
                    household.get("delivery_label"),
                    household.get("yuen_label"),
                    household.get("household_member_summary"),
                    household.get("matching_members_preview"),
                    household.get("current_member_names_preview"),
                    household.get("memorial_member_names_preview"),
                    household.get("event_summary"),
                    household.get("household_id"),
                )
            )
        ]
        missing_death_date_members = [
            member
            for member in missing_death_date_members
            if any(
                needle in _search_text(value)
                for value in (
                    member.get("name"),
                    member.get("household_name"),
                    member.get("relationship"),
                    member.get("kaimyo"),
                    member.get("note"),
                    member.get("household_id"),
                    member.get("person_id"),
                )
            )
        ]
        unknown_gender_members = [
            member
            for member in unknown_gender_members
            if any(
                needle in _search_text(value)
                for value in (
                    member.get("name"),
                    member.get("household_name"),
                    member.get("relationship"),
                    member.get("member_type_label"),
                    member.get("raw_gender"),
                    member.get("kaimyo"),
                    member.get("death_date"),
                    member.get("note"),
                    member.get("household_id"),
                    member.get("person_id"),
                )
            )
        ]
        address_line2_overlap_households = [
            household
            for household in address_line2_overlap_households
            if any(
                needle in _search_text(value)
                for value in (
                    household.get("household_name"),
                    household.get("address_line1"),
                    household.get("address_line2"),
                    household.get("overlap_text"),
                    household.get("household_id"),
                )
            )
        ]
        homyo_order_issue_members = [
            member
            for member in homyo_order_issue_members
            if any(
                needle in _search_text(value)
                for value in (
                    member.get("name"),
                    member.get("household_name"),
                    member.get("relationship"),
                    member.get("kaimyo"),
                    member.get("suggested_kaimyo"),
                    member.get("ingo"),
                    member.get("homyo"),
                    member.get("household_id"),
                    member.get("person_id"),
                )
            )
        ]

    return {
        "available": True,
        "selected_source_id": active_source_id,
        "registered_sources": runtime.registered_sources(active_source_id),
        "source": runtime.source_summary(active_source_id),
        "latest_export": latest_export,
        "canonical_batch": canonical_batch,
        "canonical_snapshot_id": snapshot_id,
        "query": query,
        "data_backend": dataset["data_backend"],
        "same_name_groups": same_name_groups,
        "same_name_group_count": len(same_name_groups),
        "missing_death_date_members": missing_death_date_members,
        "missing_death_date_count": len(missing_death_date_members),
        "unknown_gender_members": unknown_gender_members,
        "unknown_gender_count": len(unknown_gender_members),
        "address_line2_overlap_households": address_line2_overlap_households,
        "address_line2_overlap_count": len(address_line2_overlap_households),
        "homyo_order_issue_members": homyo_order_issue_members,
        "homyo_order_issue_count": len(homyo_order_issue_members),
        "import_issue_breakdown": import_issue_breakdown,
        "import_issue_total": sum(row["count"] for row in import_issue_breakdown),
        "memorial_member_total": sum(
            detail["summary"]["memorial_count"] for detail in dataset["household_details"].values()
        ),
    }
