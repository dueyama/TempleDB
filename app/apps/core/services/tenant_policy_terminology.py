from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import tenant_policy as tenant_policy_services

TERMINOLOGY_DEFAULTS = {
    "terms": {
        "homyo_body": "{kaimyo}本体",
        "homyo_input_presence": "{kaimyo}入力あり",
        "homyo_presence": "{kaimyo}あり",
        "homyo_presence_rate": "{kaimyo}あり率",
        "homyo_order_issue": "{kaimyo}順序要確認",
        "kaimyo_search": "{kaimyo}検索",
    },
    "copy": {
        "person_search": {
            "placeholder": "氏名 / かな / {person_id} / 続柄 / {kaimyo}",
            "help": "氏名、かな、{person_id}、続柄、{kaimyo}で人を探せます。",
        },
        "data_quality": {
            "search_placeholder": "氏名 / 戸主 / {kaimyo} / 続柄 / {household_id}",
            "homyo_order_description": (
                "`釋 / 釋尼 / 釈 / 釈尼 / 尼` が先に来たあとで `院 / 庵 / 軒` が"
                "出てくるものです。通常の院号{kaimyo}順と違うため、入力順の確認候補"
                "として拾っています。"
            ),
            "homyo_order_empty": "{homyo_order_issue}の候補は見つかりませんでした。",
        },
        "special_search": {
            "data_quality_description": (
                "命日不明、性別不明、{homyo_order_issue}、同名候補、import issues を"
                "まとめて見ます。"
            ),
            "kaimyo_contains_label": "{kaimyo_search}",
            "kaimyo_contains_description": (
                "検索文字を含む{kaimyo}の一覧です。{kaimyo}の一部から故人を探せます。"
            ),
            "search_placeholder": "戸主名 / 故人名 / {household_id} / {kaimyo}",
            "kaimyo_match_status": "{kaimyo}一致",
        },
        "special_searches": {
            "search_placeholder": "戸主名 / 故人名 / {household_id} / {kaimyo}",
        },
        "universal_search": {
            "placeholder": "例: 葬儀のメモ / 田中家の法事 / {kaimyo}で探す",
        },
        "household_head_transition": {
            "memorial_registration_callout": (
                "戸主の往生登録を行います。命日・{kaimyo}・享年を入れ、通常はそのまま"
                "葬儀予定も作れます。"
            ),
            "restore_current_callout": (
                "戸主 person を現在帳へ戻します。命日・{kaimyo}などの過去帳情報がある"
                "場合は外れます。"
            ),
        },
        "data_science": {
            "help_intro": (
                "過去帳の命日・享年・{kaimyo}データから、暦の偏り、年代差、{kaimyo}"
                "の文字傾向をワンクリックで見られる read-only 画面です。"
            ),
            "homyo_section_title": "{kaimyo}",
            "homyo_section_description": (
                "院号{kaimyo}を、院号の有無と{homyo_body}の文字傾向に分けて見ます。"
            ),
            "homyo_character_title": "{homyo_body}によく出る文字",
            "homyo_character_description": (
                "院号と接頭の <code>釋</code> / <code>釈</code> / <code>釋尼</code> / "
                "<code>釈尼</code> / <code>尼</code> を除いた、{homyo_body}の文字"
                "出現数です。"
            ),
            "homyo_empty": "表示できる{kaimyo}分析がありません。",
            "completeness_description": (
                "death-date が解析可能な record に限り、死亡年代ごとに享年・{kaimyo}"
                "・性別の入力率を比較します。"
            ),
        },
    },
    "search_aliases": {
        "result_kind": {
            "person": ["人", "個人", "家族", "故人", "{kaimyo}", "戒名"],
        },
        "note_type": {
            "deceased_note": ["故人メモ", "{kaimyo}メモ", "戒名メモ"],
        },
        "special_search": {
            "kaimyo_contains": ["{kaimyo_search}", "戒名検索"],
        },
    },
}


def terminology_policy_path() -> Path:
    return tenant_policy_services.tenant_policy_root() / "terminology.json"


def _normalize_nested(payload: Any, default: Any, *, context: str) -> Any:
    if isinstance(default, dict):
        if not isinstance(payload, dict):
            raise tenant_policy_services.TenantPolicyError(f"{context} must be an object")
        required_keys = set(default.keys())
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
            key: _normalize_nested(payload[key], default[key], context=f"{context}.{key}")
            for key in sorted(default.keys())
        }
    if isinstance(default, list):
        if not isinstance(payload, list):
            raise tenant_policy_services.TenantPolicyError(f"{context} must be a list")
        normalized: list[str] = []
        for index, value in enumerate(payload, start=1):
            if not isinstance(value, str):
                raise tenant_policy_services.TenantPolicyError(f"{context}[{index}] must be a string")
            cleaned = value.strip()
            if not cleaned:
                raise tenant_policy_services.TenantPolicyError(
                    f"{context}[{index}] must not be empty"
                )
            normalized.append(cleaned)
        return normalized
    if not isinstance(default, str):
        raise tenant_policy_services.TenantPolicyError(f"{context} has unsupported default type")
    if not isinstance(payload, str):
        raise tenant_policy_services.TenantPolicyError(f"{context} must be a string")
    cleaned = payload.strip()
    if not cleaned:
        raise tenant_policy_services.TenantPolicyError(f"{context} must not be empty")
    return cleaned


