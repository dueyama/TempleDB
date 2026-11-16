from __future__ import annotations

from . import (
    browser_dataset_display,
    browser_dataset_same_name,
    memorial_shared,
    runtime_shared,
)
from .browser_dataset_builders import (
    _attach_same_name_metadata,
    _build_household_browser_dataset_from_rows,
    _build_household_browser_detail_from_summary_dataset,
    _build_household_browser_summary_dataset_from_rows,
    _build_household_group_buttons,
    _build_same_name_groups,
    _filter_households,
    _household_same_name_groups,
)
from .browser_dataset_loaders import (
    _empty_household_browser_dataset,
    _load_household_browser_dataset,
    _load_household_browser_dataset_from_sqlite,
)
from .browser_dataset_rows import (
    _event_summary,
    _household_row_from_model,
    _household_summary_sort_key,
    _is_memorial_person,
    _is_placeholder_person_row,
    _is_yuen_household_row,
    _member_type_labels,
    _person_row_from_model,
    _person_summary,
    _same_name_source_member_summary,
    _sort_memorial_members,
    _sorted_household_person_rows,
)

HOUSEHOLD_KANA_GROUP_LABELS = runtime_shared.HOUSEHOLD_KANA_GROUP_LABELS
HOUSEHOLD_KANA_GROUPS = runtime_shared.HOUSEHOLD_KANA_GROUPS
HOUSEHOLD_KANA_GROUP_KEYS = runtime_shared.HOUSEHOLD_KANA_GROUP_KEYS
MEMORIAL_RANKS = memorial_shared.MEMORIAL_RANKS
_clean_value = runtime_shared._clean_value
_normalize_household_browse_text = runtime_shared._normalize_household_browse_text
_display_pairs = browser_dataset_display._display_pairs
_non_empty_pairs = browser_dataset_display._non_empty_pairs
_display_column_value = browser_dataset_display._display_column_value
_display_column_label = browser_dataset_display._display_column_label
_same_name_household_delivery_label = browser_dataset_display._same_name_household_delivery_label
_same_name_household_yuen_label = browser_dataset_display._same_name_household_yuen_label
_same_name_member_identity = browser_dataset_same_name._same_name_member_identity
_same_name_kaimyo_key = browser_dataset_same_name._same_name_kaimyo_key
_same_name_disambiguator_count = browser_dataset_same_name._same_name_disambiguator_count
_same_name_cluster_sort_key = browser_dataset_same_name._same_name_cluster_sort_key
_same_name_cluster_can_accept = browser_dataset_same_name._same_name_cluster_can_accept
_append_same_name_cluster_member = browser_dataset_same_name._append_same_name_cluster_member
_split_same_name_group_members = browser_dataset_same_name._split_same_name_group_members

__all__ = [
    "HOUSEHOLD_KANA_GROUP_LABELS",
    "HOUSEHOLD_KANA_GROUPS",
    "HOUSEHOLD_KANA_GROUP_KEYS",
    "MEMORIAL_RANKS",
    "_clean_value",
    "_normalize_household_browse_text",
    "_display_pairs",
    "_non_empty_pairs",
    "_display_column_value",
    "_display_column_label",
    "_same_name_household_delivery_label",
    "_same_name_household_yuen_label",
    "_same_name_member_identity",
    "_same_name_kaimyo_key",
    "_same_name_disambiguator_count",
    "_same_name_cluster_sort_key",
    "_same_name_cluster_can_accept",
    "_append_same_name_cluster_member",
    "_split_same_name_group_members",
    "_build_same_name_groups",
    "_attach_same_name_metadata",
    "_household_same_name_groups",
    "_empty_household_browser_dataset",
    "_load_household_browser_dataset",
    "_load_household_browser_dataset_from_sqlite",
    "_filter_households",
    "_build_household_group_buttons",
    "_sorted_household_person_rows",
    "_is_yuen_household_row",
    "_household_summary_sort_key",
    "_member_type_labels",
    "_same_name_source_member_summary",
    "_build_household_browser_summary_dataset_from_rows",
    "_build_household_browser_detail_from_summary_dataset",
    "_build_household_browser_dataset_from_rows",
    "_household_row_from_model",
    "_person_row_from_model",
    "_event_summary",
    "_sort_memorial_members",
    "_person_summary",
    "_is_placeholder_person_row",
    "_is_memorial_person",
]
