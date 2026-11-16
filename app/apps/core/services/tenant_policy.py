from __future__ import annotations

from pathlib import Path

from config.runtime_paths import tenant_root as runtime_tenant_root

from . import tenant_policy_defaults as _tenant_policy_defaults

DECEASED_FIELD_LABEL_DEFAULTS = _tenant_policy_defaults.DECEASED_FIELD_LABEL_DEFAULTS
IDENTIFIER_LABEL_DEFAULTS = _tenant_policy_defaults.IDENTIFIER_LABEL_DEFAULTS
ROLE_LABEL_DEFAULTS = _tenant_policy_defaults.ROLE_LABEL_DEFAULTS
PRINT_HEADING_LABEL_DEFAULTS = _tenant_policy_defaults.PRINT_HEADING_LABEL_DEFAULTS
ROLE_DOCUMENT_LABEL_DEFAULTS = _tenant_policy_defaults.ROLE_DOCUMENT_LABEL_DEFAULTS
ROLE_NAVIGATION_LABEL_DEFAULTS = _tenant_policy_defaults.ROLE_NAVIGATION_LABEL_DEFAULTS
MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS = (
    _tenant_policy_defaults.MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS
)
MARKER_LABEL_DEFAULTS = _tenant_policy_defaults.MARKER_LABEL_DEFAULTS
LABEL_DEFAULTS = _tenant_policy_defaults.LABEL_DEFAULTS
MAP_LINK_DEFAULTS = _tenant_policy_defaults.MAP_LINK_DEFAULTS
MEMORIAL_NOTICE_DEFAULT_KEYS = _tenant_policy_defaults.MEMORIAL_NOTICE_DEFAULT_KEYS
RELATIONSHIP_LABEL_DEFAULTS = _tenant_policy_defaults.RELATIONSHIP_LABEL_DEFAULTS
SERVICE_SCHEDULE_CATEGORY_DEFAULTS = (
    _tenant_policy_defaults.SERVICE_SCHEDULE_CATEGORY_DEFAULTS
)


class TenantPolicyError(ValueError):
    pass


def tenant_policy_root() -> Path:
    return runtime_tenant_root() / "config" / "tenant_policy" / "default"


def memorial_rules_policy_path() -> Path:
    from . import tenant_policy_memorial_rules

    return tenant_policy_memorial_rules.memorial_rules_policy_path()


def labels_policy_path() -> Path:
    from . import tenant_policy_labels

    return tenant_policy_labels.labels_policy_path()


def memorial_notice_defaults_policy_path() -> Path:
    from . import tenant_policy_memorial_notice

    return tenant_policy_memorial_notice.memorial_notice_defaults_policy_path()


def terminology_policy_path() -> Path:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.terminology_policy_path()


def map_links_policy_path() -> Path:
    from . import tenant_policy_map_links

    return tenant_policy_map_links.map_links_policy_path()


def service_schedule_categories_policy_path() -> Path:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.service_schedule_categories_policy_path()


def relationship_labels_policy_path() -> Path:
    from . import tenant_policy_relationship_labels

    return tenant_policy_relationship_labels.relationship_labels_policy_path()


def normalize_memorial_rules(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "memorial rules",
) -> list[dict]:
    from . import tenant_policy_memorial_rules

    return tenant_policy_memorial_rules.normalize_memorial_rules(payload, context=context)


def normalize_labels(
    payload: dict,
    *,
    context: str = "labels",
) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.normalize_labels(payload, context=context)


def normalize_memorial_notice_defaults(
    payload: dict,
    *,
    context: str = "memorial notice defaults",
) -> dict[str, str]:
    from . import tenant_policy_memorial_notice

    return tenant_policy_memorial_notice.normalize_memorial_notice_defaults(payload, context=context)


def normalize_terminology(
    payload: dict,
    *,
    context: str = "terminology",
) -> dict:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.normalize_terminology(payload, context=context)


def normalize_map_links(
    payload: dict,
    *,
    context: str = "map links",
) -> dict:
    from . import tenant_policy_map_links

    return tenant_policy_map_links.normalize_map_links(payload, context=context)


