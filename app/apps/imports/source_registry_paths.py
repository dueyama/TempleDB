from __future__ import annotations

from pathlib import Path

from config import runtime_paths
from config.runtime_paths import (
    analysis_root as runtime_analysis_root,
)
from config.runtime_paths import (
    exports_root as runtime_exports_root,
)
from config.runtime_paths import (
    prepared_root as runtime_prepared_root,
)
from config.runtime_paths import (
    private_sources_root as runtime_private_sources_root,
)


def _current_base_dir() -> Path:
    return runtime_paths.tenant_root()


def private_sources_root() -> Path:
    return runtime_private_sources_root()


def originaldb_root() -> Path:
    return private_sources_root()


def _legacy_source_resolved_path(file_path: str | None) -> Path:
    raw_path = (file_path or "").strip()
    path = Path(raw_path) if raw_path else private_sources_root() / "db.mdb"
    return path if path.is_absolute() else _current_base_dir() / path


def _resolved_source_path(source: dict | None, *, legacy_file_path: str | None = None) -> Path:
    if source is not None:
        resolved_path = source.get("resolved_path")
        if resolved_path:
            return Path(resolved_path)
        raw_path = (source.get("path") or source.get("file_path") or "").strip()
        if raw_path:
            path = Path(raw_path)
            return path if path.is_absolute() else _current_base_dir() / path
    return _legacy_source_resolved_path(legacy_file_path)


def current_source_path(source_id: str | None = None, *, legacy_file_path: str | None = None) -> Path:
    from .source_registry_catalog import _registry_source_entry

    registry_source = _registry_source_entry(source_id)
    return _resolved_source_path(registry_source, legacy_file_path=legacy_file_path)


def source_mdb_path(source_id: str | None = None) -> Path:
    from .source_registry_catalog import resolve_source_entry

    return resolve_source_entry(source_id)["resolved_path"]


def export_root(source_id: str) -> Path:
    return runtime_exports_root() / source_id


def prepared_root(source_id: str) -> Path:
    return runtime_prepared_root() / source_id


def analysis_root() -> Path:
    return runtime_analysis_root()


def analysis_dir(source_id: str) -> Path:
    return analysis_root() / source_id


def _relative_source_workspace_path(path: Path) -> Path:
    try:
        relative_to_base = path.relative_to(_current_base_dir())
    except ValueError as exc:
        raise ValueError("MDB path must be inside the project workspace.") from exc
    parts = relative_to_base.parts
    if parts[:3] == ("data", "private", "sources"):
        return relative_to_base
    raise ValueError("MDB path must be under data/private/sources/.")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_current_base_dir()))
    except ValueError:
        return str(path)
