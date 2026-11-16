from __future__ import annotations

import json

from . import (
    source_registry_catalog,
    source_registry_paths,
    source_registry_registration,
)

_REGISTRY_ERRORS = (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError, AssertionError)


def _source_runtime_module():
    from . import source_runtime

    return source_runtime


def _current_base_dir():
    return source_registry_paths._current_base_dir()


def _json(path):
    return source_registry_catalog._json(path)


def _timestamp(path):
    return source_registry_catalog._timestamp(path)


def _analysis_snapshot_id(path):
    return source_registry_catalog._analysis_snapshot_id(path)


def _sha256(path):
    return source_registry_catalog._sha256(path)


def _registry_source_entry(source_id):
    return source_registry_catalog._registry_source_entry(source_id)


def _resolved_source_path(source, *, legacy_file_path=None):
    return source_registry_paths._resolved_source_path(source, legacy_file_path=legacy_file_path)


def current_source_path(source_id: str | None = None, *, legacy_file_path: str | None = None):
    return source_registry_paths.current_source_path(source_id, legacy_file_path=legacy_file_path)


def resolve_source_entry(source_id: str | None = None):
    return source_registry_catalog.resolve_source_entry(source_id)


def registered_sources(selected_source_id: str | None = None):
    return source_registry_catalog.registered_sources(selected_source_id)


def remove_registered_source(source_id: str):
    return source_registry_registration.remove_registered_source(source_id)


def source_mdb_path(source_id: str | None = None):
    return source_registry_paths.source_mdb_path(source_id)


def export_root(source_id: str):
    return source_registry_paths.export_root(source_id)


def prepared_root(source_id: str):
    return source_registry_paths.prepared_root(source_id)


def analysis_root():
    return source_registry_paths.analysis_root()


def analysis_dir(source_id: str):
    return source_registry_paths.analysis_dir(source_id)


def source_summary(source_id: str | None = None):
    return source_registry_catalog.source_summary(source_id)


def private_sources_root():
    return source_registry_paths.private_sources_root()


def originaldb_root():
    return source_registry_paths.originaldb_root()


def _source_input_roots():
    return source_registry_registration._source_input_roots()


def _relative_source_workspace_path(path):
    return source_registry_paths._relative_source_workspace_path(path)


def _display_path(path):
    return source_registry_paths._display_path(path)


def _suggest_source_id(path, taken_ids):
    return source_registry_registration._suggest_source_id(path, taken_ids)


def discover_source_files(selected_source_id: str | None = None):
    return source_registry_registration.discover_source_files(selected_source_id)


def discover_originaldb_mdbs(selected_source_id: str | None = None):
    return source_registry_registration.discover_originaldb_mdbs(selected_source_id)


def register_source_file(relative_path: str, *, make_default: bool = False):
    return source_registry_registration.register_source_file(relative_path, make_default=make_default)


def register_originaldb_source(relative_path: str, *, make_default: bool = False):
    return source_registry_registration.register_originaldb_source(
        relative_path,
        make_default=make_default,
    )


def set_default_source(source_id: str):
    return source_registry_registration.set_default_source(source_id)
