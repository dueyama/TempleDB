from __future__ import annotations


def build_household_browser_context(
    source_id: str | None = None,
    query: str = "",
    household_id: str | None = None,
    candidate_from: str | None = None,
    candidate_to: str | None = None,
    kana_group: str | None = None,
    data_backend: str = "db",
    include_memorial_search: bool = False,
    auto_select_first: bool = True,
) -> dict:
    from . import household_browser_detail_runtime

    return household_browser_detail_runtime._legacy_build_household_browser_context(
        source_id=source_id,
        query=query,
        household_id=household_id,
        candidate_from=candidate_from,
        candidate_to=candidate_to,
        kana_group=kana_group,
        data_backend=data_backend,
        include_memorial_search=include_memorial_search,
        auto_select_first=auto_select_first,
    )
