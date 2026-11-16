from __future__ import annotations

from apps.imports.canonical_population import canonical_provenance_import_batch
from apps.imports.monto_sodai_db_reports import (
    build_monto_sodai_postal_label_context_for_batch,
    build_monto_sodai_roster_context_for_batch,
)


def build_monto_sodai_roster_context(source_id: str) -> dict:
    provenance_batch = canonical_provenance_import_batch(source_id=source_id)
    return build_monto_sodai_roster_context_for_batch(source_id, provenance_batch)


def build_monto_sodai_postal_label_context(
    source_id: str,
    *,
    include_role_title: bool = True,
) -> dict:
    provenance_batch = canonical_provenance_import_batch(source_id=source_id)
    return build_monto_sodai_postal_label_context_for_batch(
        source_id,
        provenance_batch,
        include_role_title=include_role_title,
    )
