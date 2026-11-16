from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services
from .tenant_policy_defaults import SERVICE_SCHEDULE_CATEGORY_DEFAULTS


def service_schedule_categories_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "service_schedule_categories.json"


def _normalize_service_schedule_categories(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str,
) -> list[dict]:
    if not isinstance(payload, list):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be a list")
    normalized: list[dict] = []
    seen_codes: set[str] = set()
    seen_seqs: set[int] = set()
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}] must be an object")
        code = str(row.get("code", "")).strip()
        label = str(row.get("label", "")).strip()
        try:
            seq = int(row["seq"])
        except (KeyError, TypeError, ValueError) as exc:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}] requires integer seq"
            ) from exc
        if not code:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}].code must not be empty"
            )
        if not label:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}].label must not be empty"
            )
        if seq < 1:
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}].seq must be >= 1")
        if code in seen_codes:
            raise tenant_policy_services.TenantPolicyError(
                f"{context} contains duplicate code={code}"
            )
        if seq in seen_seqs:
            raise tenant_policy_services.TenantPolicyError(f"{context} contains duplicate seq={seq}")
        seen_codes.add(code)
        seen_seqs.add(seq)
        normalized.append({"code": code, "label": label, "seq": seq})
    normalized.sort(key=lambda row: (row["seq"], row["code"], row["label"]))
    return normalized


def normalize_service_schedule_categories(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "service schedule categories",
) -> list[dict]:
    return _normalize_service_schedule_categories(payload, context=context)


@lru_cache(maxsize=8)
def _load_service_schedule_categories_from_path(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(
            f"service schedule categories policy file is missing: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"service schedule categories policy file is not valid JSON: {path}"
        ) from exc
    normalized = _normalize_service_schedule_categories(
        payload,
        context=f"service schedule categories policy file {path}",
    )
    return tuple(normalized)


def load_service_schedule_categories(*, path: Path | None = None) -> list[dict]:
    resolved_path = path or tenant_policy_services.service_schedule_categories_policy_path()
    return [dict(row) for row in _load_service_schedule_categories_from_path(str(resolved_path))]


def get_service_schedule_categories(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    try:
        return load_service_schedule_categories(path=path)
    except tenant_policy_services.TenantPolicyError:
        return _normalize_service_schedule_categories(
            fallback_categories or SERVICE_SCHEDULE_CATEGORY_DEFAULTS,
            context="fallback service schedule categories",
        )


def service_schedule_category_labels(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    return {
        row["code"]: row["label"]
        for row in get_service_schedule_categories(
            fallback_categories=fallback_categories,
            path=path,
        )
    }


def service_schedule_category_choices(
    *,
    fallback_categories: list[dict] | None = None,
    path: Path | None = None,
) -> list[tuple[str, str]]:
    return [
        (row["code"], row["label"])
        for row in get_service_schedule_categories(
            fallback_categories=fallback_categories,
            path=path,
        )
    ]


def clear_policy_cache() -> None:
    _load_service_schedule_categories_from_path.cache_clear()


__all__ = [
    "SERVICE_SCHEDULE_CATEGORY_DEFAULTS",
    "clear_policy_cache",
    "get_service_schedule_categories",
    "load_service_schedule_categories",
    "normalize_service_schedule_categories",
    "service_schedule_categories_policy_path",
    "service_schedule_category_choices",
    "service_schedule_category_labels",
]
