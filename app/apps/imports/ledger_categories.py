from __future__ import annotations

from .models import LEDGER_CATEGORY_CODES_BY_LABEL, LEDGER_CATEGORY_LABELS
from .runtime_shared import _clean_value


def normalize_ledger_category_code(value: str | None) -> str:
    cleaned = _clean_value(value)
    return LEDGER_CATEGORY_CODES_BY_LABEL.get(cleaned, cleaned)


def ledger_category_label(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    normalized = normalize_ledger_category_code(cleaned)
    return LEDGER_CATEGORY_LABELS.get(normalized, cleaned)


__all__ = ["ledger_category_label", "normalize_ledger_category_code"]
