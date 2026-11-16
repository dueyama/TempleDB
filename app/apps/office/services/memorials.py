from __future__ import annotations

from apps.imports import memorial_notice_runtime, memorial_sheet_runtime, service_ledger_runtime


def build_memorial_notice_context(*args, **kwargs):
    return memorial_notice_runtime.build_memorial_notice_context(*args, **kwargs)


def build_memorial_sheet_context(*args, **kwargs):
    return memorial_sheet_runtime.build_memorial_sheet_context(*args, **kwargs)


def build_household_memorial_list_context(*args, **kwargs):
    return memorial_sheet_runtime.build_household_memorial_list_context(*args, **kwargs)


def build_service_ledger_context(*args, **kwargs):
    return service_ledger_runtime.build_service_ledger_context(*args, **kwargs)


def build_home_service_schedule_summary(*args, **kwargs):
    return service_ledger_runtime.build_home_service_schedule_summary(*args, **kwargs)


def _actual_service_schedule_death_date(schedule):
    return service_ledger_runtime._actual_service_schedule_death_date(schedule)


def _resolved_service_schedule_target_date(schedule):
    return service_ledger_runtime._resolved_service_schedule_target_date(schedule)


def _is_actual_service_schedule(schedule):
    return service_ledger_runtime._is_actual_service_schedule(schedule)


def _matching_actual_schedule_for_candidate(candidate, schedules):
    return service_ledger_runtime._matching_actual_schedule_for_candidate(candidate, schedules)


def _candidate_can_record_with_funeral(candidate_type, service_label=None):
    return service_ledger_runtime._candidate_can_record_with_funeral(candidate_type, service_label)


def _service_schedule_category_for_candidate_type(candidate_type, service_label=None):
    return service_ledger_runtime._service_schedule_category_for_candidate_type(
        candidate_type,
        service_label,
    )


def _compact_service_label(service_label):
    return service_ledger_runtime._compact_service_label(service_label)
