from __future__ import annotations

import platform
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

import django
from django.apps import apps
from django.db import connection as default_connection

from apps.core.models import (
    DATABASE_BACKUP_ENGINE_CHOICES,
    DATABASE_BACKUP_STATUS_CHOICES,
    DATABASE_BACKUP_TRIGGER_CHOICES,
    DATABASE_BACKUP_VERIFICATION_TRIGGER_CHOICES,
    DATABASE_RUNTIME_KIND_CHOICES,
)

from .schema_map_database_catalog import build_database_catalog

SNAPSHOT_FORMAT_VERSION = 2
REDACTED_VALUE = "<redacted>"
UNKNOWN_VALUE = "unknown"
SAFE_SCHEMA_NAMES = {"main", "public"}
SAFE_APP_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
SAFE_MIGRATION_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_]{1,255}\Z")
SAFE_NUMERIC_DEFAULT_PATTERN = re.compile(
    r"'?(?:[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'?"
    r"(?:::(?:smallint|integer|bigint|numeric|decimal|real|double precision))?\Z",
    re.IGNORECASE,
)
SAFE_BOOLEAN_DEFAULT_PATTERN = re.compile(
    r"'?(?:true|false)'?(?:::boolean)?\Z",
    re.IGNORECASE,
)
SAFE_SEQUENCE_DEFAULT_PATTERN = re.compile(
    r"nextval\('[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?'::regclass\)\Z",
    re.IGNORECASE,
)
SAFE_TEMPORAL_DEFAULTS = {"now()", "current_timestamp", "current_timestamp()"}

RUNTIME_KIND_VALUES = {str(value) for value, _label in DATABASE_RUNTIME_KIND_CHOICES}
BACKUP_ENGINE_VALUES = {str(value) for value, _label in DATABASE_BACKUP_ENGINE_CHOICES}
BACKUP_STATUS_VALUES = {str(value) for value, _label in DATABASE_BACKUP_STATUS_CHOICES}
BACKUP_TRIGGER_VALUES = {str(value) for value, _label in DATABASE_BACKUP_TRIGGER_CHOICES}
VERIFICATION_TRIGGER_VALUES = {
    str(value) for value, _label in DATABASE_BACKUP_VERIFICATION_TRIGGER_CHOICES
}
DATABASE_ENGINES_BY_VENDOR = {
    "postgresql": "django.db.backends.postgresql",
    "sqlite": "django.db.backends.sqlite3",
}


def build_runtime_snapshot(database_connection=None) -> dict[str, object]:
    """Build a deterministic, aggregate-only snapshot of the current runtime.

    The snapshot intentionally contains no database name, filesystem path,
    hostname, user name, credentials, source registry, tenant identity, or
    application row values. Database access is limited to schema introspection,
    aggregate counts, and a small allowlist of operational status columns.
    """

    database_connection = database_connection or default_connection
    physical_catalog = build_database_catalog(database_connection)
    table_names = {
        str(table["name"])
        for table in physical_catalog["tables"]
        if table["kind"] == "table"
    }

    return {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "django": {"version": django.get_version()},
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "database": {
            "vendor": str(database_connection.vendor),
            "engine": DATABASE_ENGINES_BY_VENDOR.get(
                str(database_connection.vendor), UNKNOWN_VALUE
            ),
            "runtime_kind": _runtime_kind(database_connection, table_names),
        },
        "migrations": _applied_migrations(database_connection, table_names),
        "model_counts": _managed_model_counts(database_connection, table_names),
        "backup": _backup_status(database_connection, table_names),
        "schema": _sanitized_schema(physical_catalog),
    }


def _runtime_kind(database_connection, table_names: set[str]) -> str:
    table_name = "core_databaseruntimeidentity"
    if table_name not in table_names:
        return "unknown"

    quoted_table = database_connection.ops.quote_name(table_name)
    with database_connection.cursor() as cursor:
        cursor.execute(
            f"SELECT runtime_kind FROM {quoted_table} "
            "ORDER BY singleton_key ASC LIMIT 1"
        )
        row = cursor.fetchone()
    return _allowed_choice(row[0] if row else None, RUNTIME_KIND_VALUES)


