from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.db import connection as default_connection

GROUP_DEFINITIONS = (
    ("imports", "TempleDB 業務・取込"),
    ("core", "TempleDB 基盤"),
    ("framework", "Django 内部"),
    ("other", "その他"),
)
SUPPORTED_VENDORS = {"postgresql", "sqlite"}


def build_database_catalog(database_connection=None) -> dict[str, object]:
    """Return the physical schema visible to a PostgreSQL or SQLite connection.

    All database access in this function goes through Django's read-only
    introspection API (plus ``current_schema()`` on PostgreSQL). It never runs
    DDL or data-changing SQL.
    """

    database_connection = database_connection or default_connection
    vendor = str(database_connection.vendor)
    if vendor not in SUPPORTED_VENDORS:
        raise NotImplementedError(f"Unsupported database vendor: {vendor}")

    with database_connection.cursor() as cursor:
        schema_name = _schema_name(database_connection, cursor)
        table_infos = sorted(
            database_connection.introspection.get_table_list(cursor),
            key=lambda item: str(item.name),
        )
        tables = [
            _build_table_entry(database_connection, cursor, table_info)
            for table_info in table_infos
        ]

    table_lookup = {str(table["name"]): table for table in tables}
    relations = _attach_relations(tables, table_lookup)
    groups = _build_groups(tables)
    graph_data = _build_graph_data(groups, relations)
    settings_dict = database_connection.settings_dict
    engine = str(settings_dict.get("ENGINE") or "")
    database_name = str(settings_dict.get("NAME") or "")
    table_count = sum(table["kind"] == "table" for table in tables)
    view_count = sum(table["kind"] == "view" for table in tables)
    column_count = sum(int(table["column_count"]) for table in tables)
    constraint_count = sum(int(table["constraint_count"]) for table in tables)
    index_count = sum(int(table["index_count"]) for table in tables)
    relation_count = len(relations)
    counts = {
        "group_count": len(groups),
        "object_count": len(tables),
        "table_count": table_count,
        "view_count": view_count,
        "column_count": column_count,
        "constraint_count": constraint_count,
        "index_count": index_count,
        "relation_count": relation_count,
    }
    return {
        "engine": engine,
        "engine_label": _engine_label(vendor),
        "vendor": vendor,
        "database": database_name,
        "database_name": database_name,
        "schema": schema_name,
        "schema_name": schema_name,
        "counts": counts,
        **counts,
        "groups": groups,
        "tables": tables,
        "relations": relations,
        "graph_data": graph_data,
    }


def _schema_name(database_connection, cursor) -> str:
    if database_connection.vendor == "sqlite":
        return "main"
    cursor.execute("SELECT current_schema()")
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] else "public"


def _build_table_entry(database_connection, cursor, table_info) -> dict[str, object]:
    table_name = str(table_info.name)
    kind = "view" if str(table_info.type) == "v" else "table"
    descriptions = database_connection.introspection.get_table_description(cursor, table_name)
    raw_constraints = database_connection.introspection.get_constraints(cursor, table_name)
    constraints = _build_constraint_entries(raw_constraints)
    constraint_flags = _constraint_flags_by_column(constraints)
    columns = [
        _build_column_entry(
            database_connection,
            description,
            position=position,
            flags=constraint_flags.get(str(description.name), {}),
        )
        for position, description in enumerate(descriptions, start=1)
    ]
    group_key = _group_key(table_name)
    return {
        "name": table_name,
        "kind": kind,
        "kind_label": "ビュー" if kind == "view" else "テーブル",
        "group_key": group_key,
        "group_label": dict(GROUP_DEFINITIONS)[group_key],
        "column_count": len(columns),
        "constraint_count": sum(_is_database_constraint(item) for item in constraints),
        "index_count": sum(bool(constraint["index"]) for constraint in constraints),
        "outgoing_relation_count": 0,
        "incoming_relation_count": 0,
        "columns": columns,
        "constraints": constraints,
        "outgoing_relations": [],
        "incoming_relations": [],
    }


