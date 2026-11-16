from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.db import models
from django.utils import timezone

from config.runtime_paths import portable_exports_root

from .models import (
    DeceasedProfile,
    ExportSnapshot,
    Household,
    ImportBatch,
    ImportIssue,
    LegacySource,
    Person,
)


@dataclass(frozen=True)
class ExportedTable:
    table_name: str
    queryset: models.QuerySet


def export_portable_snapshot(
    *,
    source_id: str | None = None,
    batch_uuid: str | None = None,
    output_root: str | Path | None = None,
) -> dict:
    batch = _resolve_batch(source_id=source_id, batch_uuid=batch_uuid)
    exported_at = timezone.localtime()
    export_id = exported_at.strftime("%Y%m%d_%H%M%S")
    root = Path(output_root) if output_root is not None else portable_exports_root()
    export_dir = root / batch.source.source_id / export_id
    csv_dir = export_dir / "csv"
    jsonl_dir = export_dir / "jsonl"
    csv_dir.mkdir(parents=True, exist_ok=True)
    jsonl_dir.mkdir(parents=True, exist_ok=True)

    tables = _portable_tables(batch)
    table_summaries = [
        _write_table_files(
            table=table,
            csv_dir=csv_dir,
            jsonl_dir=jsonl_dir,
        )
        for table in tables
    ]

    manifest = {
        "export_id": export_id,
        "exported_at": exported_at.isoformat(),
        "source_id": batch.source.source_id,
        "batch_uuid": str(batch.batch_uuid),
        "prepared_snapshot_id": batch.prepared_snapshot_id,
        "export_snapshot_id": batch.export_snapshot.snapshot_id if batch.export_snapshot else "",
        "output_dir": str(export_dir),
        "notes": {
            "jsonl_preserves_null": True,
            "csv_structured_fields": "dict/list values are stored as JSON strings",
            "selection_rule": "latest successful batch for the source unless --batch-uuid is given",
        },
        "tables": table_summaries,
    }
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    latest_payload = {
        "source_id": batch.source.source_id,
        "export_id": export_id,
        "batch_uuid": str(batch.batch_uuid),
        "output_dir": str(export_dir),
    }
    latest_path = root / batch.source.source_id / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(latest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _resolve_batch(source_id: str | None, batch_uuid: str | None) -> ImportBatch:
    queryset = ImportBatch.objects.select_related("source", "export_snapshot")
    if batch_uuid:
        return queryset.get(batch_uuid=batch_uuid)

    queryset = queryset.filter(status=ImportBatch.Status.SUCCEEDED)
    if source_id:
        queryset = queryset.filter(source__source_id=source_id)
    batch = queryset.order_by("-created_at").first()
    if batch is None:
        target = source_id or "any source"
        raise ImportBatch.DoesNotExist(f"No succeeded import batch was found for {target}.")
    return batch


def _portable_tables(batch: ImportBatch) -> list[ExportedTable]:
    tables = [
        ExportedTable(
            table_name="legacy_sources",
            queryset=LegacySource.objects.filter(pk=batch.source_id).order_by("id"),
        ),
        ExportedTable(
            table_name="import_batches",
            queryset=ImportBatch.objects.filter(pk=batch.pk).order_by("id"),
        ),
        ExportedTable(
            table_name="import_issues",
            queryset=ImportIssue.objects.filter(batch=batch).order_by("id"),
        ),
        ExportedTable(
            table_name="households",
            queryset=Household.objects.filter(batch=batch).order_by("id"),
        ),
        ExportedTable(
            table_name="persons",
            queryset=Person.objects.filter(batch=batch).order_by("id"),
        ),
        ExportedTable(
            table_name="deceased_profiles",
            queryset=DeceasedProfile.objects.filter(person__batch=batch).order_by("id"),
        ),
    ]
    if batch.export_snapshot_id:
        tables.insert(
            1,
            ExportedTable(
                table_name="export_snapshots",
                queryset=ExportSnapshot.objects.filter(pk=batch.export_snapshot_id).order_by("id"),
            ),
        )
    return tables


def _write_table_files(*, table: ExportedTable, csv_dir: Path, jsonl_dir: Path) -> dict:
    model = table.queryset.model
    field_names = [field.attname for field in model._meta.concrete_fields]
    csv_path = csv_dir / f"{table.table_name}.csv"
    jsonl_path = jsonl_dir / f"{table.table_name}.jsonl"
    row_count = 0

    with csv_path.open("w", encoding="utf-8", newline="") as csv_handle, jsonl_path.open(
        "w", encoding="utf-8"
    ) as jsonl_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=field_names)
        writer.writeheader()
        for raw_row in table.queryset.values(*field_names).iterator():
            json_row = {
                field_name: _serialize_value(value, for_csv=False)
                for field_name, value in raw_row.items()
            }
            csv_row = {
                field_name: _serialize_value(value, for_csv=True)
                for field_name, value in raw_row.items()
            }
            writer.writerow(csv_row)
            jsonl_handle.write(json.dumps(json_row, ensure_ascii=False) + "\n")
            row_count += 1

    return {
        "table_name": table.table_name,
        "row_count": row_count,
        "csv_file": f"csv/{table.table_name}.csv",
        "jsonl_file": f"jsonl/{table.table_name}.jsonl",
        "field_names": field_names,
    }


def _serialize_value(value: object, *, for_csv: bool) -> object:
    if value is None:
        return "" if for_csv else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True) if for_csv else value
    return value
