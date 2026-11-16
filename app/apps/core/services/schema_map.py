from __future__ import annotations

from collections import defaultdict

from django.apps import apps as django_apps

from . import (
    schema_map_business,
    schema_map_database_catalog,
    schema_map_mermaid,
    schema_map_model_catalog,
)

SCHEMA_MAP_APP_LABELS = ("core", "imports")


def build_database_catalog(database_connection=None) -> dict[str, object]:
    """Return the physical schema for the currently connected database."""

    return schema_map_database_catalog.build_database_catalog(database_connection)


def build_schema_map(app_labels: tuple[str, ...] = SCHEMA_MAP_APP_LABELS) -> dict[str, object]:
    models = schema_map_model_catalog._collect_models(app_labels)
    model_lookup = {str(model["label"]): model for model in models}
    relation_index: dict[str, list[dict[str, object]]] = defaultdict(list)
    relation_lines: list[str] = []

    for model in models:
        for relation in model["relations"]:
            related_label = str(relation["related_model_label"])
            relation_index[related_label].append(
                {
                    "from_model_label": model["label"],
                    "from_model_name": model["name"],
                    "field_name": relation["field_name"],
                    "relation_type": relation["relation_type"],
                    "nullable": relation["nullable"],
                }
            )
            relation_lines.append(str(relation["mermaid_line"]))

    apps_payload: list[dict[str, object]] = []
    total_model_count = 0
    for app_label in app_labels:
        app_models = [model for model in models if model["app_label"] == app_label]
        if not app_models:
            continue
        for model in app_models:
            model["incoming_relations"] = sorted(
                relation_index.get(str(model["label"]), []),
                key=lambda item: (str(item["from_model_name"]), str(item["field_name"])),
            )
        app_config = django_apps.get_app_config(app_label)
        apps_payload.append(
            {
                "app_label": app_label,
                "app_verbose_name": str(app_config.verbose_name),
                "model_count": len(app_models),
                "models": app_models,
            }
        )
        total_model_count += len(app_models)

    relation_line_set = sorted(set(relation_lines))
    return {
        "apps": apps_payload,
        "app_count": len(apps_payload),
        "model_count": total_model_count,
        "relation_count": len(relation_line_set),
        "business_flows": schema_map_business._build_business_flows(model_lookup),
        "business_groups": schema_map_business._build_business_groups(model_lookup),
        "mermaid_source": schema_map_mermaid._build_mermaid_source(apps_payload, relation_line_set),
    }


BUSINESS_SCHEMA_GROUPS = schema_map_business.BUSINESS_SCHEMA_GROUPS
BUSINESS_SCHEMA_FLOWS = schema_map_business.BUSINESS_SCHEMA_FLOWS
BUSINESS_MODEL_METADATA = schema_map_business.BUSINESS_MODEL_METADATA
