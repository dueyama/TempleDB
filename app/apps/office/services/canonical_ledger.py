from __future__ import annotations

from dataclasses import dataclass

from apps.imports import canonical_population, source_runtime
from apps.imports.models import ImportBatch


class CanonicalLedgerUnavailable(LookupError):
    """Raised when an operational source has no usable canonical ledger."""


@dataclass(frozen=True)
class CanonicalLedgerContext:
    source_id: str
    provenance_batch: ImportBatch


def resolve_canonical_ledger_context(
    source_id: str | None = None,
) -> CanonicalLedgerContext:
    """Resolve the operational source and validate its canonical provenance."""

    requested_source_id = (source_id or "").strip()
    try:
        resolved_source_id = source_runtime.operational_source_id(source_id)
    except KeyError as exc:
        message = (
            f"unknown source: {requested_source_id}"
            if requested_source_id
            else "unknown operational source"
        )
        raise CanonicalLedgerUnavailable(message) from exc

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=resolved_source_id,
    )
    if provenance_batch is None:
        raise CanonicalLedgerUnavailable("canonical provenance batch not found")
    return CanonicalLedgerContext(
        source_id=resolved_source_id,
        provenance_batch=provenance_batch,
    )


__all__ = [
    "CanonicalLedgerContext",
    "CanonicalLedgerUnavailable",
    "resolve_canonical_ledger_context",
]