def _is_database_constraint(constraint: Mapping[str, object]) -> bool:
    if constraint["index"]:
        return False
    return bool(
        constraint["primary_key"]
        or constraint["unique"]
        or constraint["check"]
        or constraint["foreign_key"]
    )


def _build_constraint_entries(
    raw_constraints: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, object]]:
    entries = []
    for name, constraint in raw_constraints.items():
        raw_foreign_key = constraint.get("foreign_key")
        foreign_key = None
        if raw_foreign_key:
            target_table, target_column = raw_foreign_key
            foreign_key = {
                "table": str(target_table),
                "column": str(target_column),
            }
        entries.append(
            {
                "name": str(name),
                "columns": [str(column) for column in constraint.get("columns", ()) if column],
                "primary_key": bool(constraint.get("primary_key")),
                "unique": bool(constraint.get("unique")),
                "index": bool(constraint.get("index")),
                "check": bool(constraint.get("check")),
                "foreign_key": foreign_key,
                "orders": [str(order) for order in constraint.get("orders", ()) if order],
                "type": str(constraint.get("type") or ""),
            }
        )
    return sorted(entries, key=lambda item: str(item["name"]))


def _constraint_flags_by_column(
    constraints: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    flags: dict[str, dict[str, object]] = {}
    for constraint in constraints:
        for column in constraint["columns"]:
            column_flags = flags.setdefault(
                str(column),
                {
                    "primary_key": False,
                    "unique": False,
                    "unique_member": False,
                    "indexed": False,
                    "checked": False,
                    "foreign_keys": [],
                },
            )
            column_flags["primary_key"] = bool(
                column_flags["primary_key"] or constraint["primary_key"]
            )
            constraint_is_unique = bool(constraint["unique"])
            column_flags["unique"] = bool(
                column_flags["unique"]
                or (constraint_is_unique and len(constraint["columns"]) == 1)
            )
            column_flags["unique_member"] = bool(
                column_flags["unique_member"] or constraint_is_unique
            )
            column_flags["indexed"] = bool(column_flags["indexed"] or constraint["index"])
            column_flags["checked"] = bool(column_flags["checked"] or constraint["check"])
            if constraint["foreign_key"]:
                column_flags["foreign_keys"].append(constraint["foreign_key"])
    return flags


def _build_column_entry(
    database_connection,
    description,
    *,
    position: int,
    flags: Mapping[str, object],
) -> dict[str, object]:
    primary_key = bool(flags.get("primary_key"))
    foreign_keys = list(flags.get("foreign_keys", []))
    return {
        "name": str(description.name),
        "position": position,
        "type": _column_type_label(database_connection, description),
        "type_code": str(description.type_code),
        "nullable": bool(description.null_ok) and not primary_key,
        "default": None if description.default is None else str(description.default),
        "primary_key": primary_key,
        "unique": bool(flags.get("unique")),
        "unique_member": bool(flags.get("unique_member")),
        "indexed": bool(flags.get("indexed")),
        "checked": bool(flags.get("checked")),
        "foreign_key": foreign_keys[0] if foreign_keys else None,
        "foreign_keys": foreign_keys,
    }


def _column_type_label(database_connection, description) -> str:
    try:
        field_type = str(
            database_connection.introspection.get_field_type(description.type_code, description)
        )
    except (KeyError, TypeError):
        field_type = str(description.type_code or "unknown")

    internal_size = getattr(description, "internal_size", None)
    if internal_size is None:
        internal_size = getattr(description, "display_size", None)
    precision = getattr(description, "precision", None)
    scale = getattr(description, "scale", None)
    if field_type in {"CharField", "BinaryField"} and isinstance(internal_size, int) and internal_size > 0:
        return f"{field_type}({internal_size})"
    if field_type == "DecimalField" and precision is not None and scale is not None:
        return f"{field_type}({precision}, {scale})"
    return field_type


def _attach_relations(
    tables: list[dict[str, object]],
    table_lookup: Mapping[str, dict[str, object]],
) -> list[dict[str, object]]:
    relations: list[dict[str, object]] = []
    for table in tables:
        column_lookup = {str(column["name"]): column for column in table["columns"]}
        unique_sets = {
            frozenset(str(column) for column in constraint["columns"])
            for constraint in table["constraints"]
            if (constraint["primary_key"] or constraint["unique"]) and constraint["columns"]
        }
        for constraint in table["constraints"]:
            foreign_key = constraint["foreign_key"]
            if not foreign_key:
                continue
            source_columns = [str(column) for column in constraint["columns"]]
            target_columns = [str(foreign_key["column"])]
            unique = frozenset(source_columns) in unique_sets
            required = bool(source_columns) and all(
                not bool(column_lookup.get(column, {}).get("nullable", True))
                for column in source_columns
            )
            relation = {
                "id": f"{table['name']}:{constraint['name']}",
                "name": constraint["name"],
                "source_table": table["name"],
                "source_group_key": table["group_key"],
                "source_columns": source_columns,
                "source_column": source_columns[0] if len(source_columns) == 1 else None,
                "target_table": foreign_key["table"],
                "target_group_key": _group_key(str(foreign_key["table"])),
                "target_columns": target_columns,
                "target_column": target_columns[0],
                "nullable": not required,
                "required": required,
                "unique": unique,
                "relation_type": "one-to-one" if unique else "many-to-one",
            }
            relations.append(relation)
            table["outgoing_relations"].append(relation)
            target = table_lookup.get(str(foreign_key["table"]))
            if target is not None:
                target["incoming_relations"].append(relation)

    relations.sort(key=_relation_sort_key)
    for table in tables:
        table["outgoing_relations"].sort(key=_relation_sort_key)
        table["incoming_relations"].sort(key=_relation_sort_key)
        table["outgoing_relation_count"] = len(table["outgoing_relations"])
        table["incoming_relation_count"] = len(table["incoming_relations"])
    return relations


def _relation_sort_key(relation: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(relation["source_table"]),
        str(relation["source_column"] or ""),
        str(relation["target_table"]),
    )


def _build_groups(tables: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = []
    for key, label in GROUP_DEFINITIONS:
        group_tables = [table for table in tables if table["group_key"] == key]
        table_count = sum(table["kind"] == "table" for table in group_tables)
        view_count = sum(table["kind"] == "view" for table in group_tables)
        groups.append(
            {
                "key": key,
                "label": label,
                "object_count": len(group_tables),
                "table_count": table_count,
                "view_count": view_count,
                "column_count": sum(int(table["column_count"]) for table in group_tables),
                "constraint_count": sum(int(table["constraint_count"]) for table in group_tables),
                "index_count": sum(int(table["index_count"]) for table in group_tables),
                "relation_count": sum(
                    int(table["outgoing_relation_count"]) for table in group_tables
                ),
                "tables": group_tables,
            }
        )
    return groups


def _build_graph_data(
    groups: Iterable[Mapping[str, object]],
    relations: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "groups": [
            {
                "key": str(group["key"]),
                "label": str(group["label"]),
                "tables": [
                    {
                        "name": str(table["name"]),
                        "column_count": int(table["column_count"]),
                        "outgoing_relation_count": int(table["outgoing_relation_count"]),
                        "incoming_relation_count": int(table["incoming_relation_count"]),
                    }
                    for table in group["tables"]
                ],
            }
            for group in groups
        ],
        "relations": [
            {
                "source_table": str(relation["source_table"]),
                "source_columns": [str(column) for column in relation["source_columns"]],
                "target_table": str(relation["target_table"]),
                "target_columns": [str(column) for column in relation["target_columns"]],
                "required": bool(relation["required"]),
                "unique": bool(relation["unique"]),
            }
            for relation in relations
        ],
    }


def _group_key(table_name: str) -> str:
    if table_name.startswith("imports_"):
        return "imports"
    if table_name.startswith("core_"):
        return "core"
    if table_name.startswith(("auth_", "django_")):
        return "framework"
    return "other"


def _engine_label(vendor: str) -> str:
    return {"postgresql": "PostgreSQL", "sqlite": "SQLite"}[vendor]


__all__ = ["GROUP_DEFINITIONS", "build_database_catalog"]
