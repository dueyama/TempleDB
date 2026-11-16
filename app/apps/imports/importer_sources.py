from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from config.runtime_paths import exports_root, prepared_root, tenant_root
from config.source_registry import default_source_id, get_source

from .models import ExportSnapshot, LegacySource


def resolve_source_entry(source_id: str | None = None) -> dict:
    source = get_source(source_id)
    path = Path(source["path"])
    resolved_path = path if path.is_absolute() else tenant_root() / path
    return {
        **source,
        "resolved_path": resolved_path,
    }


def resolve_export_snapshot(source_id: str, snapshot_id: str | None = None) -> dict:
    source_root = exports_root() / source_id
    resolved_snapshot_id = (
        snapshot_id or _load_json(source_root / "latest.json")["latest_snapshot_id"]
    )
    snapshot_dir = source_root / resolved_snapshot_id
    manifest = _load_json(snapshot_dir / "manifest.json")
    return {
        "source_id": source_id,
        "snapshot_id": resolved_snapshot_id,
        "snapshot_dir": snapshot_dir,
        "manifest": manifest,
        "log_path": snapshot_dir / "export.log",
    }


def resolve_prepared_snapshot(source_id: str, snapshot_id: str | None = None) -> dict:
    source_root = prepared_root() / source_id
    resolved_snapshot_id = (
        snapshot_id or _load_json(source_root / "latest.json")["latest_snapshot_id"]
    )
    prepared_dir = source_root / resolved_snapshot_id
    manifest = _load_json(prepared_dir / "raw_manifest.json")
    return {
        "source_id": source_id,
        "snapshot_id": resolved_snapshot_id,
        "prepared_dir": prepared_dir,
        "manifest": manifest,
        "raw_manifest_path": prepared_dir / "raw_manifest.json",
    }


def sync_legacy_source(
    source_entry: dict,
    *,
    authorized_primary_source_id: str | None = None,
) -> LegacySource:
    resolved_path = source_entry["resolved_path"]
    exists = resolved_path.exists()
    sha256 = _sha256(resolved_path) if exists else ""
    defaults = {
        "label": source_entry.get("label", ""),
        "file_path": str(resolved_path),
        "file_name": resolved_path.name,
        "sha256": sha256,
        "status": source_entry.get("status", "registered"),
        "notes": source_entry.get("notes", ""),
    }
    if authorized_primary_source_id is not None:
        if source_entry["source_id"] != authorized_primary_source_id:
            raise ValueError("Authorized primary source changed before import.")
        primary_sources = list(
            LegacySource.objects.select_for_update().filter(is_primary=True).order_by("source_id")
        )
        if (
            len(primary_sources) != 1
            or primary_sources[0].source_id != authorized_primary_source_id
        ):
            raise ValueError("DB primary source changed before import.")
        source = primary_sources[0]
        current_path = Path(source.file_path)
        if not current_path.is_absolute():
            current_path = tenant_root() / current_path
        if current_path.resolve(strict=False) != Path(resolved_path).resolve(strict=False):
            raise ValueError("DB primary source path changed before import.")
        for field_name, value in defaults.items():
            setattr(source, field_name, value)
        source.save(update_fields=[*defaults, "updated_at"])
        return source

    defaults["is_primary"] = source_entry["source_id"] == _default_source_id()
    return LegacySource.objects.update_or_create(
        source_id=source_entry["source_id"],
        defaults=defaults,
    )[0]


def sync_export_snapshot(*, source: LegacySource, export_snapshot: dict) -> ExportSnapshot:
    manifest = export_snapshot["manifest"]
    created_at_text = manifest.get("snapshot", {}).get("created_at")
    created_at = _parse_datetime(created_at_text)
    return ExportSnapshot.objects.update_or_create(
        source=source,
        snapshot_id=export_snapshot["snapshot_id"],
        defaults={
            "export_dir": str(export_snapshot["snapshot_dir"]),
            "manifest_path": str(export_snapshot["snapshot_dir"] / "manifest.json"),
            "log_path": str(export_snapshot.get("log_path") or ""),
            "source_created_at": created_at,
            "table_count": manifest.get("export_settings", {}).get("table_count", 0),
            "null_token": manifest.get("export_settings", {}).get("null_token", "__MDB_NULL__"),
            "manifest": manifest,
        },
    )[0]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_source_id() -> str:
    return default_source_id()