def normalize_terminology(
    payload: dict,
    *,
    context: str = "terminology",
) -> dict[str, Any]:
    return _normalize_nested(payload, TERMINOLOGY_DEFAULTS, context=context)


@lru_cache(maxsize=8)
def _load_terminology_from_path(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise tenant_policy_services.TenantPolicyError(f"terminology policy file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise tenant_policy_services.TenantPolicyError(
            f"terminology policy file is not valid JSON: {path}"
        ) from exc
    return normalize_terminology(payload, context=f"terminology policy file {path}")


def _render_string(value: str, replacements: dict[str, str], *, context: str) -> str:
    try:
        return value.format_map(replacements)
    except KeyError as exc:
        missing_key = str(exc.args[0])
        raise tenant_policy_services.TenantPolicyError(
            f"{context} contains unknown placeholder: {missing_key}"
        ) from exc


def _render_nested(value: Any, replacements: dict[str, str], *, context: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _render_nested(item, replacements, context=f"{context}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list):
        rendered: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value, start=1):
            rendered_item = _render_string(item, replacements, context=f"{context}[{index}]")
            if rendered_item in seen:
                continue
            seen.add(rendered_item)
            rendered.append(rendered_item)
        return rendered
    return _render_string(value, replacements, context=context)


def _terminology_replacements(*, labels_path: Path | None = None) -> dict[str, str]:
    deceased_labels = tenant_policy_services.deceased_field_labels(path=labels_path)
    id_labels = tenant_policy_services.identifier_labels(path=labels_path)
    return {
        "kaimyo": deceased_labels["kaimyo"],
        "kaimyo_kana": deceased_labels["kaimyo_kana"],
        "zokumyo": deceased_labels["zokumyo"],
        "person_id": id_labels["person"],
        "household_id": id_labels["household"],
        "service_event_id": id_labels["service_event"],
    }


def load_terminology(
    *,
    path: Path | None = None,
    labels_path: Path | None = None,
) -> dict[str, Any]:
    resolved_path = path or tenant_policy_services.terminology_policy_path()
    raw = copy.deepcopy(_load_terminology_from_path(str(resolved_path)))
    replacements = _terminology_replacements(labels_path=labels_path)
    rendered_terms = _render_nested(
        raw["terms"],
        replacements,
        context=f"terminology terms {resolved_path}",
    )
    replacements.update(rendered_terms)
    rendered_copy = _render_nested(
        raw["copy"],
        replacements,
        context=f"terminology copy {resolved_path}",
    )
    rendered_aliases = _render_nested(
        raw["search_aliases"],
        replacements,
        context=f"terminology search aliases {resolved_path}",
    )
    return {
        "terms": rendered_terms,
        "copy": rendered_copy,
        "search_aliases": rendered_aliases,
    }


def get_terminology(
    *,
    fallback_terminology: dict[str, Any] | None = None,
    path: Path | None = None,
    labels_path: Path | None = None,
) -> dict[str, Any]:
    try:
        return load_terminology(path=path, labels_path=labels_path)
    except tenant_policy_services.TenantPolicyError:
        payload = fallback_terminology or TERMINOLOGY_DEFAULTS
        normalized = normalize_terminology(payload, context="fallback terminology")
        replacements = _terminology_replacements(labels_path=labels_path)
        rendered_terms = _render_nested(
            normalized["terms"],
            replacements,
            context="fallback terminology terms",
        )
        replacements.update(rendered_terms)
        return {
            "terms": rendered_terms,
            "copy": _render_nested(
                normalized["copy"],
                replacements,
                context="fallback terminology copy",
            ),
            "search_aliases": _render_nested(
                normalized["search_aliases"],
                replacements,
                context="fallback terminology search aliases",
            ),
        }


def terminology_terms(*, path: Path | None = None, labels_path: Path | None = None) -> dict[str, str]:
    return get_terminology(path=path, labels_path=labels_path)["terms"]


def terminology_copy(*, path: Path | None = None, labels_path: Path | None = None) -> dict[str, Any]:
    return get_terminology(path=path, labels_path=labels_path)["copy"]


def search_aliases(*, path: Path | None = None, labels_path: Path | None = None) -> dict[str, Any]:
    return get_terminology(path=path, labels_path=labels_path)["search_aliases"]


def clear_policy_cache() -> None:
    _load_terminology_from_path.cache_clear()


__all__ = [
    "TERMINOLOGY_DEFAULTS",
    "clear_policy_cache",
    "get_terminology",
    "load_terminology",
    "normalize_terminology",
    "search_aliases",
    "terminology_copy",
    "terminology_policy_path",
    "terminology_terms",
]