def _applied_migrations(
    database_connection,
    table_names: set[str],
) -> dict[str, object]:
    table_name = "django_migrations"
    items: list[dict[str, str]] = []
    if table_name in table_names:
        quoted_table = database_connection.ops.quote_name(table_name)
        with database_connection.cursor() as cursor:
            cursor.execute(
                f"SELECT app, name FROM {quoted_table} ORDER BY app ASC, name ASC"
            )
            items = [
                {
                    "app": _safe_identifier(app_label, SAFE_APP_IDENTIFIER_PATTERN),
                    "name": _safe_identifier(
                        migration_name,
                        SAFE_MIGRATION_IDENTIFIER_PATTERN,
                    ),
                }
                for app_label, migration_name in cursor.fetchall()
            ]
    return {"count": len(items), "applied": items}


def _managed_model_counts(
    database_connection,
    table_names: set[str],
) -> dict[str, object]:
    model_entries = []
    for model in apps.get_models(include_auto_created=False):
        options = model._meta
        table_name = str(options.db_table)
        if (
            not options.managed
            or options.proxy
            or options.swapped
            or table_name not in table_names
        ):
            continue
        model_entries.append(
            {
                "model": str(options.label_lower),
                "table": table_name,
                "count": _table_row_count(database_connection, table_name),
            }
        )
    model_entries.sort(key=lambda item: (item["model"], item["table"]))
    return {"count": len(model_entries), "models": model_entries}


def _table_row_count(database_connection, table_name: str) -> int:
    quoted_table = database_connection.ops.quote_name(table_name)
    with database_connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {quoted_table}")
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _backup_status(
    database_connection,
    table_names: set[str],
) -> dict[str, object]:
    return {
        "latest_backup": _latest_backup(database_connection, table_names),
        "latest_test_restore": _latest_test_restore(database_connection, table_names),
    }


