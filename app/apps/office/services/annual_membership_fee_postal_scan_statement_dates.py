from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

WAREKI_ERA_OFFSETS = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
}


def extract_pdf_statement_date(pdf_path: Path) -> date | None:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None

    try:
        with pdfium.PdfDocument(str(pdf_path)) as document:
            if len(document) <= 0:
                return None
            page = document[0]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range()
                finally:
                    text_page.close()
            finally:
                page.close()
    except Exception:
        return None
    return parse_statement_date_text(text)


def parse_statement_date_text(text: str) -> date | None:
    normalized = unicodedata.normalize("NFKC", text or "")
    wareki_match = re.search(
        r"(令和|平成|昭和)\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        normalized,
    )
    if wareki_match:
        era, era_year_text, month_text, day_text = wareki_match.groups()
        era_year = 1 if era_year_text == "元" else int(era_year_text)
        return safe_date(
            WAREKI_ERA_OFFSETS[era] + era_year,
            int(month_text),
            int(day_text),
        )
    gregorian_match = re.search(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        normalized,
    )
    if gregorian_match:
        year_text, month_text, day_text = gregorian_match.groups()
        return safe_date(int(year_text), int(month_text), int(day_text))
    return None


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


__all__ = [
    "WAREKI_ERA_OFFSETS",
    "extract_pdf_statement_date",
    "parse_statement_date_text",
    "safe_date",
]
