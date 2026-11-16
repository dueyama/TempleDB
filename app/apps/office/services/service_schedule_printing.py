from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.services import memorial_dates
from apps.core.services import temple_identity as temple_identity_services
from apps.imports import (
    memorial_notice_columns,
    runtime_shared,
    service_ledger_runtime,
)
from apps.imports.household_memorial_candidates_runtime import _build_memorial_candidates
from apps.imports.models import Person, ServiceSchedule, VisitNote

from .household_editing_core import _household_display_head_name


def _service_schedule_print_url(
    schedule: ServiceSchedule,
    *,
    source_id: str,
    next_url: str,
    source_table: str = "",
) -> str:
    del source_id
    query = {"next": next_url}
    resolved_source_table = source_table or schedule.source_table
    if resolved_source_table:
        query["source_table"] = resolved_source_table
    return (
        f"{reverse('office:print_service_schedule', args=[schedule.household_uid, schedule.schedule_uid])}"
        f"?{urlencode(query)}"
    )


def _service_schedule_print_group(schedule: ServiceSchedule) -> list[ServiceSchedule]:
    if schedule.link_group_key:
        related = list(
            ServiceSchedule.objects.filter(
                link_group_key=schedule.link_group_key,
                deleted_at__isnull=True,
            )
            .select_related("household", "person", "person__deceased_profile")
            .order_by("person_uid", "id")
        )
    else:
        related = [schedule]
    related.sort(
        key=lambda item: (
            item.pk != schedule.pk,
            service_ledger_runtime._actual_service_schedule_death_date(item) or date.max,
            item.subject_name or item.person_name_snapshot or "",
        )
    )
    return related


def _person_related_visit_notes(schedule: ServiceSchedule) -> list[VisitNote]:
    if not schedule.household_id or not schedule.person_id:
        return []
    queryset = (
        VisitNote.objects.filter(household_id=schedule.household_id)
        .filter(Q(person_id=schedule.person_id) | Q(service_schedule__person_id=schedule.person_id))
        .select_related("service_schedule", "person")
        .order_by("-visited_on", "-created_at")
    )
    note_entries: list[VisitNote] = []
    seen_ids: set[int] = set()
    for note in queryset:
        if note.pk in seen_ids:
            continue
        seen_ids.add(note.pk)
        note_entries.append(note)
        if len(note_entries) >= 4:
            break
    return note_entries


def _resolve_service_schedule_sutra_label(
    schedule: ServiceSchedule,
    *,
    sutra_cycle: list[str] | None = None,
) -> str:
    resolved_cycle = sutra_cycle or temple_identity_services.service_schedule_sutra_cycle()
    if not resolved_cycle:
        return ""
    if memorial_dates._kijitsu_offset_days_from_label(schedule.service_label) == 48:
        return resolved_cycle[0]
    memorial_offset_years = memorial_dates._memorial_offset_years_from_label(schedule.service_label)
    if memorial_offset_years is None:
        return ""
    for cycle_order, rule in enumerate(memorial_dates._effective_memorial_rules([]), start=1):
        try:
            rule_years = max(int(rule.get("years", 0)), 0)
        except (TypeError, ValueError):
            continue
        if rule_years == memorial_offset_years:
            return resolved_cycle[cycle_order % len(resolved_cycle)]
    return ""


def _build_service_schedule_print_card(
    schedule: ServiceSchedule,
    *,
    sutra_cycle: list[str] | None = None,
) -> dict:
    person = schedule.person
    household_name = schedule.household_name_snapshot or (
        _household_display_head_name(schedule.household) if schedule.household_id else ""
    )
    actual_death_date = service_ledger_runtime._actual_service_schedule_death_date(schedule)
    death_date_label = actual_death_date.isoformat() if actual_death_date else ""
    death_date_wareki = memorial_dates._to_wareki_date_numeric(actual_death_date) if actual_death_date else ""
    planned_death_date = service_ledger_runtime._resolved_service_schedule_target_date(schedule)
    planned_death_date_label = planned_death_date.isoformat() if planned_death_date else ""
    planned_death_date_wareki = (
        memorial_dates._to_wareki_date_numeric(planned_death_date) if planned_death_date else ""
    )
    note_items: list[dict[str, str]] = []
    if person is not None and (person.person_note or "").strip():
        note_items.append(
            {
                "label": "個人メモ",
                "meta": "",
                "body": person.person_note.strip(),
            }
        )
    if person is not None and (person.deceased_note or "").strip():
        note_items.append(
            {
                "label": "故人備考",
                "meta": "",
                "body": person.deceased_note.strip(),
            }
        )
    for note in _person_related_visit_notes(schedule):
        meta_parts = [note.visited_on.isoformat()]
        if note.author_label:
            meta_parts.append(note.author_label)
        note_items.append(
            {
                "label": note.title or "訪問メモ",
                "meta": " / ".join(part for part in meta_parts if part),
                "body": note.body.strip(),
            }
        )
    age_text = ""
    estimated_birth_year_text = ""
    if person is not None and person.age_at_death is not None:
        age_text = f"{person.age_at_death}{person.age_unit or '歳'}"
        if actual_death_date is not None and (person.age_unit or "歳") in {"歳", "才"}:
            estimated_birth_year = actual_death_date.year - person.age_at_death + 1
            estimated_birth_year_text = (
                f"{estimated_birth_year}年生（{memorial_dates._to_wareki_year_numeric(estimated_birth_year)}）"
            )
    return {
        "household_name": household_name,
        "person_name": schedule.subject_name or schedule.person_name_snapshot or "",
        "person_kana": person.kana if person is not None else "",
        "kaimyo": person.kaimyo if person is not None else "",
        "kaimyo_kana": person.kaimyo_kana if person is not None else "",
        "death_date": death_date_label,
        "death_date_wareki": death_date_wareki,
        "planned_death_date": planned_death_date_label,
        "planned_death_date_wareki": planned_death_date_wareki,
        "age_at_death": age_text,
        "estimated_birth_year": estimated_birth_year_text,
        "service_label": schedule.service_label,
        "sutra_label": _resolve_service_schedule_sutra_label(schedule, sutra_cycle=sutra_cycle),
        "relationship_label": person.relationship_label if person is not None else "",
        "note_items": note_items,
        "has_notes": bool(note_items),
        "is_current": False,
    }


