from __future__ import annotations

import re
import unicodedata

NULL_TOKEN = "__MDB_NULL__"


def clean_contact_value(value: str | None) -> str:
    if value is None or value == NULL_TOKEN:
        return ""
    return value.strip()


def normalize_contact_text(value: str | None) -> str:
    cleaned = clean_contact_value(value)
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    return "".join(char for char in normalized if char not in {" ", "　"})


def normalize_postal_code_digits(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", clean_contact_value(value))
    return re.sub(r"[^0-9]", "", normalized)


def normalize_phone_digits(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", clean_contact_value(value))
    return re.sub(r"[^0-9]", "", normalized)


__all__ = [
    "clean_contact_value",
    "normalize_contact_text",
    "normalize_phone_digits",
    "normalize_postal_code_digits",
]
