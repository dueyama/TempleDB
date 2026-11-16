from __future__ import annotations

import re
import unicodedata

_WHITESPACE_SPLIT_RE = re.compile(r"(\s+)")


def normalize_kana_storage(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    parts = _WHITESPACE_SPLIT_RE.split(text)
    converted: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isspace():
            converted.append(part)
            continue
        normalized = unicodedata.normalize("NFKC", part)
        converted.append("".join(_katakana_to_hiragana(char) for char in normalized))
    return "".join(converted)


def normalize_kana_for_match(value: str | None) -> str:
    return "".join(normalize_kana_storage(value).split())


def _katakana_to_hiragana(char: str) -> str:
    code = ord(char)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return char


__all__ = [
    "normalize_kana_for_match",
    "normalize_kana_storage",
]
