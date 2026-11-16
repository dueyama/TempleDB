from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path


def _runtime_module():
    from . import source_registry_runtime

    return source_registry_runtime


def _source_input_roots() -> list[Path]:
    return [_runtime_module().private_sources_root()]


def _suggest_source_id(path: Path, taken_ids: set[str]) -> str:
    normalized = unicodedata.normalize("NFKC", path.stem).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug:
        slug = "source"
    candidate = slug
    suffix = 2
    while candidate in taken_ids:
        candidate = f"{slug}-{suffix}"
        suffix += 1
    return candidate


def discover_source_files(selected_source_id: str | None = None) -> list[dict]:
    runtime = _runtime_module()._source_runtime_module()
    roots = [root for root in _source_input_roots() if root.exists()]
    if not roots:
        return []

    default_id = runtime.registry_default_source_id()
    resolved_selected = runtime.resolve_source_entry(selected_source_id)["source_id"]
    registered = []
    registered_by_path = {}
    for source in runtime.list_sources():
        path = Path(source["path"])
        resolved_path = path if path.is_absolute() else _runtime_module()._current_base_dir() / path
        registered.append(source)
        registered_by_path[resolved_path.resolve()] = source

    taken_ids = {source["source_id"] for source in registered}
    rows = []
    seen_paths: set[Path] = set()
    for root in roots:
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() != ".mdb":
                continue
            resolved_path = path.resolve()
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            relative_path = _runtime_module()._display_path(path)
            registered_source = registered_by_path.get(resolved_path)
            if registered_source:
                suggested_source_id = registered_source["source_id"]
            else:
                suggested_source_id = _suggest_source_id(path, taken_ids)
                taken_ids.add(suggested_source_id)
            rows.append(
                {
                    "file_name": path.name,
                    "relative_path": relative_path,
                    "suggested_source_id": suggested_source_id,
                    "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
                    "registered": registered_source is not None,
                    "source_id": registered_source["source_id"] if registered_source else None,
                    "label": registered_source.get("label") if registered_source else path.stem,
                    "status": registered_source.get("status", "registered") if registered_source else "detected",
                    "is_default": (
                        registered_source["source_id"] == default_id if registered_source else False
                    ),
                    "selected": (
                        registered_source["source_id"] == resolved_selected if registered_source else False
                    ),
                }
            )
    return rows


def discover_originaldb_mdbs(selected_source_id: str | None = None) -> list[dict]:
    return discover_source_files(selected_source_id)


def remove_registered_source(source_id: str) -> dict:
    return _runtime_module()._source_runtime_module().registry_remove_source(source_id)


def register_source_file(relative_path: str, *, make_default: bool = False) -> dict:
    runtime = _runtime_module()._source_runtime_module()
    relative_path = (relative_path or "").strip()
    if not relative_path:
        raise ValueError("MDB path is required.")
    path = Path(relative_path)
    resolved_path = path if path.is_absolute() else _runtime_module()._current_base_dir() / path
    if not resolved_path.exists():
        raise FileNotFoundError(f"MDB not found: {relative_path}")
    if resolved_path.suffix.lower() != ".mdb":
        raise ValueError("Only .mdb files can be registered.")
    relative_to_base = _runtime_module()._relative_source_workspace_path(resolved_path)

    for source in runtime.list_sources():
        registered_path = Path(source["path"])
        candidate = (
            registered_path
            if registered_path.is_absolute()
            else _runtime_module()._current_base_dir() / registered_path
        )
        if candidate.resolve() == resolved_path.resolve():
            if make_default:
                runtime.registry_set_default_source(source["source_id"])
            return runtime.resolve_source_entry(source["source_id"])

    source_id = _suggest_source_id(
        resolved_path,
        {source["source_id"] for source in runtime.list_sources()},
    )
    notes = f"Registered from imports console on {datetime.now().strftime('%Y-%m-%d')}."
    stored = runtime.upsert_source(
        {
            "source_id": source_id,
            "label": resolved_path.stem,
            "path": str(relative_to_base),
            "status": "primary" if make_default else "registered",
            "notes": notes,
        },
        make_default=make_default,
    )
    return runtime.resolve_source_entry(stored["source_id"])


def register_originaldb_source(relative_path: str, *, make_default: bool = False) -> dict:
    return register_source_file(relative_path, make_default=make_default)


def set_default_source(source_id: str) -> dict:
    runtime = _runtime_module()._source_runtime_module()
    source_id = (source_id or "").strip()
    if not source_id:
        raise ValueError("source_id is required.")
    stored = runtime.registry_set_default_source(source_id)
    return runtime.resolve_source_entry(stored["source_id"])