def normalize_service_schedule_categories(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "service schedule categories",
) -> list[dict]:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.normalize_service_schedule_categories(
        payload,
        context=context,
    )


def normalize_relationship_labels(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "relationship labels",
) -> list[dict]:
    from . import tenant_policy_relationship_labels

    return tenant_policy_relationship_labels.normalize_relationship_labels(
        payload,
        context=context,
    )


def load_memorial_rules(*, path: Path | None = None) -> list[dict]:
    from . import tenant_policy_memorial_rules

    return tenant_policy_memorial_rules.load_memorial_rules(path=path)


def get_memorial_rules(
    *,
    fallback_rules: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    from . import tenant_policy_memorial_rules

    return tenant_policy_memorial_rules.get_memorial_rules(
        fallback_rules=fallback_rules,
        path=path,
    )


def load_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.load_labels(path=path)


def get_labels(
    *,
    fallback_labels: dict[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.get_labels(fallback_labels=fallback_labels, path=path)


def get_label(
    key: str,
    default: str,
    *,
    path: Path | None = None,
) -> str:
    from . import tenant_policy_labels

    return tenant_policy_labels.get_label(key, default, path=path)


def deceased_field_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.deceased_field_labels(path=path)


def identifier_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.identifier_labels(path=path)


def print_heading_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.print_heading_labels(path=path)


def memorial_notice_table_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.memorial_notice_table_labels(path=path)


def marker_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.marker_labels(path=path)


def role_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.role_labels(path=path)


def role_document_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.role_document_labels(path=path)


def role_navigation_labels(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_labels

    return tenant_policy_labels.role_navigation_labels(path=path)


def load_memorial_notice_defaults(*, path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_memorial_notice

    return tenant_policy_memorial_notice.load_memorial_notice_defaults(path=path)


def get_memorial_notice_defaults(
    *,
    fallback_defaults: dict[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    from . import tenant_policy_memorial_notice

    return tenant_policy_memorial_notice.get_memorial_notice_defaults(
        fallback_defaults=fallback_defaults,
        path=path,
    )


def load_map_links(*, path: Path | None = None) -> dict:
    from . import tenant_policy_map_links

    return tenant_policy_map_links.load_map_links(path=path)


def get_map_links(
    *,
    fallback_map_links: dict | None = None,
    path: Path | None = None,
) -> dict:
    from . import tenant_policy_map_links

    return tenant_policy_map_links.get_map_links(
        fallback_map_links=fallback_map_links,
        path=path,
    )


def map_link_address_query_replacements(*, path: Path | None = None) -> tuple[tuple[str, str], ...]:
    from . import tenant_policy_map_links

    return tenant_policy_map_links.map_link_address_query_replacements(path=path)


def load_service_schedule_categories(*, path: Path | None = None) -> list[dict]:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.load_service_schedule_categories(path=path)


def get_service_schedule_categories(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.get_service_schedule_categories(
        fallback_categories=fallback_categories,
        path=path,
    )


def service_schedule_category_labels(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.service_schedule_category_labels(
        fallback_categories=fallback_categories,
        path=path,
    )


def service_schedule_category_choices(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> list[tuple[str, str]]:
    from . import tenant_policy_service_schedule_categories

    return tenant_policy_service_schedule_categories.service_schedule_category_choices(
        fallback_categories=fallback_categories,
        path=path,
    )


def load_relationship_labels(*, path: Path | None = None) -> list[dict]:
    from . import tenant_policy_relationship_labels

    return tenant_policy_relationship_labels.load_relationship_labels(path=path)


def get_relationship_labels(
    *,
    fallback_labels: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    from . import tenant_policy_relationship_labels

    return tenant_policy_relationship_labels.get_relationship_labels(
        fallback_labels=fallback_labels,
        path=path,
    )


def relationship_label_choices(
    *,
    fallback_labels: list[dict] | None = None,
    path: Path | None = None,
) -> list[tuple[str, str]]:
    from . import tenant_policy_relationship_labels

    return tenant_policy_relationship_labels.relationship_label_choices(
        fallback_labels=fallback_labels,
        path=path,
    )


def load_terminology(
    *,
    path: Path | None = None,
    labels_path: Path | None = None,
) -> dict:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.load_terminology(path=path, labels_path=labels_path)


def get_terminology(
    *,
    fallback_terminology: dict | None = None,
    path: Path | None = None,
    labels_path: Path | None = None,
) -> dict:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.get_terminology(
        fallback_terminology=fallback_terminology,
        path=path,
        labels_path=labels_path,
    )


def terminology_terms(*, path: Path | None = None, labels_path: Path | None = None) -> dict[str, str]:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.terminology_terms(path=path, labels_path=labels_path)


def terminology_copy(*, path: Path | None = None, labels_path: Path | None = None) -> dict:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.terminology_copy(path=path, labels_path=labels_path)


def search_aliases(*, path: Path | None = None, labels_path: Path | None = None) -> dict:
    from . import tenant_policy_terminology

    return tenant_policy_terminology.search_aliases(path=path, labels_path=labels_path)


def clear_policy_cache() -> None:
    from . import (
        tenant_policy_labels,
        tenant_policy_map_links,
        tenant_policy_memorial_notice,
        tenant_policy_memorial_rules,
        tenant_policy_relationship_labels,
        tenant_policy_service_schedule_categories,
        tenant_policy_terminology,
    )

    tenant_policy_memorial_rules.clear_policy_cache()
    tenant_policy_memorial_notice.clear_policy_cache()
    tenant_policy_labels.clear_policy_cache()
    tenant_policy_map_links.clear_policy_cache()
    tenant_policy_relationship_labels.clear_policy_cache()
    tenant_policy_service_schedule_categories.clear_policy_cache()
    tenant_policy_terminology.clear_policy_cache()


__all__ = [
    "DECEASED_FIELD_LABEL_DEFAULTS",
    "IDENTIFIER_LABEL_DEFAULTS",
    "LABEL_DEFAULTS",
    "MAP_LINK_DEFAULTS",
    "MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS",
    "PRINT_HEADING_LABEL_DEFAULTS",
    "ROLE_DOCUMENT_LABEL_DEFAULTS",
    "ROLE_NAVIGATION_LABEL_DEFAULTS",
    "ROLE_LABEL_DEFAULTS",
    "RELATIONSHIP_LABEL_DEFAULTS",
    "SERVICE_SCHEDULE_CATEGORY_DEFAULTS",
    "TenantPolicyError",
    "clear_policy_cache",
    "deceased_field_labels",
    "identifier_labels",
    "get_label",
    "get_labels",
    "get_memorial_notice_defaults",
    "get_memorial_rules",
    "get_relationship_labels",
    "get_service_schedule_categories",
    "labels_policy_path",
    "load_labels",
    "load_memorial_notice_defaults",
    "load_map_links",
    "load_memorial_rules",
    "load_relationship_labels",
    "load_service_schedule_categories",
    "marker_labels",
    "map_link_address_query_replacements",
    "map_links_policy_path",
    "memorial_notice_table_labels",
    "memorial_notice_defaults_policy_path",
    "memorial_rules_policy_path",
    "normalize_labels",
    "normalize_memorial_notice_defaults",
    "normalize_memorial_rules",
    "normalize_map_links",
    "normalize_relationship_labels",
    "normalize_service_schedule_categories",
    "normalize_terminology",
    "print_heading_labels",
    "relationship_label_choices",
    "relationship_labels_policy_path",
    "role_document_labels",
    "role_navigation_labels",
    "role_labels",
    "search_aliases",
    "service_schedule_categories_policy_path",
    "service_schedule_category_choices",
    "service_schedule_category_labels",
    "tenant_policy_root",
    "terminology_copy",
    "terminology_policy_path",
    "terminology_terms",
    "load_terminology",
    "get_terminology",
    "get_map_links",
]
