from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def _runtime_module():
    from . import source_registry_runtime

    return source_registry_runtime


def _json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _timestamp(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _analysis_snapshot_id(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- snapshot_id: `") and line.endswith("`"):
            return line.removeprefix("- snapshot_id: `").removesuffix("`")
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_source_entry(source_id: str | None) -> dict | None:
    try:
        return _runtime_module()._source_runtime_module().resolve_source_entry(source_id)
    except _runtime_module()._REGISTRY_ERRORS:
        return None


def resolve_source_entry(source_id: str | None = None) -> dict:
    requested_source_id = (source_id or "").strip() or None
    runtime = _runtime_module()._source_runtime_module()
    source = runtime.get_source(requested_source_id)
    path = Path(source["path"])
    resolved_path = path if path.is_absolute() else _runtime_module()._current_base_dir() / path
    return {
        **source,
        "resolved_path": resolved_path,
    }


def registered_sources(selected_source_id: str | None = None) -> list[dict]:
    runtime = _runtime_module()._source_runtime_module()
    resolved_selected = runtime.resolve_source_entry(selected_source_id)["source_id"]
    default_id = runtime.registry_default_source_id()
    rows = []
    for source in runtime.list_sources():
        path = Path(source["path"])
        resolved_path = path if path.is_absolute() else _runtime_module()._current_base_dir() / path
        rows.append(
            {
                **source,
                "resolved_path": resolved_path,
                "exists": resolved_path.exists(),
                "is_default": source["source_id"] == default_id,
                "selected": source["source_id"] == resolved_selected,
            }
        )
    return rows


def source_summary(source_id: str | None = None) -> dict:
    runtime = _runtime_module()._source_runtime_module()
    source = runtime.resolve_source_entry(source_id)
    resolved_path = source.get("resolved_path")
    if resolved_path is None:
        file_path = source.get("file_path")
        if file_path:
            path = Path(file_path)
        else:
            path = _runtime_module().private_sources_root() / "db.mdb"
    else:
        path = Path(resolved_path)
    exists = path.exists()
    default_id = runtime.registry_default_source_id()
    return {
        "source_id": source["source_id"],
        "label": source.get("label", source["source_id"]),
        "status": source.get("status", "registered"),
        "is_default": source["source_id"] == default_id,
        "notes": source.get("notes", ""),
        "path": path,
        "resolved_path": path,
        "exists": exists,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if exists else None,
        "sha256": _sha256(path) if exists else None,
    }
