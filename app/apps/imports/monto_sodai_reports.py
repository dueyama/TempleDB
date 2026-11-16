from __future__ import annotations

from . import canonical_population, monto_sodai_analysis, monto_sodai_sources
from .monto_sodai_db_reports import (
    build_monto_sodai_postal_label_context_for_batch,
    build_monto_sodai_roster_context_for_batch,
)


def build_monto_sodai_roster_context(source_id: str, *, folder_name: str | None = None) -> dict:
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    candidates = monto_sodai_sources.list_auxiliary_monto_sodai_csv_candidates()
    selected_folder_name = folder_name or (candidates[0]["folder_name"] if candidates else "")
    csv_path = monto_sodai_sources.latest_auxiliary_monto_sodai_csv_path(
        selected_folder_name or None
    )
    roster_context = build_monto_sodai_roster_context_for_batch(
        source_id,
        canonical_batch,
    )
    analysis = (
        monto_sodai_analysis.analyze_monto_sodai_rows(
            source_id,
            folder_name=selected_folder_name or None,
        )
        if csv_path and roster_context.get("available")
        else None
    )
    return {
        **roster_context,
        "monto_sodai_folder": selected_folder_name,
        "monto_sodai_candidates": candidates,
        "monto_sodai_csv_path": str(csv_path) if csv_path else "",
        "analysis": analysis,
    }


def build_monto_sodai_postal_label_context(
    source_id: str,
    *,
    include_role_title: bool = True,
) -> dict:
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    return build_monto_sodai_postal_label_context_for_batch(
        source_id,
        canonical_batch,
        include_role_title=include_role_title,
    )
