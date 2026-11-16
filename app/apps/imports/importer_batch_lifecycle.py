from __future__ import annotations

import json
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from . import canonical_population
from .importer_sources import (
    resolve_export_snapshot,
    resolve_prepared_snapshot,
    resolve_source_entry,
    sync_export_snapshot,
    sync_legacy_source,
)
from .legacy_reimport_guard import LegacyReimportBlocked, require_legacy_reimport
from .models import ImportBatch

TABLE_HOUSEHOLDS = "UTB001_戸主"
TABLE_PERSONS = "UTB002_家族"


def _initial_import_stats() -> dict:
    return {
        "records_read": 0,
        "households_imported": 0,
        "persons_imported": 0,
        "deceased_profiles_imported": 0,
        "service_schedules_imported": 0,
        "issues_count": 0,
        "orphan_persons": 0,
        "orphan_service_households": 0,
        "missing_service_persons": 0,
        "birth_date_parse_errors": 0,
        "death_date_parse_errors": 0,
        "scheduled_date_parse_errors": 0,
    }


def _prepared_household_person_tables(prepared_snapshot: dict) -> dict:
    prepared_manifest = prepared_snapshot["manifest"]
    tables = {row["table_name"]: row for row in prepared_manifest.get("tables", [])}
    household_table = tables.get(TABLE_HOUSEHOLDS)
    person_table = tables.get(TABLE_PERSONS)
    if household_table is None or person_table is None:
        raise ValueError("Prepared snapshot is missing UTB001_戸主 or UTB002_家族.")
    prepared_dir = Path(prepared_snapshot["prepared_dir"])
    return {
        "prepared_dir": prepared_dir,
        "household_path": prepared_dir / household_table["jsonl_file"],
        "person_path": prepared_dir / person_table["jsonl_file"],
        "source_export_batch": prepared_snapshot["snapshot_id"],
    }


def _create_running_import_batch(
    *,
    source_entry: dict,
    export_snapshot: dict,
    prepared_snapshot: dict,
    mode: str,
    authorized_primary_source_id: str | None = None,
) -> ImportBatch:
    export_snapshot_id = export_snapshot["snapshot_id"]
    prepared_snapshot_id = prepared_snapshot["snapshot_id"]
    if export_snapshot_id != prepared_snapshot_id:
        raise ValueError(
            "Export snapshot and prepared snapshot do not match: "
            f"{export_snapshot_id} != {prepared_snapshot_id}"
        )

    with transaction.atomic():
        source = sync_legacy_source(
            source_entry,
            authorized_primary_source_id=authorized_primary_source_id,
        )
        if ImportBatch.objects.filter(status=ImportBatch.Status.RUNNING).exists():
            raise LegacyReimportBlocked(
                "Another import started before the canonical import lock was acquired."
            )
        try:
            canonical_records_exist = canonical_population.canonical_business_records_exist()
        except canonical_population.CanonicalPopulationConflict as exc:
            raise LegacyReimportBlocked(
                "Canonical business data provenance is invalid; append import refused."
            ) from exc
        if canonical_records_exist:
            raise LegacyReimportBlocked(
                "Canonical business data already exists; append import refused."
            )
        snapshot = sync_export_snapshot(source=source, export_snapshot=export_snapshot)
        return ImportBatch.objects.create(
            source=source,
            export_snapshot=snapshot,
            scope="households_persons_services",
            mode=mode,
            status=ImportBatch.Status.RUNNING,
            prepared_snapshot_id=prepared_snapshot_id,
            started_at=timezone.now(),
        )


def _mark_import_batch_failed(batch: ImportBatch, exc: Exception) -> None:
    batch.status = ImportBatch.Status.FAILED
    batch.finished_at = timezone.now()
    batch.summary = {"error": str(exc)}
    batch.save(update_fields=["status", "finished_at", "summary", "updated_at"])


def _mark_import_batch_succeeded(batch: ImportBatch, stats: dict) -> None:
    batch.status = ImportBatch.Status.SUCCEEDED
    batch.finished_at = timezone.now()
    batch.records_read = stats["records_read"]
    batch.households_imported = stats["households_imported"]
    batch.persons_imported = stats["persons_imported"]
    batch.deceased_profiles_imported = stats["deceased_profiles_imported"]
    batch.service_schedules_imported = stats["service_schedules_imported"]
    batch.issues_count = stats["issues_count"]
    batch.summary = stats["summary"]
    batch.save(
        update_fields=[
            "status",
            "finished_at",
            "records_read",
            "households_imported",
            "persons_imported",
            "deceased_profiles_imported",
            "service_schedules_imported",
            "issues_count",
            "summary",
            "updated_at",
        ]
    )


def _iter_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            records.append(json.loads(line))
    return records


def import_households_persons(
    source_id: str | None = None,
    snapshot_id: str | None = None,
    mode: str = ImportBatch.Mode.REHEARSAL,
    *,
    expected_source_path: str | Path | None = None,
) -> ImportBatch:
    source_entry = resolve_source_entry(source_id)
    require_legacy_reimport(
        source_entry["source_id"],
        resolved_source_path=source_entry["resolved_path"],
    )
    if expected_source_path is not None:
        resolved_source_path = Path(source_entry["resolved_path"]).resolve(strict=False)
        expected_path = Path(expected_source_path).resolve(strict=False)
        if resolved_source_path != expected_path:
            raise ValueError(
                "Source authority changed after legacy reimport authorization; import refused."
            )
    export_snapshot = resolve_export_snapshot(source_entry["source_id"], snapshot_id)
    prepared_snapshot = resolve_prepared_snapshot(source_entry["source_id"], snapshot_id)
    from . import importer_ingest

    return importer_ingest.import_households_persons_from_snapshots(
        source_entry=source_entry,
        export_snapshot=export_snapshot,
        prepared_snapshot=prepared_snapshot,
        mode=mode,
    )
