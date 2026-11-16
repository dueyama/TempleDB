from __future__ import annotations

from . import (
    browser_dataset,
    household_browser_detail_context,
    household_browser_detail_fields,
    household_browser_detail_status,
    runtime_shared,
)
from .household_browser_dataset_runtime import (
    _load_household_browser_summary_dataset as _load_household_browser_summary_dataset,
)
from .household_browser_runtime_shared import (
    latest_export_snapshot as latest_export_snapshot,
)
from .household_browser_runtime_shared import (
    latest_import_batch_summary as latest_import_batch_summary,
)
from .household_browser_runtime_shared import (
    registered_sources as registered_sources,
)
from .household_browser_runtime_shared import (
    resolve_runtime_source_entry as resolve_runtime_source_entry,
)
from .household_browser_runtime_shared import (
    source_summary as source_summary,
)

HOUSEHOLD_KANA_GROUP_KEYS = runtime_shared.HOUSEHOLD_KANA_GROUP_KEYS
HOUSEHOLD_KANA_GROUP_LABELS = runtime_shared.HOUSEHOLD_KANA_GROUP_LABELS


def _build_household_group_buttons(
    households: list[dict],
    filtered_households: list[dict],
    selected_group_key: str,
) -> list[dict]:
    return browser_dataset._build_household_group_buttons(
        households,
        filtered_households,
        selected_group_key,
    )


def _filter_households(
    households: list[dict],
    query: str,
    kana_group: str = "all",
    *,
    household_details: dict[str, dict] | None = None,
    memorial_search_index: dict[str, tuple[str, ...]] | None = None,
    include_memorial_search: bool = False,
) -> list[dict]:
    return browser_dataset._filter_households(
        households,
        query,
        kana_group,
        household_details=household_details,
        memorial_search_index=memorial_search_index,
        include_memorial_search=include_memorial_search,
    )


def _household_browser_household_fields(
    source_id: str,
    household_id: str,
    base_fields: list[dict],
    head_person_fields: list[dict],
) -> list[dict]:
    return household_browser_detail_fields._household_browser_household_fields(
        source_id,
        household_id,
        base_fields,
        head_person_fields,
    )


def _household_browser_postal_delivery_summary(
    source_id: str,
    household_id: str,
    base_fields: list[dict],
    head_person_fields: list[dict],
    current_members: list[dict],
) -> dict | None:
    return household_browser_detail_fields._household_browser_postal_delivery_summary(
        source_id,
        household_id,
        base_fields,
        head_person_fields,
        current_members,
    )


def _household_head_ledger_status(
    household_name: str,
    head_person_fields: list[dict],
    current_members: list[dict],
    memorial_members: list[dict],
) -> dict:
    return household_browser_detail_status._household_head_ledger_status(
        household_name,
        head_person_fields,
        current_members,
        memorial_members,
    )


def _exclude_head_person_from_member_list(members: list[dict], head_person_id: str | None) -> list[dict]:
    return household_browser_detail_status._exclude_head_person_from_member_list(
        members,
        head_person_id,
    )


def _normalize_head_status_name(value: str | None) -> str:
    return household_browser_detail_status._normalize_head_status_name(value)


def _household_browser_extinct_action(
    *,
    household_name: str,
    head_person_fields: list[dict],
    current_members: list[dict],
    head_ledger_status: dict,
) -> dict[str, object]:
    return household_browser_detail_status._household_browser_extinct_action(
        household_name=household_name,
        head_person_fields=head_person_fields,
        current_members=current_members,
        head_ledger_status=head_ledger_status,
    )


def _load_household_browser_context_dataset(source_id: str, snapshot_id: str) -> dict:
    return household_browser_detail_context._load_household_browser_context_dataset(
        source_id,
        snapshot_id,
    )


def _legacy_build_household_browser_context(
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
    return household_browser_detail_context._legacy_build_household_browser_context(
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


__all__ = [
    "_build_household_group_buttons",
    "_exclude_head_person_from_member_list",
    "_filter_households",
    "_household_browser_extinct_action",
    "_household_browser_household_fields",
    "_load_household_browser_context_dataset",
    "_household_browser_postal_delivery_summary",
    "_household_head_ledger_status",
    "_legacy_build_household_browser_context",
    "_normalize_head_status_name",
]
