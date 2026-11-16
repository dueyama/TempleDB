from __future__ import annotations

from pathlib import Path

from django.db import transaction

from . import importer_batch_lifecycle, importer_household_rows, importer_person_rows
from .importer_postprocess import (
    _assign_imported_household_head_people,
    _copy_district_officer_flags_from_previous_batch,
)
from .legacy_reimport_guard import require_legacy_reimport
from .models import ImportBatch


def import_households_persons(
    source_id: str | None = None,
    snapshot_id: str | None = None,
    mode: str = ImportBatch.Mode.REHEARSAL,
    *,
    expected_source_path: str | Path | None = None,
) -> ImportBatch:
    return importer_batch_lifecycle.import_households_persons(
        source_id=source_id,
        snapshot_id=snapshot_id,
        mode=mode,
        expected_source_path=expected_source_path,
    )


def import_households_persons_from_snapshots(
    *,
    source_entry: dict,
    export_snapshot: dict,
    prepared_snapshot: dict,
    mode: str = ImportBatch.Mode.REHEARSAL,
) -> ImportBatch:
    authorization = require_legacy_reimport(
        source_entry.get("source_id"),
        resolved_source_path=source_entry.get("resolved_path"),
    )
    batch = importer_batch_lifecycle._create_running_import_batch(
        source_entry=source_entry,
        export_snapshot=export_snapshot,
        prepared_snapshot=prepared_snapshot,
        mode=mode,
        authorized_primary_source_id=authorization.source_id,
    )

    try:
        stats = _run_household_person_import(
            batch=batch,
            source_entry=source_entry,
            prepared_snapshot=prepared_snapshot,
        )
    except Exception as exc:
        importer_batch_lifecycle._mark_import_batch_failed(batch, exc)
        raise

    importer_batch_lifecycle._mark_import_batch_succeeded(batch, stats)
    return batch


def _run_household_person_import(
    *,
    batch: ImportBatch,
    source_entry: dict,
    prepared_snapshot: dict,
) -> dict:
    table_paths = importer_batch_lifecycle._prepared_household_person_tables(prepared_snapshot)
    stats = importer_batch_lifecycle._initial_import_stats()

    with transaction.atomic():
        households_by_legacy_id = importer_household_rows._import_household_rows(
            batch=batch,
            source_entry=source_entry,
            prepared_snapshot=prepared_snapshot,
            table_paths=table_paths,
            stats=stats,
        )
        importer_person_rows._import_person_rows(
            batch=batch,
            source_entry=source_entry,
            prepared_snapshot=prepared_snapshot,
            table_paths=table_paths,
            households_by_legacy_id=households_by_legacy_id,
            stats=stats,
        )
        _assign_imported_household_head_people(
            households=households_by_legacy_id.values(),
            batch=batch,
        )
        district_officer_copy = _copy_district_officer_flags_from_previous_batch(batch=batch)

    stats["summary"] = {
        "orphan_persons": stats["orphan_persons"],
        "orphan_service_households": stats["orphan_service_households"],
        "missing_service_persons": stats["missing_service_persons"],
        "birth_date_parse_errors": stats["birth_date_parse_errors"],
        "death_date_parse_errors": stats["death_date_parse_errors"],
        "scheduled_date_parse_errors": stats["scheduled_date_parse_errors"],
        "district_officer_copy": district_officer_copy,
    }
    return stats


def _iter_jsonl(path):
    return importer_batch_lifecycle._iter_jsonl(path)


def _create_issue(
    *,
    batch,
    stats: dict,
    severity: str,
    code: str,
    record: dict,
    legacy_pk_text: str,
    message: str,
    details: dict | None = None,
) -> None:
    return importer_person_rows._create_issue(
        batch=batch,
        stats=stats,
        severity=severity,
        code=code,
        record=record,
        legacy_pk_text=legacy_pk_text,
        message=message,
        details=details,
    )


def _sync_household_notice_flags_from_legacy(
    *,
    source,
    households,
) -> None:
    return importer_household_rows._sync_household_notice_flags_from_legacy(
        source=source,
        households=households,
    )
