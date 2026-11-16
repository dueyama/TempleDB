from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from . import (
    operational_source_bootstrap as operational_source_bootstrap_owner,
)
from . import (
    operational_source_records as operational_source_records_owner,
)
from . import (
    operational_source_status as operational_source_status_owner,
)

# Owner modules resolve these registry dependencies through the facade at call time.
from .source_registry_runtime import (
    _REGISTRY_ERRORS as _REGISTRY_ERRORS,
)
from .source_registry_runtime import (
    _registry_source_entry as _registry_source_entry,
)
from .source_registry_runtime import (
    _resolved_source_path as _resolved_source_path,
)
from .source_registry_runtime import (
    _sha256 as _sha256,
)

_DB_LOOKUP_ERRORS = (OperationalError, ProgrammingError)


def _source_runtime_module():
    from . import source_runtime

    return source_runtime


def source_summary(source_id: str | None = None) -> dict:
    return _source_runtime_module().source_summary(source_id)


def resolve_source_entry(source_id: str | None = None) -> dict:
    return _source_runtime_module().resolve_source_entry(source_id)


def log_source_operation(**kwargs):
    return _source_runtime_module().log_source_operation(**kwargs)


def _primary_legacy_source_record():
    return operational_source_records_owner._primary_legacy_source_record()


def _source_entry_from_legacy_source(source_record):
    return operational_source_records_owner._source_entry_from_legacy_source(source_record)


def _ensure_legacy_source_from_registry(source_id: str | None = None, *, force_primary: bool):
    return operational_source_records_owner._ensure_legacy_source_from_registry(
        source_id,
        force_primary=force_primary,
    )


def _latest_operational_source_bootstrap_log(source_record):
    return operational_source_records_owner._latest_operational_source_bootstrap_log(source_record)


def _operational_source_warning_message(source_id: str, registry_default_id: str | None) -> str:
    return operational_source_bootstrap_owner._operational_source_warning_message(
        source_id,
        registry_default_id,
    )


def ensure_operational_source_record(source_id: str | None = None):
    return operational_source_bootstrap_owner.ensure_operational_source_record(source_id)


def operational_source_id(source_id: str | None = None) -> str:
    return operational_source_status_owner.operational_source_id(source_id)


def resolve_operational_source_entry(source_id: str | None = None) -> dict:
    return operational_source_status_owner.resolve_operational_source_entry(source_id)


def operational_source_summary(source_id: str | None = None) -> dict:
    return operational_source_status_owner.operational_source_summary(source_id)


def operational_source_status(source_id: str | None = None) -> dict:
    return operational_source_status_owner.operational_source_status(source_id)
