from __future__ import annotations

from django.apps import apps as django_apps
from django.db.models import Field, Model


def _collect_models(app_labels: tuple[str, ...]) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        for model in app_config.get_models():
            collected.append(_build_model_entry(model))
    collected.sort(key=lambda item: (str(item["app_label"]), str(item["name"])))
    return collected


def _build_model_entry(model: type[Model]) -> dict[str, object]:
    field_entries = [_build_field_entry(field) for field in _iter_direct_fields(model)]
    relation_entries = [_build_relation_entry(model, field) for field in _iter_relation_fields(model)]
    return {
        "app_label": model._meta.app_label,
        "name": model.__name__,
        "label": _model_label(model),
        "db_table": model._meta.db_table,
        "field_count": len(field_entries),
        "relation_count": len(relation_entries),
        "fields": field_entries,
        "relations": relation_entries,
        "incoming_relations": [],
    }


def _iter_direct_fields(model: type[Model]) -> list[Field]:
    direct_fields = list(model._meta.fields)
    direct_fields.extend(model._meta.many_to_many)
    return direct_fields


def _iter_relation_fields(model: type[Model]) -> list[Field]:
    return [
        field
        for field in model._meta.get_fields()
        if field.is_relation and not field.auto_created and getattr(field, "related_model", None) is not None
    ]


def _build_field_entry(field: Field) -> dict[str, object]:
    return {
        "name": field.name,
        "type_label": _field_type_label(field),
        "null": bool(getattr(field, "null", False)),
        "blank": bool(getattr(field, "blank", False)),
        "primary_key": bool(getattr(field, "primary_key", False)),
        "unique": bool(getattr(field, "unique", False)),
        "is_relation": bool(field.is_relation),
    }


def _build_relation_entry(model: type[Model], field: Field) -> dict[str, object]:
    related_model = field.related_model
    assert related_model is not None
    relation_type = _relation_type(field)
    return {
        "field_name": field.name,
        "relation_type": relation_type,
        "nullable": bool(getattr(field, "null", False)),
        "related_model_name": related_model.__name__,
        "related_model_label": _model_label(related_model),
        "mermaid_line": _relation_mermaid_line(model, field, related_model),
    }


def _field_type_label(field: Field) -> str:
    if field.many_to_many:
        return "ManyToMany"
    if field.one_to_one:
        return "OneToOne"
    if field.many_to_one:
        return "ForeignKey"
    return field.get_internal_type()


def _relation_type(field: Field) -> str:
    if field.many_to_many:
        return "many-to-many"
    if field.one_to_one:
        return "one-to-one"
    if field.many_to_one:
        return "many-to-one"
    return "relation"


def _relation_mermaid_line(model: type[Model], field: Field, related_model: type[Model]) -> str:
    source = model.__name__
    target = related_model.__name__
    if field.many_to_many:
        return f"{source} }}o--o{{ {target} : {field.name}"
    if field.one_to_one:
        return f"{target} ||--|| {source} : {field.name}"
    return f"{target} ||--o{{ {source} : {field.name}"


def _model_label(model: type[Model]) -> str:
    return f"{model._meta.app_label}.{model.__name__}"


__all__ = [
    "_build_field_entry",
    "_build_model_entry",
    "_build_relation_entry",
    "_collect_models",
    "_field_type_label",
    "_iter_direct_fields",
    "_iter_relation_fields",
    "_model_label",
    "_relation_mermaid_line",
    "_relation_type",
]
