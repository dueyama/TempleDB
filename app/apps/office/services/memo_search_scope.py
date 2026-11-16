from __future__ import annotations

from django.db.models import Q

from apps.imports import canonical_population, source_runtime
from apps.imports.models import Household, ImportBatch, Person, ServiceSchedule, VisitNote


def _resolve_search_scope(
    *,
    source_id: str | None,
    include_history: bool,
) -> tuple[str, ImportBatch | None]:
    resolved_source_id = _resolve_search_source_id(source_id)
    if include_history:
        return resolved_source_id, None
    visible_batch = canonical_population.canonical_provenance_import_batch(
        source_id=resolved_source_id,
    )
    return resolved_source_id, visible_batch


def _resolve_search_source_id(source_id: str | None) -> str:
    return source_runtime.resolve_source_entry(source_id)["source_id"]


def _scoped_households(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
):
    queryset = Household.objects.select_related("head_person", "batch").filter(deleted_at__isnull=True)
    if include_history:
        return queryset.filter(batch__source__source_id=source_id)
    return queryset


def _scoped_people(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
):
    queryset = Person.objects.select_related("household", "batch").filter(deleted_at__isnull=True)
    if include_history:
        return queryset.filter(batch__source__source_id=source_id)
    return queryset


def _scoped_service_schedules(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
):
    queryset = ServiceSchedule.objects.select_related("household", "person", "related_batch").filter(
        deleted_at__isnull=True
    )
    if include_history:
        return queryset.filter(
            Q(related_batch__source__source_id=source_id)
            | Q(related_batch__isnull=True, legacy_source_id=source_id)
        )
    return queryset


def _scoped_visit_notes(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
):
    queryset = VisitNote.objects.select_related("household", "person", "related_batch")
    if include_history:
        return queryset.filter(
            Q(related_batch__source__source_id=source_id)
            | Q(related_batch__isnull=True, legacy_source_id=source_id)
        )
    return queryset
