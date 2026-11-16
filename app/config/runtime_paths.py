from __future__ import annotations

import os
from pathlib import Path

from config.env import load_env_file
from config.instance_runtime import PLATFORM_ROOT, selected_instance


def _load_selected_instance_environment(
    *,
    platform_root: Path = PLATFORM_ROOT,
) -> None:
    if os.environ.get("TEMPLEDB_TENANT_ROOT", "").strip():
        load_env_file(platform_root=platform_root)
        return
    selection = selected_instance(platform_root=platform_root)
    if selection is not None:
        load_env_file(platform_root=platform_root)


_load_selected_instance_environment()

BASE_DIR = PLATFORM_ROOT


def _configured_tenant_root() -> Path:
    raw_value = os.environ.get("TEMPLEDB_TENANT_ROOT", "").strip()
    if not raw_value:
        return BASE_DIR
    configured = Path(raw_value).expanduser()
    if not configured.is_absolute():
        raise RuntimeError("TEMPLEDB_TENANT_ROOT must be an absolute path.")
    return Path(os.path.abspath(configured))


TENANT_ROOT = _configured_tenant_root()
TENANT_PREFERENCES_ROOT = TENANT_ROOT / "config" / "tenant_preferences"
GENERATED_ROOT = TENANT_ROOT / "data" / "generated"
RUNTIME_ROOT = TENANT_ROOT / "data" / "runtime"
PRIVATE_ROOT = TENANT_ROOT / "data" / "private"
PRIVATE_SOURCES_ROOT = PRIVATE_ROOT / "sources"
PRIVATE_AUXILIARY_ROOT = PRIVATE_ROOT / "auxiliary"
PRIVATE_CREDENTIALS_ROOT = PRIVATE_ROOT / "credentials"
RUNTIME_SOURCE_REGISTRY_PATH = RUNTIME_ROOT / "source_registry.json"
EXPORTS_ROOT = GENERATED_ROOT / "legacy_exports"
PREPARED_ROOT = GENERATED_ROOT / "prepared_exports"
ANALYSIS_ROOT = GENERATED_ROOT / "analysis_outputs"
IMPORT_RUNS_ROOT = GENERATED_ROOT / "import_runs"
PORTABLE_EXPORTS_ROOT = GENERATED_ROOT / "portable_exports"
SQLITE_DB_PATH = RUNTIME_ROOT / "dev.sqlite3"


def tenant_root() -> Path:
    return TENANT_ROOT


def tenant_preferences_root() -> Path:
    return TENANT_PREFERENCES_ROOT


def generated_root() -> Path:
    return GENERATED_ROOT


def runtime_root() -> Path:
    return RUNTIME_ROOT


def private_root() -> Path:
    return PRIVATE_ROOT


def private_sources_root() -> Path:
    return PRIVATE_SOURCES_ROOT


def private_auxiliary_root() -> Path:
    return PRIVATE_AUXILIARY_ROOT


def private_credentials_root() -> Path:
    return PRIVATE_CREDENTIALS_ROOT


def runtime_source_registry_path() -> Path:
    return RUNTIME_SOURCE_REGISTRY_PATH


def exports_root() -> Path:
    return EXPORTS_ROOT


def prepared_root() -> Path:
    return PREPARED_ROOT


def analysis_root() -> Path:
    return ANALYSIS_ROOT


def import_runs_root() -> Path:
    return IMPORT_RUNS_ROOT


def portable_exports_root() -> Path:
    return PORTABLE_EXPORTS_ROOT


def sqlite_db_path() -> Path:
    return SQLITE_DB_PATH
