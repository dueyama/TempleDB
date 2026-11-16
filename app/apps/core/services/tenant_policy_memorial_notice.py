from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import tenant_policy as tenant_policy_services
from .tenant_policy_defaults import MEMORIAL_NOTICE_DEFAULT_KEYS

MEMORIAL_NOTICE_ROWS_PER_PAGE = 6
DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE = (
    "{{YEAR_LABEL}} に当たるご法事をお勤めいたしたく、"
    "下記の通りご案内申し上げます。"
)
DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT = (
    "{year_with_wareki} に当たるご法事をお勤めいたしたく、"
    "下記の通りご案内申し上げます。"
)
DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT = (
    "ご都合をお知らせいただけましたら幸甚に存じます。"
)
DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT = (
    "宗派名　寺院名\n"
    "住所\n"
    "電話　電話番号"
)
DEFAULT_MEMORIAL_NOTICE_STYLE = {
    "recipient_font_size": 2.00,
    "body_font_size": 1.15,
    "signature_font_size": 1.15,
    "table_font_size": 1.0,
}


def memorial_notice_defaults_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "memorial_notice_defaults.json"


def _normalize_memorial_notice_defaults(
    payload: dict,
    *,
    context: str,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be an object")
    required_keys = set(MEMORIAL_NOTICE_DEFAULT_KEYS)
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
    for key in MEMORIAL_NOTICE_DEFAULT_KEYS:
        value = payload.get(key)
        if not isinstance(value, str):
            raise tenant_policy_services.TenantPolicyError(f"{context}.{key} must be a string")
        if not value.strip():
            raise tenant_policy_services.TenantPolicyError(f"{context}.{key} must not be empty")
        normalized[key] = value
    return normalized


def normalize_memorial_notice_defaults(
    payload: dict,
    *,
    context: str = "memorial notice defaults",
) -> dict[str, str]:
    return _normalize_memorial_notice_defaults(payload, context=context)


@lru_cache(maxsize=8)
def _load_memorial_notice_defaults_from_path(path_str: str) -> tuple[tuple[str, str], ...]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(
            f"memorial notice defaults policy file is missing: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"memorial notice defaults policy file is not valid JSON: {path}"
        ) from exc
    normalized = _normalize_memorial_notice_defaults(
        payload,
        context=f"memorial notice defaults policy file {path}",
    )
    return tuple((key, normalized[key]) for key in MEMORIAL_NOTICE_DEFAULT_KEYS)


def load_memorial_notice_defaults(*, path: Path | None = None) -> dict[str, str]:
    resolved_path = path or tenant_policy_services.memorial_notice_defaults_policy_path()
    return dict(_load_memorial_notice_defaults_from_path(str(resolved_path)))


def get_memorial_notice_defaults(
    *,
    fallback_defaults: dict[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    try:
        return load_memorial_notice_defaults(path=path)
    except tenant_policy_services.TenantPolicyError:
        if fallback_defaults is None:
            raise
        return _normalize_memorial_notice_defaults(
            fallback_defaults,
            context="fallback memorial notice defaults",
        )


def clear_policy_cache() -> None:
    _load_memorial_notice_defaults_from_path.cache_clear()


__all__ = [
    "DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE",
    "DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT",
    "DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT",
    "DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT",
    "DEFAULT_MEMORIAL_NOTICE_STYLE",
    "MEMORIAL_NOTICE_DEFAULT_KEYS",
    "MEMORIAL_NOTICE_ROWS_PER_PAGE",
    "clear_policy_cache",
    "get_memorial_notice_defaults",
    "load_memorial_notice_defaults",
    "memorial_notice_defaults_policy_path",
    "normalize_memorial_notice_defaults",
]
