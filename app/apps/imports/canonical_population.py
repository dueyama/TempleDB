from __future__ import annotations

from dataclasses import dataclass

from django.db.models import BigIntegerField, Case, F, QuerySet, Value, When
from django.db.utils import OperationalError, ProgrammingError

from .models import (
    Household,
    ImportBatch,
    OfferingPayment,
    Person,
    ServiceSchedule,
    VisitNote,
)


class CanonicalPopulationConflict(RuntimeError):
    pass


class CanonicalPopulationMissingProvenance(CanonicalPopulationConflict):
    pass


class CanonicalPopulationBatchStatusError(CanonicalPopulationConflict):
    pass


class CanonicalPopulationImportInProgress(CanonicalPopulationConflict):
    pass


CANONICAL_BATCH_RELATIONS = (
    (Household, "batch_id"),
    (Person, "batch_id"),
    (ServiceSchedule, "related_batch_id"),
    (VisitNote, "related_batch_id"),
    (OfferingPayment, "related_batch_id"),
)

# ImportBatch primary keys are positive. These negative markers can therefore
# travel through the same UNION query as real IDs without being mistaken for one.
_MISSING_PROVENANCE_SENTINELS = {
    ServiceSchedule: -1,
    VisitNote: -2,
    OfferingPayment: -3,
}
_INVALID_BATCH_STATUS_SENTINEL = -4
_RUNNING_IMPORT_SENTINEL = -5


@dataclass(frozen=True)
class CanonicalPopulationState:
    batch_ids: frozenset[int]
    missing_provenance_models: tuple[str, ...]
    has_invalid_batch_status: bool
    has_running_import: bool


def _population_marker_query(model, field_name: str) -> QuerySet:
    relation_name = field_name.removesuffix("_id")
    whens = []
    missing_sentinel = _MISSING_PROVENANCE_SENTINELS.get(model)
    if missing_sentinel is not None:
        whens.append(
            When(
                **{f"{field_name}__isnull": True},
                then=Value(missing_sentinel),
            )
        )
    whens.append(
        When(
            **{f"{relation_name}__status": ImportBatch.Status.SUCCEEDED},
            then=F(field_name),
        )
    )
    return (
        model.objects.order_by()
        .annotate(
            _canonical_population_marker=Case(
                *whens,
                default=Value(_INVALID_BATCH_STATUS_SENTINEL),
                output_field=BigIntegerField(),
            )
        )
        .values_list("_canonical_population_marker", flat=True)
    )


def _running_import_marker_query() -> QuerySet:
    return (
        ImportBatch.objects.filter(status=ImportBatch.Status.RUNNING)
        .order_by()
        .annotate(
            _canonical_population_marker=Value(
                _RUNNING_IMPORT_SENTINEL,
                output_field=BigIntegerField(),
            )
        )
        .values_list("_canonical_population_marker", flat=True)
    )


def canonical_population_state() -> CanonicalPopulationState:
    """Inspect canonical ownership, missing provenance, and batch status in one query."""

    marker_queries = [
        _population_marker_query(model, field_name)
        for model, field_name in CANONICAL_BATCH_RELATIONS
    ]
    marker_queries.append(_running_import_marker_query())
    markers = frozenset(int(value) for value in marker_queries[0].union(*marker_queries[1:]))
    missing_models = tuple(
        model.__name__
        for model, sentinel in _MISSING_PROVENANCE_SENTINELS.items()
        if sentinel in markers
    )
    sentinel_values = {
        *_MISSING_PROVENANCE_SENTINELS.values(),
        _INVALID_BATCH_STATUS_SENTINEL,
        _RUNNING_IMPORT_SENTINEL,
    }
    return CanonicalPopulationState(
        batch_ids=frozenset(marker for marker in markers if marker not in sentinel_values),
        missing_provenance_models=missing_models,
        has_invalid_batch_status=_INVALID_BATCH_STATUS_SENTINEL in markers,
        has_running_import=_RUNNING_IMPORT_SENTINEL in markers,
    )


def _raise_for_invalid_population_state(state: CanonicalPopulationState) -> None:
    if state.has_running_import:
        raise CanonicalPopulationImportInProgress(
            "A canonical import is currently running; normal ledger access is paused."
        )
    if state.missing_provenance_models:
        labels = ", ".join(state.missing_provenance_models)
        raise CanonicalPopulationMissingProvenance(
            "Canonical operational data is missing related_batch provenance: "
            f"{labels}"
        )
    if state.has_invalid_batch_status:
        raise CanonicalPopulationBatchStatusError(
            "Canonical business data belongs to an import batch that has not succeeded."
        )


def canonical_population_batch_ids() -> frozenset[int]:
    """Return batches that own valid canonical or operational rows."""

    state = canonical_population_state()
    _raise_for_invalid_population_state(state)
    return state.batch_ids


def canonical_business_records_exist() -> bool:
    """Return whether an import would append to an existing canonical ledger."""

    return bool(canonical_population_batch_ids())


def require_single_canonical_population() -> int | None:
    """Fail closed instead of combining records from invalid import populations."""

    batch_ids = canonical_population_batch_ids()
    if len(batch_ids) > 1:
        labels = ", ".join(str(batch_id) for batch_id in sorted(batch_ids))
        raise CanonicalPopulationConflict(
            f"Canonical business data spans multiple import batches: {labels}"
        )
    return next(iter(batch_ids), None)


def canonical_provenance_import_batch(
    *,
    source_id: str | None = None,
) -> ImportBatch | None:
    """Return the data-bearing batch, falling back only for an empty ledger."""

    expected_source_id = (source_id or "").strip()
    batch_id = require_single_canonical_population()
    if batch_id is not None:
        batch = ImportBatch.objects.select_related("source").get(pk=batch_id)
        # Recheck after resolving the ID so a concurrent status change cannot
        # expose data from a RUNNING, FAILED, or PENDING import.
        if batch.status != ImportBatch.Status.SUCCEEDED:
            raise CanonicalPopulationBatchStatusError(
                "Canonical business data belongs to an import batch that has not succeeded."
            )
        if expected_source_id and batch.source.source_id != expected_source_id:
            raise CanonicalPopulationConflict(
                "Canonical business data belongs to source "
                f"{batch.source.source_id}, not {expected_source_id}."
            )
        return batch

    batches = ImportBatch.objects.filter(status=ImportBatch.Status.SUCCEEDED).select_related(
        "source"
    )
    if expected_source_id:
        batches = batches.filter(source__source_id=expected_source_id)
    return batches.order_by("-created_at", "-pk").first()


def safe_canonical_population_batch_ids() -> frozenset[int]:
    try:
        return canonical_population_batch_ids()
    except (OperationalError, ProgrammingError):
        return frozenset()


def safe_canonical_population_state() -> CanonicalPopulationState | None:
    try:
        return canonical_population_state()
    except (OperationalError, ProgrammingError):
        return None


__all__ = [
    "CANONICAL_BATCH_RELATIONS",
    "CanonicalPopulationBatchStatusError",
    "CanonicalPopulationConflict",
    "CanonicalPopulationImportInProgress",
    "CanonicalPopulationMissingProvenance",
    "CanonicalPopulationState",
    "canonical_business_records_exist",
    "canonical_population_batch_ids",
    "canonical_population_state",
    "canonical_provenance_import_batch",
    "require_single_canonical_population",
    "safe_canonical_population_batch_ids",
    "safe_canonical_population_state",
]
