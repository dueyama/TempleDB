from __future__ import annotations

from . import runtime_shared


def _filter_households(
    households: list[dict],
    query: str,
    kana_group: str = "all",
    *,
    household_details: dict[str, dict] | None = None,
    memorial_search_index: dict[str, tuple[str, ...]] | None = None,
    include_memorial_search: bool = False,
) -> list[dict]:
    needle = runtime_shared._search_text(query)
    effective_kana_group = kana_group if not needle else "all"
    if not needle:
        if kana_group == "all":
            return households
        return [row for row in households if row.get("browse_group_key") == kana_group]

    filtered = []
    for row in households:
        if effective_kana_group != "all" and row.get("browse_group_key") != effective_kana_group:
            continue
        haystacks = (
            row["household_id"],
            row["name"],
            row["kana"],
            row["address"],
            row["phone"],
            *row.get("search_aliases", []),
        )
        if any(needle in runtime_shared._search_text(value) for value in haystacks):
            filtered.append(row)
            continue
        if not include_memorial_search:
            continue
        if memorial_search_index is not None and any(
            needle in runtime_shared._search_text(value)
            for value in memorial_search_index.get(row["household_id"], ())
        ):
            filtered.append(row)
            continue
        if household_details is None:
            continue
        detail = household_details.get(row["household_id"], {})
        members = [*detail.get("current_members", []), *detail.get("memorial_members", [])]
        if any(
            needle in runtime_shared._search_text(value)
            for member in members
            for value in (
                member.get("person_id"),
                member.get("name"),
                member.get("kana"),
                member.get("relationship"),
                member.get("kaimyo"),
                member.get("death_date"),
            )
        ):
            filtered.append(row)
    return filtered


def _build_household_group_buttons(
    households: list[dict],
    filtered_households: list[dict],
    selected_group_key: str,
) -> list[dict]:
    total_counts = {key: 0 for key in runtime_shared.HOUSEHOLD_KANA_GROUP_KEYS}
    match_counts = {key: 0 for key in runtime_shared.HOUSEHOLD_KANA_GROUP_KEYS}
    total_counts["all"] = len(households)
    match_counts["all"] = len(filtered_households)
    filtered_ids = {row["household_id"] for row in filtered_households}
    for row in households:
        group_key = row.get("browse_group_key", "other")
        total_counts[group_key] = total_counts.get(group_key, 0) + 1
        if row["household_id"] in filtered_ids:
            match_counts[group_key] = match_counts.get(group_key, 0) + 1

    return [
        {
            **group,
            "count": total_counts.get(group["key"], 0),
            "match_count": match_counts.get(group["key"], 0),
            "selected": group["key"] == selected_group_key,
        }
        for group in runtime_shared.HOUSEHOLD_KANA_GROUPS
    ]
