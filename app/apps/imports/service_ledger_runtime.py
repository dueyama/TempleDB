from __future__ import annotations

from .service_ledger_context import (
    _build_service_ledger_event_groups,
    _legacy_build_service_ledger_context,
    build_home_service_schedule_summary,
    build_service_ledger_context,
)
from .service_ledger_entries import (
    _actual_service_schedule_death_date,
    _candidate_already_has_actual_schedule,
    _candidate_can_record_with_funeral,
    _collapse_linked_service_entries,
    _compact_service_label,
    _effective_service_schedule_status,
    _effective_service_schedule_status_label,
    _is_actual_service_schedule,
    _linked_service_entry_master_sort_key,
    _matching_actual_schedule_for_candidate,
    _person_is_service_target,
    _resolved_service_schedule_target_date,
    _service_category_badge_label,
    _service_event_is_actual,
    _service_ledger_candidate_entry,
    _service_ledger_candidate_matches,
    _service_ledger_schedule_entry,
    _service_ledger_schedule_matches,
    _service_row_from_model,
    _service_schedule_category_for_candidate_type,
    _service_target_person_entry,
    _service_target_person_matches,
)
from .service_ledger_sources import (
    _load_household_browser_dataset,
    _load_service_ledger_schedules,
    _load_service_target_people,
    latest_export_snapshot,
    latest_succeeded_import_batch,
    registered_sources,
    resolve_runtime_source_entry,
    source_summary,
)


def _build_memorial_candidates(
    memorial_members: list[dict],
    memorial_rules: list[dict],
    period_start,
    period_end,
) -> list[dict]:
    from . import household_memorial_candidates_runtime

    return household_memorial_candidates_runtime._build_memorial_candidates(
        memorial_members,
        memorial_rules,
        period_start,
        period_end,
    )


def _notice_eligible_memorial_members(detail: dict) -> list[dict]:
    from . import household_memorial_candidates_runtime

    return household_memorial_candidates_runtime._notice_eligible_memorial_members(detail)


__all__ = [
    "_build_memorial_candidates",
    "_notice_eligible_memorial_members",
    "_load_household_browser_dataset",
    "latest_export_snapshot",
    "latest_succeeded_import_batch",
    "registered_sources",
    "resolve_runtime_source_entry",
    "source_summary",
    "build_service_ledger_context",
    "_legacy_build_service_ledger_context",
    "build_home_service_schedule_summary",
    "_load_service_ledger_schedules",
    "_load_service_target_people",
    "_build_service_ledger_event_groups",
    "_service_row_from_model",
    "_actual_service_schedule_death_date",
    "_resolved_service_schedule_target_date",
    "_service_schedule_category_for_candidate_type",
    "_candidate_can_record_with_funeral",
    "_compact_service_label",
    "_service_category_badge_label",
    "_service_ledger_schedule_entry",
    "_collapse_linked_service_entries",
    "_linked_service_entry_master_sort_key",
    "_effective_service_schedule_status",
    "_effective_service_schedule_status_label",
    "_service_event_is_actual",
    "_is_actual_service_schedule",
    "_service_ledger_schedule_matches",
    "_service_ledger_candidate_matches",
    "_matching_actual_schedule_for_candidate",
    "_candidate_already_has_actual_schedule",
    "_service_ledger_candidate_entry",
    "_service_target_person_entry",
    "_person_is_service_target",
    "_service_target_person_matches",
]
