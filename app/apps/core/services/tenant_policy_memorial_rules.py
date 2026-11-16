from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services


def memorial_rules_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "memorial_rules.json"


def _normalize_memorial_rules(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str,
) -> list[dict]:
    if not isinstance(payload, list):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be a list")
    normalized: list[dict] = []
    seen_years: set[int] = set()
    seen_seqs: set[int] = set()
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}] must be an object")
        try:
            years = int(row["years"])
            seq = int(row["seq"])
        except (KeyError, TypeError, ValueError) as exc:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}] requires integer years and seq"
            ) from exc
        label = str(row.get("label", "")).strip()
        if years < 0:
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}].years must be >= 0")
        if seq < 1:
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}].seq must be >= 1")
        if not label:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}].label must not be empty"
            )
        if years in seen_years:
            raise tenant_policy_services.TenantPolicyError(f"{context} contains duplicate years={years}")
        if seq in seen_seqs:
            raise tenant_policy_services.TenantPolicyError(f"{context} contains duplicate seq={seq}")
        seen_years.add(years)
        seen_seqs.add(seq)
        normalized.append({"years": years, "label": label, "seq": seq})
    normalized.sort(key=lambda row: (row["seq"], row["years"], row["label"]))
    return normalized


def normalize_memorial_rules(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "memorial rules",
) -> list[dict]:
    return _normalize_memorial_rules(payload, context=context)


@lru_cache(maxsize=8)
def _load_memorial_rules_from_path(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(
            f"memorial rules policy file is missing: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"memorial rules policy file is not valid JSON: {path}"
        ) from exc
    normalized = _normalize_memorial_rules(payload, context=f"memorial rules policy file {path}")
    return tuple(normalized)


def load_memorial_rules(*, path: Path | None = None) -> list[dict]:
    resolved_path = path or tenant_policy_services.memorial_rules_policy_path()
    return [dict(row) for row in _load_memorial_rules_from_path(str(resolved_path))]


def get_memorial_rules(
    *,
    fallback_rules: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    try:
        return load_memorial_rules(path=path)
    except tenant_policy_services.TenantPolicyError:
        return _normalize_memorial_rules(
            fallback_rules or [],
            context="fallback memorial rules",
        )


def clear_policy_cache() -> None:
    _load_memorial_rules_from_path.cache_clear()


__all__ = [
    "clear_policy_cache",
    "get_memorial_rules",
    "load_memorial_rules",
    "memorial_rules_policy_path",
    "normalize_memorial_rules",
]
