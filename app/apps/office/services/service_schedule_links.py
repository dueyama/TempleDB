from __future__ import annotations

from . import (
    service_schedule_link_candidates,
    service_schedule_link_creation,
    service_schedule_link_groups,
)

SERVICE_LINK_LOOKBACK_DAYS = service_schedule_link_candidates.SERVICE_LINK_LOOKBACK_DAYS
SERVICE_LINK_DEFAULT_LOOKBACK_YEARS = (
    service_schedule_link_candidates.SERVICE_LINK_DEFAULT_LOOKBACK_YEARS
)
SERVICE_LINK_EXTENDED_LOOKBACK_YEARS = (
    service_schedule_link_candidates.SERVICE_LINK_EXTENDED_LOOKBACK_YEARS
)
SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS = (
    service_schedule_link_candidates.SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS
)
SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS = (
    service_schedule_link_candidates.SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS
)
LINKED_GROUP_SHARED_FIELDS = service_schedule_link_groups.LINKED_GROUP_SHARED_FIELDS


def _new_service_link_group_key() -> str:
    return service_schedule_link_creation._new_service_link_group_key()


def _service_link_candidate_token(candidate: dict) -> str:
    return service_schedule_link_candidates._service_link_candidate_token(candidate)


def _parse_service_link_candidate_token(token: str) -> dict | None:
    return service_schedule_link_candidates._parse_service_link_candidate_token(token)


def _same_person_hatsubon_link_enabled(
    primary_category: str | None,
    primary_service_label: str | None,
) -> bool:
    return service_schedule_link_candidates._same_person_hatsubon_link_enabled(
        primary_category,
        primary_service_label,
    )


def _build_household_service_link_candidates(
    active_source_id: str,
    batch,
    household_id: str,
    *,
    primary_person_id: str,
    primary_target_date,
    primary_category: str | None = None,
    primary_service_label: str | None = None,
    lookback_years: int = SERVICE_LINK_DEFAULT_LOOKBACK_YEARS,
    lookahead_years: int = SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS,
) -> list[dict]:
    return service_schedule_link_candidates._build_household_service_link_candidates(
        active_source_id,
        batch,
        household_id,
        primary_person_id=primary_person_id,
        primary_target_date=primary_target_date,
        primary_category=primary_category,
        primary_service_label=primary_service_label,
        lookback_years=lookback_years,
        lookahead_years=lookahead_years,
    )


def _selected_service_link_candidates(selected_tokens: list[str], candidates: list[dict]) -> list[dict]:
    return service_schedule_link_candidates._selected_service_link_candidates(selected_tokens, candidates)


def _create_linked_service_schedules(
    *,
    batch,
    source_id: str,
    base_schedule,
    selected_candidates: list[dict],
    editor_label: str,
    change_note: str,
    previous_sync_keys: list[str] | None = None,
):
    return service_schedule_link_creation._create_linked_service_schedules(
        batch=batch,
        source_id=source_id,
        base_schedule=base_schedule,
        selected_candidates=selected_candidates,
        editor_label=editor_label,
        change_note=change_note,
        previous_sync_keys=previous_sync_keys,
    )


def _apply_linked_schedule_values(
    *,
    linked_schedule,
    base_schedule,
    person,
    candidate: dict,
) -> None:
    return service_schedule_link_creation._apply_linked_schedule_values(
        linked_schedule=linked_schedule,
        base_schedule=base_schedule,
        person=person,
        candidate=candidate,
    )


def _find_reusable_linked_schedule(
    *,
    batch,
    base_schedule,
    person,
    candidate: dict,
):
    return service_schedule_link_creation._find_reusable_linked_schedule(
        batch=batch,
        base_schedule=base_schedule,
        person=person,
        candidate=candidate,
    )


def _linked_service_schedule_members(schedule) -> list[dict]:
    return service_schedule_link_groups._linked_service_schedule_members(schedule)


def _linked_service_schedule_choices(schedule) -> tuple[list[tuple[str, str]], list[str]]:
    return service_schedule_link_groups._linked_service_schedule_choices(schedule)


def _apply_linked_group_updates(
    schedule,
    *,
    apply_updates: bool,
    editor_label: str,
    change_note: str,
):
    return service_schedule_link_groups._apply_linked_group_updates(
        schedule,
        apply_updates=apply_updates,
        editor_label=editor_label,
        change_note=change_note,
    )
