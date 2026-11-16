from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from apps.imports.models import GoogleCalendarSyncBinding, ServiceSchedule

from .google_calendar_sync_payloads import (
    _build_google_calendar_event_payload,
    _google_calendar_effective_date,
    _google_calendar_payload_fingerprint,
)


@dataclass(frozen=True)
class _SyncTarget:
    sync_key: str
    primary_schedule: ServiceSchedule | None
    member_schedule_ids: list[int]
    should_exist: bool
    payload: dict | None
    fingerprint: str

def google_calendar_sync_key_for_schedule(schedule: ServiceSchedule) -> str:
    link_group_key = (schedule.link_group_key or "").strip()
    if link_group_key:
        return f"link:{link_group_key}"
    return f"schedule:{schedule.pk}"

def _build_sync_target(sync_key: str) -> _SyncTarget:
    primary_schedule: ServiceSchedule | None = None
    member_schedule_ids: list[int] = []
    sync_type, raw_key = _split_sync_key(sync_key)
    if sync_type == "link":
        schedules = list(
            ServiceSchedule.objects.filter(
                link_group_key=raw_key,
                deleted_at__isnull=True,
            )
            .select_related("household", "person")
            .order_by("pk")
        )
        if schedules:
            primary_schedule = schedules[0]
            member_schedule_ids = [schedule.pk for schedule in schedules]
    elif sync_type == "schedule" and raw_key.isdigit():
        schedule = (
            ServiceSchedule.objects.filter(pk=int(raw_key), deleted_at__isnull=True)
            .select_related("household", "person")
            .first()
        )
        if schedule is not None and not (schedule.link_group_key or "").strip():
            primary_schedule = schedule
            member_schedule_ids = [schedule.pk]

    if primary_schedule is None:
        return _SyncTarget(sync_key=sync_key, primary_schedule=None, member_schedule_ids=[], should_exist=False, payload=None, fingerprint="")

    effective_date = _google_calendar_effective_date(primary_schedule)
    should_exist = (
        primary_schedule.status in {
            ServiceSchedule.Status.SCHEDULED,
            ServiceSchedule.Status.COMPLETED,
            ServiceSchedule.Status.CANCELLED,
            ServiceSchedule.Status.DEFERRED,
        }
        and effective_date is not None
    )
    payload = _build_google_calendar_event_payload(
        sync_key=sync_key,
        schedule=primary_schedule,
        member_schedule_ids=member_schedule_ids,
    ) if should_exist else None
    fingerprint = _google_calendar_payload_fingerprint(
        sync_key=sync_key,
        schedule=primary_schedule,
        member_schedule_ids=member_schedule_ids,
        payload=payload,
    ) if should_exist and payload is not None else ""
    if payload is not None:
        payload.setdefault("extendedProperties", {}).setdefault("private", {})
        payload["extendedProperties"]["private"].update(
            {
                "templedb_sync_key": sync_key,
                "templedb_primary_schedule_id": str(primary_schedule.pk),
                "templedb_member_schedule_ids": ",".join(str(item) for item in member_schedule_ids),
                "templedb_fingerprint": fingerprint,
            }
        )
    return _SyncTarget(
        sync_key=sync_key,
        primary_schedule=primary_schedule,
        member_schedule_ids=member_schedule_ids,
        should_exist=should_exist,
        payload=payload,
        fingerprint=fingerprint,
    )

def _normalized_sync_keys(sync_keys: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for sync_key in sync_keys:
        value = str(sync_key or "").strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _collect_google_calendar_reconcile_keys() -> set[str]:
    # A previously synchronized standalone event can become obsolete when its
    # schedule joins a group. Retain those old keys so reconcile can delete it.
    keys = set(GoogleCalendarSyncBinding.objects.values_list("sync_key", flat=True))
    for schedule in (
        ServiceSchedule.objects.filter(deleted_at__isnull=True)
        .filter(
            Q(status__in=[
                ServiceSchedule.Status.SCHEDULED,
                ServiceSchedule.Status.COMPLETED,
                ServiceSchedule.Status.CANCELLED,
                ServiceSchedule.Status.DEFERRED,
            ])
            | Q(scheduled_date__isnull=False)
            | Q(completed_on__isnull=False)
            | Q(target_date__isnull=False)
        )
        .only("id", "link_group_key")
    ):
        keys.add(google_calendar_sync_key_for_schedule(schedule))
    return keys

def _split_sync_key(sync_key: str) -> tuple[str, str]:
    key = str(sync_key or "").strip()
    if ":" not in key:
        return "", key
    prefix, raw = key.split(":", 1)
    return prefix, raw


def _coerce_positive_ints(values: list[int] | tuple[int, ...]) -> list[int]:
    resolved: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed <= 0 or parsed in resolved:
            continue
        resolved.append(parsed)
    return resolved
