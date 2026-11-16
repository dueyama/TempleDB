from __future__ import annotations

from django.db.models import Count

from . import browser_dataset, canonical_population, source_runtime
from .memorial_shared import LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES
from .models import Person, ServiceSchedule


def _load_household_browser_dataset(
    source_id: str,
    snapshot_id: str,
    *,
    data_backend: str = "db",
    canonical_population_checked: bool = False,
) -> dict:
    return browser_dataset._load_household_browser_dataset(
        source_id,
        snapshot_id,
        data_backend=data_backend,
        canonical_population_checked=canonical_population_checked,
    )


def latest_export_snapshot(source_id: str) -> dict | None:
    return source_runtime.latest_export_snapshot(source_id)


def latest_succeeded_import_batch(source_id: str, *, snapshot_id: str | None = None):
    return source_runtime.latest_succeeded_import_batch(source_id, snapshot_id=snapshot_id)


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    return source_runtime.registered_sources(selected_source_id)


def resolve_runtime_source_entry() -> dict:
    return source_runtime.resolve_runtime_source_entry()


def source_summary(source_id: str | None = None) -> dict:
    return source_runtime.source_summary(source_id)


def _load_service_ledger_schedules(
    batch,
    *,
    canonical_population_checked: bool = False,
) -> list[ServiceSchedule]:
    if not canonical_population_checked:
        canonical_population.canonical_provenance_import_batch(
            source_id=batch.source.source_id if batch is not None else None,
        )
    return list(
        ServiceSchedule.objects.filter(
            deleted_at__isnull=True,
        )
        .exclude(
            record_origin=ServiceSchedule.Origin.IMPORTED,
            source_table__in=LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES,
        )
        .select_related("household", "household__head_person", "person", "person__deceased_profile")
        .annotate(
            note_count=Count("visit_notes", distinct=True),
            payment_count=Count("offering_payments", distinct=True),
        )
        .order_by("scheduled_date", "scheduled_time", "target_date", "id")
    )


def _load_service_target_people(
    batch,
    *,
    canonical_population_checked: bool = False,
) -> list[Person]:
    if not canonical_population_checked:
        canonical_population.canonical_provenance_import_batch(
            source_id=batch.source.source_id if batch is not None else None,
        )
    return list(
        Person.objects.filter(
            deleted_at__isnull=True,
        )
        .select_related("household", "household__head_person", "deceased_profile")
        .order_by("household__household_uid", "person_uid")
    )


__all__ = [
    "_load_household_browser_dataset",
    "latest_export_snapshot",
    "latest_succeeded_import_batch",
    "registered_sources",
    "resolve_runtime_source_entry",
    "source_summary",
    "_load_service_ledger_schedules",
    "_load_service_target_people",
]
