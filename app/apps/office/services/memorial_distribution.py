"""Prepare existing annual notices in the order used to hand them out.

The notice builder owns eligibility, completed-service annotations and the
reference year. District sheets and postal recipients own delivery membership.
This service only joins those existing outputs; it does not save print history.
"""

from __future__ import annotations

from apps.imports import canonical_population
from apps.imports.memorial_notice_context_runtime import build_memorial_notice_context
from apps.imports.models import HOUSEHOLD_DELIVERY_DISTRICT, HOUSEHOLD_DELIVERY_NONE
from apps.imports.postal_recipient_rows import build_postal_recipient_db_rows

from .district_authority import _district_profile_map_for_households
from .district_member_sheets import build_district_member_sheet_context
from .postal_recipient_order import postal_recipient_print_sort_key


def _packet_with_marker(packet: dict, marker: str) -> dict:
    return {
        **packet,
        "documents": [
            {**document, "distribution_marker": marker}
            for document in packet["documents"]
        ],
    }


def _notice_print_items(documents: list[dict]) -> list[dict]:
    return [
        {
            "kind": "notice",
            "document": document,
            "marker": document["distribution_marker"],
        }
        for document in documents
    ]


def _unknown_reason(profile) -> str:
    if profile is None or not profile.delivery_method:
        return "配布方法が未設定です。"
    if profile.delivery_method == HOUSEHOLD_DELIVERY_NONE:
        return "配布方法が「配布なし」です。"
    if profile.delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
        if profile.district_id is None:
            return "地区配布ですが、地区が未設定です。"
        return "地区メンバー一覧・郵送対象と照合できませんでした。"
    return "地区配布・郵送のどちらにも該当しません。"


def build_memorial_distribution_context(
    source_id: str,
    *,
    target_year: int,
    include_reference_year: bool = True,
) -> dict:
    """Return all current district lists and distinct notice delivery groups.

    District lists retain their canonical order even when they have no notices.
    A stopped district belongs to postal delivery under the existing postal
    recipient rules. A residual district reference on an explicitly postal
    profile is not active district delivery. Only an actual overlap between the
    two canonical outputs is a conflict, and conflicted packets are withheld.
    """
    notice_context = build_memorial_notice_context(
        source_id,
        year=target_year,
        include_reference_year=include_reference_year,
    )
    packets_by_id: dict[str, dict] = {}
    for document in notice_context.get("documents", []):
        household_id = str(document["household"]["household_id"])
        packet = packets_by_id.setdefault(
            household_id,
            {
                "household_id": household_id,
                "name": document["recipient_name"],
                "household": document["household"],
                "documents": [],
                "reason": "",
            },
        )
        packet["documents"].append(document)

    result = {
        **notice_context,
        "household_count": len(packets_by_id),
        "district_groups": [],
        "district_count": 0,
        "district_with_notices_count": 0,
        "district_without_notices_count": 0,
        "district_household_count": 0,
        "district_notice_page_count": 0,
        "postal_packets": [],
        "postal_documents": [],
        "postal_household_count": 0,
        "postal_page_count": 0,
        "unknown_packets": [],
        "unknown_documents": [],
        "unknown_household_count": 0,
        "unknown_page_count": 0,
        "conflicts": [],
        "conflict_count": 0,
        "include_memorial_notice_marker": True,
        "memorial_notice_target_year": notice_context["target_year"],
    }
    active_source_id = notice_context.get("selected_source_id") or source_id
    district_context = build_district_member_sheet_context(active_source_id)
    if not district_context["available"]:
        return {
            **result,
            "available": False,
            "message": district_context.get("error_message") or "地区一覧を取得できませんでした。",
        }

    postal_rows = []
    if packets_by_id:
        provenance_batch = canonical_population.canonical_provenance_import_batch(
            source_id=active_source_id,
        )
        postal_rows = build_postal_recipient_db_rows(
            active_source_id,
            provenance_batch,
            canonical_scope=True,
        )
    postal_ids = {str(row["household_id"]) for row in postal_rows}
    district_memberships: dict[str, list[dict]] = {}
    for sheet in district_context["sheets"]:
        for member in sheet["members"]:
            district_memberships.setdefault(str(member["household_id"]), []).append(sheet)

    conflict_ids = {
        household_id
        for household_id, memberships in district_memberships.items()
        if household_id in packets_by_id and (len(memberships) > 1 or household_id in postal_ids)
    }
    for household_id, packet in packets_by_id.items():
        if household_id in conflict_ids:
            result["conflicts"].append(
                {
                    **packet,
                    "reason": (
                        "地区配布と郵送の両方に該当します。配布設定を確認してください。"
                        if household_id in postal_ids
                        else "複数の地区一覧に該当します。配布設定を確認してください。"
                    ),
                }
            )

    assigned_ids = set(conflict_ids)
    for original_sheet in district_context["sheets"]:
        member_ids = [str(member["household_id"]) for member in original_sheet["members"]]
        selected_ids = [
            household_id
            for household_id in member_ids
            if household_id in packets_by_id and household_id not in assigned_ids
        ]
        packets = [
            _packet_with_marker(packets_by_id[household_id], original_sheet["district_name"])
            for household_id in selected_ids
        ]
        selected_id_set = set(selected_ids)
        sheet = {
            **original_sheet,
            "members": [
                {
                    **member,
                    "has_memorial_notice_target": str(member["household_id"]) in selected_id_set,
                }
                for member in original_sheet["members"]
            ],
        }
        documents = [document for packet in packets for document in packet["documents"]]
        result["district_groups"].append(
            {
                "district_id": sheet["district_id"],
                "district_name": sheet["district_name"],
                "sheet": sheet,
                "packets": packets,
                "documents": documents,
                "household_count": len(packets),
                "page_count": len(documents),
                "print_items": [{"kind": "district", "sheet": sheet}, *_notice_print_items(documents)],
            }
        )
        assigned_ids.update(selected_ids)

    # Apply the label order before selecting notice targets; keep each home's pages together.
    for row in sorted(postal_rows, key=postal_recipient_print_sort_key):
        household_id = str(row["household_id"])
        if household_id in packets_by_id and household_id not in assigned_ids:
            result["postal_packets"].append(_packet_with_marker(packets_by_id[household_id], "○"))
            assigned_ids.add(household_id)

    unassigned_ids = [household_id for household_id in packets_by_id if household_id not in assigned_ids]
    profiles = _district_profile_map_for_households(active_source_id, unassigned_ids)
    result["unknown_packets"] = [
        {
            **_packet_with_marker(packets_by_id[household_id], ""),
            "reason": _unknown_reason(profiles.get(household_id)),
        }
        for household_id in unassigned_ids
    ]
    for category in ("postal", "unknown"):
        packets = result[f"{category}_packets"]
        documents = [document for packet in packets for document in packet["documents"]]
        result[f"{category}_documents"] = documents
        result[f"{category}_household_count"] = len(packets)
        result[f"{category}_page_count"] = len(documents)

    result["district_count"] = len(result["district_groups"])
    result["district_without_notices_count"] = sum(
        group["household_count"] == 0 for group in result["district_groups"]
    )
    result["district_with_notices_count"] = result["district_count"] - result["district_without_notices_count"]
    result["district_household_count"] = sum(group["household_count"] for group in result["district_groups"])
    result["district_notice_page_count"] = sum(group["page_count"] for group in result["district_groups"])
    result["conflict_count"] = len(result["conflicts"])
    result["available"] = bool(result["district_groups"] or packets_by_id)
    if result["available"]:
        result["message"] = ""
    return result
