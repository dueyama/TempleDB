"""Keep postal documents in the same recipient order as address labels."""

from __future__ import annotations

from apps.imports.ledger_categories import normalize_ledger_category_code
from apps.imports.models import LEDGER_CATEGORY_WOMENS_ASSOCIATION
from apps.imports.runtime_shared import _clean_value, _int_sort, _sort_text


def postal_recipient_print_sort_key(row: dict) -> tuple:
    recipient_kana = _clean_value(row.get("recipient_kana"))
    recipient_name = _clean_value(row.get("recipient_name")) or _clean_value(
        row.get("household_name")
    )
    return (
        1 if normalize_ledger_category_code(row.get("ledger_category")) == LEDGER_CATEGORY_WOMENS_ASSOCIATION else 0,
        1 if not recipient_kana else 0,
        _sort_text(recipient_kana),
        _sort_text(recipient_name),
        _sort_text(row.get("household_name")),
        _int_sort(row.get("household_id")),
    )
