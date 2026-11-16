from __future__ import annotations

import hashlib

from . import runtime_shared


def _same_name_member_identity(member: dict) -> tuple[str, str, str]:
    return (
        str(member.get("household_id", "")),
        str(member.get("person_id", "")),
        str(member.get("member_type", "")),
    )


def _same_name_kaimyo_key(value: str | None) -> str:
    return runtime_shared._normalize_same_name_text(value)


def _same_name_disambiguator_count(member: dict) -> int:
    return int(bool(member.get("death_date"))) + int(bool(_same_name_kaimyo_key(member.get("kaimyo"))))


def _same_name_cluster_sort_key(member: dict) -> tuple[int, int, str, str, int]:
    return (
        -_same_name_disambiguator_count(member),
        0 if member.get("death_date") else 1,
        runtime_shared._sort_date(member.get("death_date")),
        runtime_shared._sort_text(member.get("kaimyo")),
        runtime_shared._int_sort(member.get("person_id")),
    )


def _same_name_cluster_can_accept(cluster: dict, member: dict) -> bool:
    death_date = member.get("death_date", "")
    kaimyo_key = _same_name_kaimyo_key(member.get("kaimyo"))
    if death_date and cluster["death_dates"] and death_date not in cluster["death_dates"]:
        return False
    if kaimyo_key and cluster["kaimyo_keys"] and kaimyo_key not in cluster["kaimyo_keys"]:
        return False
    return True


def _append_same_name_cluster_member(cluster: dict, member: dict) -> None:
    cluster["members"].append(member)
    death_date = member.get("death_date", "")
    kaimyo_key = _same_name_kaimyo_key(member.get("kaimyo"))
    if death_date:
        cluster["death_dates"].add(death_date)
    if kaimyo_key:
        cluster["kaimyo_keys"].add(kaimyo_key)


def _split_same_name_group_members(group_members: list[dict]) -> list[list[dict]]:
    clusters: list[dict] = []
    for member in sorted(group_members, key=_same_name_cluster_sort_key):
        matching_clusters = [cluster for cluster in clusters if _same_name_cluster_can_accept(cluster, member)]
        if len(matching_clusters) == 1:
            _append_same_name_cluster_member(matching_clusters[0], member)
            continue
        if not matching_clusters:
            new_cluster = {"members": [], "death_dates": set(), "kaimyo_keys": set()}
            _append_same_name_cluster_member(new_cluster, member)
            clusters.append(new_cluster)
            continue
        # Records with no distinguishing fields should not bridge multiple conflicting groups.
    return [cluster["members"] for cluster in clusters]


def _build_same_name_groups(members: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for member in members:
        same_name_key = member.get("same_name_key", "")
        if not same_name_key:
            continue
        grouped.setdefault(same_name_key, []).append(
            {
                "person_id": member.get("person_id", ""),
                "household_id": member.get("household_id", ""),
                "household_name": member.get("household_name", ""),
                "name": member.get("name", ""),
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "member_type": member.get("member_type", ""),
                "member_type_label": member.get("member_type_label", ""),
                "death_date": member.get("death_date", ""),
                "kaimyo": member.get("kaimyo", ""),
                "note": member.get("note", ""),
            }
        )

    same_name_groups = {}
    for same_name_key, group_members in grouped.items():
        if len(group_members) < 2:
            continue
        split_groups = [
            split_members for split_members in _split_same_name_group_members(group_members) if len(split_members) >= 2
        ]
        for index, split_members in enumerate(split_groups):
            sorted_members = sorted(
                split_members,
                key=lambda item: (
                    1 if not item.get("death_date") else 0,
                    runtime_shared._sort_date(item.get("death_date")),
                    runtime_shared._sort_text(item.get("household_name")),
                    runtime_shared._sort_text(item.get("relationship")),
                    runtime_shared._int_sort(item.get("household_id")),
                    runtime_shared._int_sort(item.get("person_id")),
                ),
            )
            display_name = next((item["name"] for item in sorted_members if item.get("name")), same_name_key)
            group_key = same_name_key if len(split_groups) == 1 else f"{same_name_key}::{index}"
            group_id_seed = same_name_key if len(split_groups) == 1 else f"{same_name_key}:{index}"
            group_id = f"same-name-{hashlib.sha1(group_id_seed.encode('utf-8')).hexdigest()[:10]}"
            same_name_groups[group_key] = {
                "group_id": group_id,
                "same_name_key": same_name_key,
                "display_name": display_name,
                "count": len(sorted_members),
                "household_count": len({item["household_id"] for item in sorted_members}),
                "members": sorted_members,
            }
    return same_name_groups


def _attach_same_name_metadata(members: list[dict], same_name_groups: dict[str, dict]) -> list[dict]:
    group_by_member_identity = {
        _same_name_member_identity(candidate): group
        for group in same_name_groups.values()
        for candidate in group["members"]
    }
    annotated = []
    for member in members:
        group = group_by_member_identity.get(_same_name_member_identity(member))
        annotated.append(
            {
                **member,
                "same_name_group_id": group["group_id"] if group else "",
                "same_name_group_size": group["count"] if group else 1,
                "same_name_other_count": max((group["count"] - 1), 0) if group else 0,
            }
        )
    return annotated


def _household_same_name_groups(
    members: list[dict],
    same_name_groups: dict[str, dict],
    selected_household_id: str,
) -> list[dict]:
    member_identities = {_same_name_member_identity(member) for member in members}
    groups = []
    matching_groups = [
        group
        for group in same_name_groups.values()
        if any(_same_name_member_identity(candidate) in member_identities for candidate in group["members"])
    ]
    for group in sorted(
        matching_groups,
        key=lambda item: (
            runtime_shared._sort_text(item.get("display_name")),
            item.get("group_id", ""),
        ),
    ):
        groups.append(
            {
                **group,
                "members": [
                    {
                        **candidate,
                        "is_selected_household": candidate["household_id"] == selected_household_id,
                    }
                    for candidate in group["members"]
                ],
            }
        )
    return groups
