from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services
from .tenant_policy_defaults import RELATIONSHIP_LABEL_DEFAULTS


def relationship_labels_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "relationship_labels.json"


def _normalize_relationship_labels(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str,
) -> list[dict]:
    if not isinstance(payload, list):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be a list")
    normalized: list[dict] = []
    seen_labels: set[str] = set()
    seen_seqs: set[int] = set()
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}] must be an object")
        label = str(row.get("label", "")).strip()
        try:
            seq = int(row["seq"])
        except (KeyError, TypeError, ValueError) as exc:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}] requires integer seq"
            ) from exc
        if not label:
            raise tenant_policy_services.TenantPolicyError(
                f"{context}[{index}].label must not be empty"
            )
        if seq < 1:
            raise tenant_policy_services.TenantPolicyError(f"{context}[{index}].seq must be >= 1")
        if label in seen_labels:
            raise tenant_policy_services.TenantPolicyError(
                f"{context} contains duplicate label={label}"
            )
        if seq in seen_seqs:
            raise tenant_policy_services.TenantPolicyError(f"{context} contains duplicate seq={seq}")
        seen_labels.add(label)
        seen_seqs.add(seq)
        normalized.append({"label": label, "seq": seq})
    normalized.sort(key=lambda row: (row["seq"], row["label"]))
    return normalized


def normalize_relationship_labels(
    payload: list[dict] | tuple[dict, ...],
    *,
    context: str = "relationship labels",
) -> list[dict]:
    return _normalize_relationship_labels(payload, context=context)


@lru_cache(maxsize=8)
def _load_relationship_labels_from_path(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(
            f"relationship labels policy file is missing: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"relationship labels policy file is not valid JSON: {path}"
        ) from exc
    normalized = _normalize_relationship_labels(
        payload,
        context=f"relationship labels policy file {path}",
    )
    return tuple(normalized)


def load_relationship_labels(*, path: Path | None = None) -> list[dict]:
    resolved_path = path or tenant_policy_services.relationship_labels_policy_path()
    return [dict(row) for row in _load_relationship_labels_from_path(str(resolved_path))]


def get_relationship_labels(
    *,
    fallback_labels: list[dict] | None = None,
    path: Path | None = None,
) -> list[dict]:
    try:
        return load_relationship_labels(path=path)
    except tenant_policy_services.TenantPolicyError:
        return _normalize_relationship_labels(
            fallback_labels or RELATIONSHIP_LABEL_DEFAULTS,
            context="fallback relationship labels",
        )


def relationship_label_choices(
    *,
    fallback_labels: list[dict] | None = None,
    path: Path | None = None,
) -> list[tuple[str, str]]:
    return [
        (row["label"], row["label"])
        for row in get_relationship_labels(
            fallback_labels=fallback_labels,
            path=path,
        )
    ]


def clear_policy_cache() -> None:
    _load_relationship_labels_from_path.cache_clear()


__all__ = [
    "RELATIONSHIP_LABEL_DEFAULTS",
    "clear_policy_cache",
    "get_relationship_labels",
    "load_relationship_labels",
    "normalize_relationship_labels",
    "relationship_label_choices",
    "relationship_labels_policy_path",
]
