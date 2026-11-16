from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services
from .tenant_policy_defaults import MAP_LINK_DEFAULTS


def map_links_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "map_links.json"


def _normalize_address_query_replacements(
    payload: list[dict],
    *,
    context: str,
) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be a list")
    normalized: list[dict[str, str]] = []
    seen_matches: set[str] = set()
    for index, item in enumerate(payload, start=1):
        item_context = f"{context}[{index}]"
        if not isinstance(item, dict):
            raise tenant_policy_services.TenantPolicyError(f"{item_context} must be an object")
        required_keys = {"match", "replace"}
        payload_keys = set(item.keys())
        missing_keys = sorted(required_keys - payload_keys)
        unknown_keys = sorted(payload_keys - required_keys)
        if missing_keys:
            raise tenant_policy_services.TenantPolicyError(
                f"{item_context} is missing keys: {', '.join(missing_keys)}"
            )
        if unknown_keys:
            raise tenant_policy_services.TenantPolicyError(
                f"{item_context} contains unknown keys: {', '.join(unknown_keys)}"
            )
        match = item.get("match")
        if not isinstance(match, str):
            raise tenant_policy_services.TenantPolicyError(f"{item_context}.match must be a string")
        cleaned_match = match.strip()
        if not cleaned_match:
            raise tenant_policy_services.TenantPolicyError(
                f"{item_context}.match must not be empty"
            )
        replace = item.get("replace")
        if not isinstance(replace, str):
            raise tenant_policy_services.TenantPolicyError(
                f"{item_context}.replace must be a string"
            )
        if cleaned_match in seen_matches:
            raise tenant_policy_services.TenantPolicyError(
                f"{context} contains duplicate match: {cleaned_match}"
            )
        seen_matches.add(cleaned_match)
        normalized.append({"match": cleaned_match, "replace": replace})
    return normalized


def normalize_map_links(
    payload: dict,
    *,
    context: str = "map links",
) -> dict[str, list[dict[str, str]]]:
    if not isinstance(payload, dict):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be an object")
    required_keys = {"address_query_replacements"}
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
    return {
        "address_query_replacements": _normalize_address_query_replacements(
            payload["address_query_replacements"],
            context=f"{context}.address_query_replacements",
        )
    }


@lru_cache(maxsize=8)
def _load_map_links_from_path(path_str: str) -> tuple[tuple[str, str], ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(
            f"map links policy file is missing: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"map links policy file is not valid JSON: {path}"
        ) from exc
    normalized = normalize_map_links(payload, context=f"map links policy file {path}")
    return tuple(
        (item["match"], item["replace"])
        for item in normalized["address_query_replacements"]
    )


def load_map_links(*, path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    resolved_path = path or tenant_policy_services.map_links_policy_path()
    return {
        "address_query_replacements": [
            {"match": match, "replace": replace}
            for match, replace in _load_map_links_from_path(str(resolved_path))
        ]
    }


def get_map_links(
    *,
    fallback_map_links: dict | None = None,
    path: Path | None = None,
) -> dict[str, list[dict[str, str]]]:
    try:
        return load_map_links(path=path)
    except tenant_policy_services.TenantPolicyError:
        return normalize_map_links(
            fallback_map_links or MAP_LINK_DEFAULTS,
            context="fallback map links",
        )


def map_link_address_query_replacements(*, path: Path | None = None) -> tuple[tuple[str, str], ...]:
    map_links = get_map_links(path=path)
    return tuple(
        (item["match"], item["replace"])
        for item in map_links["address_query_replacements"]
    )


def clear_policy_cache() -> None:
    _load_map_links_from_path.cache_clear()


__all__ = [
    "MAP_LINK_DEFAULTS",
    "clear_policy_cache",
    "get_map_links",
    "load_map_links",
    "map_link_address_query_replacements",
    "map_links_policy_path",
    "normalize_map_links",
]
