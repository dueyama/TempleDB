from __future__ import annotations

import json
from datetime import date, timedelta

from django.utils import timezone

from apps.core.services import memorial_dates
from apps.imports import (
    browser_dataset,
    canonical_population,
    memorial_notice_runtime,
    service_ledger_runtime,
)
from apps.imports.household_memorial_candidates_runtime import _build_memorial_candidates
from apps.imports.models import ServiceSchedule

from .service_schedule_core import _parse_prefill_date
from .service_schedule_lifecycle import (
    _is_manual_service_schedule,
    _manual_service_schedule_has_blocking_relations,
)

SERVICE_LINK_LOOKBACK_DAYS = 366
SERVICE_LINK_DEFAULT_LOOKBACK_YEARS = 1
SERVICE_LINK_EXTENDED_LOOKBACK_YEARS = 3
SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS = 2
SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS = 10
MANCHUIN_OFFSET_DAYS = 48


def _service_link_candidate_token(candidate: dict) -> str:
    return json.dumps(
        {
            "person_id": candidate.get("person_id", ""),
            "label": candidate.get("label", ""),
            "target_date": candidate.get("target_date", ""),
            "candidate_type": candidate.get("candidate_type", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_service_link_candidate_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        payload = json.loads(token)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "person_id": str(payload.get("person_id", "")),
        "label": str(payload.get("label", "")),
        "target_date": str(payload.get("target_date", "")),
        "candidate_type": str(payload.get("candidate_type", "")),
    }


def _same_person_hatsubon_link_enabled(
    primary_category: str | None,
    primary_service_label: str | None,
) -> bool:
    normalized_category = (primary_category or "").strip()
    normalized_label = (primary_service_label or "").strip()
    if normalized_category not in {
        ServiceSchedule.Category.MEMORIAL,
        ServiceSchedule.Category.CHUIN,
        ServiceSchedule.Category.OTHER,
    }:
        return False
    if not normalized_label or normalized_label == "初盆":
        return False
    if memorial_dates._memorial_offset_years_from_label(normalized_label) is not None:
        return True
    return (
        memorial_dates._kijitsu_offset_days_from_label(normalized_label)
        == MANCHUIN_OFFSET_DAYS
    )


def _candidate_allowed_for_primary_link_scope(
    candidate: dict,
    primary_service_label: str | None,
) -> bool:
    if candidate.get("candidate_type") != "中陰":
        return True
    primary_kijitsu_offset = memorial_dates._kijitsu_offset_days_from_label(
        primary_service_label,
    )
    if primary_kijitsu_offset is None:
        primary_kijitsu_offset = MANCHUIN_OFFSET_DAYS
    return (
        memorial_dates._kijitsu_offset_days_from_label(candidate.get("label"))
        == primary_kijitsu_offset
    )


def _matching_reusable_same_person_hatsubon_schedule(
    candidate: dict,
    schedules: list[ServiceSchedule],
) -> ServiceSchedule | None:
    matching_schedule = service_ledger_runtime._matching_actual_schedule_for_candidate(
        candidate,
        schedules,
    )
    if matching_schedule is None:
        return None
    if not _is_manual_service_schedule(matching_schedule):
        return None
    if matching_schedule.link_group_key:
        return None
    if _manual_service_schedule_has_blocking_relations(matching_schedule):
        return None
    return matching_schedule


def _build_household_service_link_candidates(
    active_source_id: str,
    batch,
    household_id: str,
    *,
    primary_person_id: str,
    primary_target_date: date | None,
    primary_category: str | None = None,
    primary_service_label: str | None = None,
    lookback_years: int = SERVICE_LINK_DEFAULT_LOOKBACK_YEARS,
    lookahead_years: int = SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS,
) -> list[dict]:
    del batch
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if canonical_batch is None:
        return []
    try:
        dataset = browser_dataset._load_household_browser_dataset(
            active_source_id,
            canonical_batch.prepared_snapshot_id or "",
            data_backend="db",
            canonical_population_checked=True,
        )
    except KeyError:
        return []
    detail = dataset["household_details"].get(household_id)
    if detail is None:
        return []
    anchor_date = primary_target_date or date.today()
    today = timezone.localdate()
    resolved_lookback_years = max(int(lookback_years), 0)
    period_start = (
        anchor_date - timedelta(days=SERVICE_LINK_LOOKBACK_DAYS)
        if resolved_lookback_years == SERVICE_LINK_DEFAULT_LOOKBACK_YEARS
        else memorial_dates._replace_year_clamped(
            anchor_date,
            anchor_date.year - resolved_lookback_years,
        )
    )
    period_end = memorial_dates._replace_year_clamped(
        anchor_date,
        anchor_date.year + max(int(lookahead_years), 0),
    )
    memorial_rules = memorial_dates._effective_memorial_rules(dataset.get("memorial_rules", []))
    household_schedule_records = list(
        ServiceSchedule.objects.filter(
            household_uid=household_id,
            deleted_at__isnull=True,
        )
        .select_related("household", "person")
        .order_by("scheduled_date", "scheduled_time", "target_date", "id")
    )
    household_actual_schedule_records = [
        schedule
        for schedule in household_schedule_records
        if service_ledger_runtime._is_actual_service_schedule(schedule)
    ]
    household_schedules = [
        service_ledger_runtime._service_ledger_schedule_entry(
            schedule,
            today=date.today(),
            overdue_period_start=date.today() - timedelta(days=SERVICE_LINK_LOOKBACK_DAYS),
        )
        for schedule in household_actual_schedule_records
    ]
    completed_household_schedules = [
        schedule
        for schedule in household_actual_schedule_records
        if service_ledger_runtime._effective_service_schedule_status(schedule)
        == ServiceSchedule.Status.COMPLETED
    ]
    linked_schedules_by_group: dict[str, list[ServiceSchedule]] = {}
    for schedule in household_actual_schedule_records:
        if schedule.link_group_key:
            linked_schedules_by_group.setdefault(schedule.link_group_key, []).append(schedule)
    candidates = _build_memorial_candidates(
        detail["memorial_members"],
        memorial_rules,
        period_start,
        period_end,
    )
    allow_same_person_hatsubon = _same_person_hatsubon_link_enabled(
        primary_category,
        primary_service_label,
    )
    options: list[dict] = []
    for candidate in candidates:
        if candidate.get("candidate_type") in {"葬儀", "臨終勤行", "通夜", "礼参"}:
            continue
        is_same_person = candidate.get("person_id") == primary_person_id
        if is_same_person and not (
            allow_same_person_hatsubon and candidate.get("candidate_type") == "初盆"
        ):
            continue
        if not _candidate_allowed_for_primary_link_scope(candidate, primary_service_label):
            continue
        candidate_target_date = _parse_prefill_date(candidate.get("target_date"))
        matching_completed_schedule = service_ledger_runtime._matching_actual_schedule_for_candidate(
            candidate,
            completed_household_schedules,
        )
        if matching_completed_schedule is not None:
            token = _service_link_candidate_token(candidate)
            relationship = candidate.get("relationship") or "続柄未設定"
            is_past = candidate_target_date is not None and candidate_target_date < today
            caution_prefix = "【過去】 " if is_past else ""
            completion_note = memorial_notice_runtime._memorial_notice_note(
                matching_completed_schedule,
                candidate_target_date,
                linked_schedules_by_group,
            ).removesuffix("。")
            completion_suffix = (
                f" / {completion_note} / 勤修済み" if completion_note else " / 勤修済み"
            )
            options.append(
                {
                    **candidate,
                    "token": token,
                    "is_past": is_past,
                    "is_selectable": False,
                    "is_completed": True,
                    "existing_schedule_id": str(matching_completed_schedule.pk),
                    "completion_note": completion_note,
                    "display_label": (
                        f"{caution_prefix}{candidate.get('person_name', '')} / "
                        f"{candidate.get('label', '')} / {candidate.get('target_date', '')} / "
                        f"{relationship}{completion_suffix}"
                    ),
                }
            )
            continue
        reusable_schedule = None
        if (
            is_same_person
            and allow_same_person_hatsubon
            and candidate.get("candidate_type") == "初盆"
        ):
            reusable_schedule = _matching_reusable_same_person_hatsubon_schedule(
                candidate,
                household_schedule_records,
            )
        if (
            service_ledger_runtime._candidate_already_has_actual_schedule(
                candidate,
                household_schedules,
            )
            and reusable_schedule is None
        ):
            continue
        token = _service_link_candidate_token(candidate)
        relationship = candidate.get("relationship") or "続柄未設定"
        is_past = candidate_target_date is not None and candidate_target_date < today
        caution_prefix = "【過去】 " if is_past else ""
        existing_schedule_label = (
            reusable_schedule.schedule_uid or str(reusable_schedule.pk)
            if reusable_schedule is not None
            else ""
        )
        existing_schedule_suffix = (
            f" / 既存予定 {existing_schedule_label}" if existing_schedule_label else ""
        )
        options.append(
            {
                **candidate,
                "token": token,
                "is_past": is_past,
                "is_selectable": True,
                "is_completed": False,
                "existing_schedule_id": str(reusable_schedule.pk) if reusable_schedule else "",
                "completion_note": "",
                "display_label": (
                    f"{caution_prefix}{candidate.get('person_name', '')} / {candidate.get('label', '')} / "
                    f"{candidate.get('target_date', '')} / {relationship}"
                    f"{existing_schedule_suffix}"
                ),
            }
        )
    return options


def _selected_service_link_candidates(selected_tokens: list[str], candidates: list[dict]) -> list[dict]:
    selected_keys = {
        (
            parsed.get("person_id", ""),
            parsed.get("label", ""),
            parsed.get("target_date", ""),
            parsed.get("candidate_type", ""),
        )
        for token in selected_tokens
        for parsed in [_parse_service_link_candidate_token(token)]
        if parsed is not None
    }
    return [
        candidate
        for candidate in candidates
        if candidate.get("is_selectable", True)
        if (
            candidate.get("person_id", ""),
            candidate.get("label", ""),
            candidate.get("target_date", ""),
            candidate.get("candidate_type", ""),
        )
        in selected_keys
    ]
