from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services
from .tenant_policy_defaults import (
    DECEASED_FIELD_LABEL_DEFAULTS,
    IDENTIFIER_LABEL_DEFAULTS,
    LABEL_DEFAULTS,
    MARKER_LABEL_DEFAULTS,
    MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS,
    PRINT_HEADING_LABEL_DEFAULTS,
    ROLE_DOCUMENT_LABEL_DEFAULTS,
    ROLE_LABEL_DEFAULTS,
    ROLE_NAVIGATION_LABEL_DEFAULTS,
)


def labels_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "labels.json"


def _normalize_labels(
    payload: dict,
    *,
    context: str,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be an object")
    required_keys = set(LABEL_DEFAULTS.keys())
    payload_keys = set(payload.keys())
    missing_keys = sorted(required_keys - payload_keys)
    unknown_keys = sorted(payload_keys - required_keys)
    if missing_keys:
        raise tenant_policy_services.TenantPolicyError(
            f"{context} is missing keys: {', '.join(missing_keys)}"
        )
    if unknown_keys:
        raise tenant_policy_services.TenantPolicyError(
            f"{context} contains unknown keys: {', '.join(unknown_keys)}"
        )
    normalized: dict[str, str] = {}
    for key in sorted(required_keys):
        value = str(payload.get(key, "")).strip()
        if not value:
            raise tenant_policy_services.TenantPolicyError(f"{context}.{key} must not be empty")
        normalized[key] = value
    return normalized


def normalize_labels(
    payload: dict,
    *,
    context: str = "labels",
) -> dict[str, str]:
    return _normalize_labels(payload, context=context)


@lru_cache(maxsize=8)
def _load_labels_from_path(path_str: str) -> tuple[tuple[str, str], ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(f"labels policy file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"labels policy file is not valid JSON: {path}"
        ) from exc
    normalized = _normalize_labels(payload, context=f"labels policy file {path}")
    return tuple(sorted(normalized.items()))


def load_labels(*, path: Path | None = None) -> dict[str, str]:
    resolved_path = path or tenant_policy_services.labels_policy_path()
    return dict(_load_labels_from_path(str(resolved_path)))


def get_labels(
    *,
    fallback_labels: dict[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    try:
        return load_labels(path=path)
    except tenant_policy_services.TenantPolicyError:
        return _normalize_labels(
            fallback_labels or LABEL_DEFAULTS,
            context="fallback labels",
        )


def get_label(
    key: str,
    default: str,
    *,
    path: Path | None = None,
) -> str:
    labels = get_labels(path=path)
    return labels.get(key, default)


def deceased_field_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "kaimyo": labels["person.kaimyo"],
        "kaimyo_kana": labels["person.kaimyo_kana"],
        "zokumyo": labels["person.zokumyo"],
    }


def identifier_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "person": labels["id.person"],
        "household": labels["id.household"],
        "service_event": labels["id.service_event"],
    }


def print_heading_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "memorial_sheet": labels["document.memorial_sheet"],
        "memorial_notice": labels["document.memorial_notice"],
        "service_schedule_print": labels["document.service_schedule_print"],
    }


def memorial_notice_table_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "death_date": labels["memorial_notice.label.death_date"],
        "memorial_service": labels["memorial_notice.label.memorial_service"],
        "other_note": labels["memorial_notice.label.other_note"],
    }


def marker_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "memorial_notice": labels["marker.memorial_notice"],
    }


def role_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "district_officer": labels["role.district_officer"],
        "monto_sodai": labels["role.monto_sodai"],
        "monto_sodai_formal": labels["role.monto_sodai_formal"],
        "responsible_officer": labels["role.responsible_officer"],
    }


def role_document_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "district_officer_roster": labels["document.district_officer_roster"],
        "monto_sodai_roster": labels["document.monto_sodai_roster"],
        "responsible_officer_roster": labels["document.responsible_officer_roster"],
        "district_officer_postal_labels": labels["document.district_officer_postal_labels"],
        "district_officer_delivery_labels": labels["document.district_officer_delivery_labels"],
        "monto_sodai_postal_labels": labels["document.monto_sodai_postal_labels"],
    }


def role_navigation_labels(*, path: Path | None = None) -> dict[str, str]:
    labels = get_labels(path=path)
    return {
        "district_officer_postal": labels["nav.district_officer_postal"],
        "district_officer_delivery": labels["nav.district_officer_delivery"],
    }


def clear_policy_cache() -> None:
    _load_labels_from_path.cache_clear()


__all__ = [
    "DECEASED_FIELD_LABEL_DEFAULTS",
    "IDENTIFIER_LABEL_DEFAULTS",
    "LABEL_DEFAULTS",
    "MARKER_LABEL_DEFAULTS",
    "MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS",
    "PRINT_HEADING_LABEL_DEFAULTS",
    "ROLE_DOCUMENT_LABEL_DEFAULTS",
    "ROLE_NAVIGATION_LABEL_DEFAULTS",
    "ROLE_LABEL_DEFAULTS",
    "clear_policy_cache",
    "deceased_field_labels",
    "get_label",
    "get_labels",
    "identifier_labels",
    "labels_policy_path",
    "load_labels",
    "marker_labels",
    "memorial_notice_table_labels",
    "normalize_labels",
    "print_heading_labels",
    "role_document_labels",
    "role_navigation_labels",
    "role_labels",
]