def _household_future_memorial_rows(
    schedule: ServiceSchedule,
    participant_schedules: list[ServiceSchedule],
    *,
    years_ahead: int = 3,
) -> list[dict[str, str]]:
    if not schedule.household_id:
        return []
    period_start = timezone.localdate()
    period_end = memorial_dates._replace_year_clamped(period_start, period_start.year + years_ahead)
    related_people = list(
        Person.objects.filter(
            household_id=schedule.household_id,
            deleted_at__isnull=True,
            is_deceased=True,
        )
        .select_related("deceased_profile")
        .order_by("person_uid", "id")
    )
    memorial_members: list[dict[str, str]] = []
    for person in related_people:
        if person.death_date is None:
            continue
        memorial_members.append(
            {
                "household_id": schedule.household.household_uid,
                "household_name": schedule.household_name_snapshot
                or (_household_display_head_name(schedule.household) if schedule.household_id else ""),
                "person_id": person.person_uid,
                "name": person.name,
                "relationship": person.relationship_label,
                "kaimyo": person.kaimyo,
                "death_date": person.death_date.isoformat(),
                "death_date_iso": person.death_date.isoformat(),
                "age_at_death": person.age_at_death_raw
                or (str(person.age_at_death) if person.age_at_death is not None else ""),
                "age_unit": person.age_unit or "歳",
            }
        )
    memorial_rules = memorial_dates._effective_memorial_rules([])
    current_group_keys = {
        (
            item.person_uid or "",
            item.service_label or "",
            (service_ledger_runtime._resolved_service_schedule_target_date(item) or date.min).isoformat(),
        )
        for item in participant_schedules
        if service_ledger_runtime._resolved_service_schedule_target_date(item) is not None
    }
    household_actual_schedules = [
        item
        for item in ServiceSchedule.objects.filter(
            household_id=schedule.household_id,
            deleted_at__isnull=True,
        )
        .select_related("household", "person", "person__deceased_profile")
        .order_by("scheduled_date", "scheduled_time", "id")
        if service_ledger_runtime._is_actual_service_schedule(item)
    ]
    linked_schedules_by_group: dict[str, list[ServiceSchedule]] = {}
    for item in household_actual_schedules:
        if item.link_group_key:
            linked_schedules_by_group.setdefault(item.link_group_key, []).append(item)
    household_schedule_entries = [
        service_ledger_runtime._service_ledger_schedule_entry(
            item,
            today=period_start,
            overdue_period_start=period_start - timedelta(days=183),
        )
        for item in household_actual_schedules
    ]
    rows: list[dict[str, str]] = []
    for item in household_actual_schedules:
        target_date = service_ledger_runtime._resolved_service_schedule_target_date(item)
        if target_date is None:
            continue
        if not (period_start <= target_date <= period_end):
            continue
        signature = (
            item.person_uid or "",
            item.service_label or "",
            target_date.isoformat(),
        )
        if signature in current_group_keys:
            continue
        rows.append(
            {
                "person_name": item.subject_name or item.person_name_snapshot or "",
                "service_label": item.service_label,
                "target_date": target_date.isoformat(),
                "scheduled_date": item.scheduled_date.isoformat() if item.scheduled_date else "",
                "status_label": service_ledger_runtime._effective_service_schedule_status_label(item),
                "kind_label": "予定済み",
                "completion_note": memorial_notice_columns._memorial_notice_note(
                    item,
                    target_date,
                    linked_schedules_by_group,
                ),
            }
        )
    candidates = _build_memorial_candidates(
        memorial_members,
        memorial_rules,
        period_start,
        period_end,
    )
    for candidate in candidates:
        if candidate.get("candidate_type") != "回忌":
            continue
        signature = (
            candidate.get("person_id", ""),
            candidate.get("label", ""),
            candidate.get("target_date", ""),
        )
        if signature in current_group_keys:
            continue
        if service_ledger_runtime._candidate_already_has_actual_schedule(candidate, household_schedule_entries):
            continue
        rows.append(
            {
                "person_name": candidate.get("person_name", ""),
                "service_label": candidate.get("label", ""),
                "target_date": candidate.get("target_date", ""),
                "scheduled_date": "",
                "status_label": "未定",
                "kind_label": "候補",
                "completion_note": "",
            }
        )
    rows.sort(
        key=lambda item: (
            item.get("target_date", "9999-99-99"),
            runtime_shared._sort_text(item.get("person_name")),
            runtime_shared._sort_text(item.get("service_label")),
        )
    )
    return rows
