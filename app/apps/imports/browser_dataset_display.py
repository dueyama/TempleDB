from __future__ import annotations

from apps.core.services import tenant_policy as tenant_policy_services

from . import runtime_shared
from .ledger_categories import ledger_category_label
from .models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_NONE,
    HOUSEHOLD_DELIVERY_POSTAL,
)
from .synthetic_household_runtime import YUEN_HOUSEHOLD_NAME_PREFIX, YUEN_HOUSEHOLD_SOURCE_TABLE

_clean_value = runtime_shared._clean_value
_DISPLAY_COLUMN_KAIMYO = "__display_kaimyo"
_DISPLAY_COLUMN_RESERVE_KAIMYO = "__display_reserve_kaimyo"


def _display_pairs(row: dict, columns: list[str]) -> list[dict]:
    pairs = []
    for column in columns:
        value = _display_column_value(column, row.get(column))
        if value:
            pairs.append({"label": _display_column_label(column), "value": value})
    return pairs


def _non_empty_pairs(row: dict) -> list[dict]:
    pairs = []
    for key, value in row.items():
        if str(key).startswith("__") or isinstance(value, (dict, list, tuple)):
            continue
        display = runtime_shared._display_value(value)
        if display:
            pairs.append({"label": key, "value": display})
    return pairs


def _display_column_value(column: str, value: str | None) -> str:
    cleaned = runtime_shared._display_value(value)
    if not cleaned:
        return ""
    if column == "世話人ID":
        return ""
    if column == "台帳区分":
        return ledger_category_label(value)
    return cleaned


def _display_column_label(column: str) -> str:
    if column in {_DISPLAY_COLUMN_KAIMYO, "法名"}:
        return tenant_policy_services.deceased_field_labels()["kaimyo"]
    if column in {_DISPLAY_COLUMN_RESERVE_KAIMYO, "予備法名"}:
        return f"予備{tenant_policy_services.deceased_field_labels()['kaimyo']}"
    return column


def _same_name_household_delivery_label(delivery_method: str | None, district_name: str | None = "") -> str:
    cleaned_method = _clean_value(delivery_method)
    cleaned_district_name = _clean_value(district_name)
    if cleaned_method == HOUSEHOLD_DELIVERY_DISTRICT:
        if cleaned_district_name:
            return f"手配り / {cleaned_district_name}"
        return "手配り"
    if cleaned_method == HOUSEHOLD_DELIVERY_POSTAL:
        return "郵送"
    if cleaned_method == HOUSEHOLD_DELIVERY_NONE:
        return "郵送なし"
    return "手配り・郵送なし"


def _same_name_household_yuen_label(
    household_source_table: str | None,
    household_name: str | None,
) -> str:
    cleaned_source_table = _clean_value(household_source_table)
    cleaned_name = _clean_value(household_name)
    if cleaned_source_table == YUEN_HOUSEHOLD_SOURCE_TABLE or cleaned_name.startswith(YUEN_HOUSEHOLD_NAME_PREFIX):
        return "はい"
    return "いいえ"


__all__ = [
    "_DISPLAY_COLUMN_KAIMYO",
    "_DISPLAY_COLUMN_RESERVE_KAIMYO",
    "_display_column_label",
    "_display_column_value",
    "_display_pairs",
    "_non_empty_pairs",
    "_same_name_household_delivery_label",
    "_same_name_household_yuen_label",
]