def _latest_backup(
    database_connection,
    table_names: set[str],
) -> dict[str, object] | None:
    table_name = "core_databasebackuprun"
    if table_name not in table_names:
        return None

    quoted_table = database_connection.ops.quote_name(table_name)
    with database_connection.cursor() as cursor:
        cursor.execute(
            "SELECT database_engine, trigger_kind, status, started_at, finished_at "
            f"FROM {quoted_table} WHERE database_engine = %s "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            [str(database_connection.vendor)],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _status_payload(row, trigger_values=BACKUP_TRIGGER_VALUES)


def _latest_test_restore(
    database_connection,
    table_names: set[str],
) -> dict[str, object] | None:
    verification_table = "core_databasebackupverificationrun"
    backup_table = "core_databasebackuprun"
    if verification_table not in table_names or backup_table not in table_names:
        return None

    quoted_verification = database_connection.ops.quote_name(verification_table)
    quoted_backup = database_connection.ops.quote_name(backup_table)
    with database_connection.cursor() as cursor:
        cursor.execute(
            "SELECT backup.database_engine, verification.trigger_kind, "
            "verification.status, verification.started_at, verification.finished_at "
            f"FROM {quoted_verification} verification "
            f"INNER JOIN {quoted_backup} backup "
            "ON backup.id = verification.backup_run_id "
            "WHERE backup.database_engine = %s "
            "ORDER BY verification.started_at DESC, verification.id DESC LIMIT 1",
            [str(database_connection.vendor)],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _status_payload(row, trigger_values=VERIFICATION_TRIGGER_VALUES)


def _status_payload(
    row: Iterable[object],
    *,
    trigger_values: set[str],
) -> dict[str, object]:
    database_engine, trigger_kind, status, started_at, finished_at = row
    return {
        "database_engine": _allowed_choice(database_engine, BACKUP_ENGINE_VALUES),
        "trigger_kind": _allowed_choice(trigger_kind, trigger_values),
        "status": _allowed_choice(status, BACKUP_STATUS_VALUES),
        "started_at": _json_datetime(started_at),
        "finished_at": _json_datetime(finished_at),
    }


def _json_datetime(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _sanitized_schema(catalog: Mapping[str, Any]) -> dict[str, object]:
    tables = [_sanitized_table(table) for table in catalog["tables"]]
    groups = [
        {
            "key": str(group["key"]),
            "label": str(group["label"]),
            "object_count": int(group["object_count"]),
            "table_count": int(group["table_count"]),
            "view_count": int(group["view_count"]),
            "column_count": int(group["column_count"]),
            "constraint_count": int(group["constraint_count"]),
            "index_count": int(group["index_count"]),
            "relation_count": int(group["relation_count"]),
            "table_names": [str(table["name"]) for table in group["tables"]],
        }
        for group in catalog["groups"]
    ]
    relations = [
        {
            "id": str(relation["id"]),
            "name": str(relation["name"]),
            "source_table": str(relation["source_table"]),
            "source_group_key": str(relation["source_group_key"]),
            "source_columns": [str(value) for value in relation["source_columns"]],
            "source_column": _optional_string(relation["source_column"]),
            "target_table": str(relation["target_table"]),
            "target_group_key": str(relation["target_group_key"]),
            "target_columns": [str(value) for value in relation["target_columns"]],
            "target_column": str(relation["target_column"]),
            "nullable": bool(relation["nullable"]),
            "required": bool(relation["required"]),
            "unique": bool(relation["unique"]),
            "relation_type": str(relation["relation_type"]),
        }
        for relation in catalog["relations"]
    ]
    counts = {key: int(value) for key, value in catalog["counts"].items()}
    return {
        "schema_name": _safe_schema_name(catalog["schema_name"]),
        "counts": counts,
        "groups": groups,
        "tables": tables,
        "relations": relations,
    }


def _sanitized_table(table: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": str(table["name"]),
        "kind": str(table["kind"]),
        "kind_label": str(table["kind_label"]),
        "group_key": str(table["group_key"]),
        "group_label": str(table["group_label"]),
        "column_count": int(table["column_count"]),
        "constraint_count": int(table["constraint_count"]),
        "index_count": int(table["index_count"]),
        "outgoing_relation_count": int(table["outgoing_relation_count"]),
        "incoming_relation_count": int(table["incoming_relation_count"]),
        "columns": [_sanitized_column(column) for column in table["columns"]],
        "constraints": [
            _sanitized_constraint(constraint) for constraint in table["constraints"]
        ],
    }


def _sanitized_column(column: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": str(column["name"]),
        "position": int(column["position"]),
        "type": str(column["type"]),
        "nullable": bool(column["nullable"]),
        "default": _safe_schema_default(column["default"]),
        "primary_key": bool(column["primary_key"]),
        "unique": bool(column["unique"]),
        "unique_member": bool(column["unique_member"]),
        "indexed": bool(column["indexed"]),
        "checked": bool(column["checked"]),
        "foreign_keys": [
            {
                "table": str(foreign_key["table"]),
                "column": str(foreign_key["column"]),
            }
            for foreign_key in column["foreign_keys"]
        ],
    }


def _sanitized_constraint(constraint: Mapping[str, Any]) -> dict[str, object]:
    foreign_key = constraint["foreign_key"]
    return {
        "name": str(constraint["name"]),
        "columns": [str(column) for column in constraint["columns"]],
        "primary_key": bool(constraint["primary_key"]),
        "unique": bool(constraint["unique"]),
        "index": bool(constraint["index"]),
        "check": bool(constraint["check"]),
        "foreign_key": (
            {
                "table": str(foreign_key["table"]),
                "column": str(foreign_key["column"]),
            }
            if foreign_key
            else None
        ),
        "orders": [str(order) for order in constraint["orders"]],
        "type": str(constraint["type"]),
    }


def _safe_schema_default(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    normalized = text.lower()
    if normalized == "null":
        return "NULL"
    if SAFE_BOOLEAN_DEFAULT_PATTERN.fullmatch(normalized):
        return normalized
    if normalized in SAFE_TEMPORAL_DEFAULTS:
        return normalized
    if SAFE_NUMERIC_DEFAULT_PATTERN.fullmatch(normalized):
        return text
    if SAFE_SEQUENCE_DEFAULT_PATTERN.fullmatch(text):
        return text
    return REDACTED_VALUE


def _safe_schema_name(value: object) -> str:
    text = str(value)
    return text if text in SAFE_SCHEMA_NAMES else REDACTED_VALUE


def _safe_identifier(value: object, pattern: re.Pattern[str]) -> str:
    text = str(value)
    return text if pattern.fullmatch(text) else REDACTED_VALUE


def _allowed_choice(value: object, allowed_values: set[str]) -> str:
    text = str(value) if value is not None else ""
    return text if text in allowed_values else UNKNOWN_VALUE


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = ["SNAPSHOT_FORMAT_VERSION", "build_runtime_snapshot"]
