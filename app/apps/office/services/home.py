from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from apps.imports import canonical_population, source_runtime
from apps.imports.models import ServiceSchedule
from apps.office.services.home_memorial_calendar import build_home_memorial_calendar_context
from apps.office.services.home_service_completion import attach_home_completion_entries
from apps.office.services.memorials import build_home_service_schedule_summary


def build_home_context() -> dict:
    source = source_runtime.operational_source_summary()
    latest_export = source_runtime.latest_export_snapshot(source["source_id"])
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source["source_id"],
    )
    context = {
        "home_refresh_date": timezone.localdate().isoformat(),
        "home_refresh_timezone": timezone.get_current_timezone_name(),
        "selected_source_id": source["source_id"],
        "source": source,
        "latest_export": latest_export,
    }
    context["home_schedule"] = build_home_service_schedule_summary(
        source_id=source["source_id"],
        latest_export=latest_export,
        batch=provenance_batch,
        canonical_population_checked=True,
    )
    _include_temple_events(context["home_schedule"])
    attach_home_completion_entries(context["home_schedule"])
    context["home_memorial_calendar"] = build_home_memorial_calendar_context(
        source_id=source["source_id"],
        batch=provenance_batch,
        canonical_population_checked=True,
    )
    return context


def _include_temple_events(summary: dict) -> None:
    """Merge temple events into the home cards without changing the service ledger."""
    if not summary["available"]:
        return
    today = date.fromisoformat(summary["today_label"])
    events = ServiceSchedule.objects.filter(
        event_scope=ServiceSchedule.EventScope.TEMPLE,
        deleted_at__isnull=True,
        scheduled_date__range=(today, today + timedelta(days=6)),
        status__in=(ServiceSchedule.Status.CANDIDATE, ServiceSchedule.Status.SCHEDULED),
    ).order_by("scheduled_date", "scheduled_time", "pk")
    for event in events:
        days = (event.scheduled_date - today).days
        key = "today_events" if days == 0 else "next_events"
        summary[key].append({
            "is_temple_event": True,
            "event_id": event.pk,
            "service_label": event.service_label,
            "subject_name": event.subject_name,
            "scheduled_date": event.scheduled_date.isoformat(),
            "scheduled_time": event.scheduled_time.strftime("%H:%M") if event.scheduled_time else "",
            "location": event.location,
            "days_until_label": f"{days}日後" if days else "",
        })
    for prefix in ("today", "next"):
        key = f"{prefix}_events"
        summary[key] = sorted(summary[key], key=lambda entry: (
            entry.get("scheduled_date") or "",
            entry.get("scheduled_time") or "99:99",
        ))[:4]
        summary[f"{prefix}_count"] = len(summary[key])
