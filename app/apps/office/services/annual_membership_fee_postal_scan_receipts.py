from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from pathlib import Path


def extract_pdf_page_receipt_details(pdf_path: Path, page_number: int) -> dict:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return {}

    try:
        with pdfium.PdfDocument(str(pdf_path)) as document:
            page_index = max(int(page_number) - 1, 0)
            if page_index >= len(document):
                return {}
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range()
                finally:
                    text_page.close()
            finally:
                page.close()
    except Exception:
        return {}
    return parse_receipt_details_text(text)


def parse_receipt_details_text(text: str) -> dict:
    normalized = unicodedata.normalize("NFKC", text or "")
    paid_amount = _amount_after_label(normalized, "払込金額")
    collection_fee = _amount_after_label(normalized, "口座徴収料金")
    handling_office = _handling_office_details(normalized)
    if paid_amount is None and collection_fee is None and not handling_office:
        return {}
    net_amount = paid_amount - (collection_fee or 0) if paid_amount is not None else None
    details = {
        "paid_amount": paid_amount,
        "collection_fee": collection_fee,
        "net_amount": net_amount,
    }
    details.update(handling_office)
    return details


def with_receipt_details(payload: dict, receipt_details: dict | None) -> dict:
    if not receipt_details:
        return payload
    updated = dict(payload)
    updated["receipt_details"] = receipt_details
    return updated


def net_amount_from_receipt_details(receipt_details: dict | None) -> Decimal | None:
    receipt_details = receipt_details or {}
    net_amount = receipt_details.get("net_amount")
    if net_amount in {None, ""}:
        return None
    try:
        return Decimal(str(net_amount))
    except Exception:
        return None


def _amount_after_label(text: str, label: str) -> int | None:
    match = re.search(rf"{re.escape(label)}[\s:：]*([0-9][0-9,\s]*)\s*円", text)
    if not match:
        return None
    digits = re.sub(r"[^0-9]", "", match.group(1))
    return int(digits) if digits else None


def _handling_office_details(text: str) -> dict[str, str]:
    lines = [re.sub(r"\s+", "", line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    for label_index, line in enumerate(lines):
        if line != "取扱店":
            continue
        if label_index < 1:
            continue
        office_name = _clean_handling_office_name(lines[label_index - 1])
        if not office_name:
            continue
        details = {"handling_office_name": office_name}
        if label_index >= 2:
            code_match = re.fullmatch(r"[()（）]?([0-9]{4,6})[()（）]?", lines[label_index - 2])
            if code_match:
                details["handling_office_code"] = code_match.group(1)
        return details
    return {}


def _clean_handling_office_name(value: str) -> str:
    cleaned = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))
    if not cleaned or cleaned in {"通帳アプリ"}:
        return ""
    if len(cleaned) > 30 or not re.search(r"[一-龯々ぁ-んァ-ヶ]", cleaned):
        return ""
    if any(
        label in cleaned
        for label in (
            "取扱店",
            "口座番号",
            "取扱年月日",
            "一連番号",
            "通知番号",
            "払込金額",
            "口座徴収料金",
            "事務センター",
        )
    ):
        return ""
    return cleaned


__all__ = [
    "extract_pdf_page_receipt_details",
    "net_amount_from_receipt_details",
    "parse_receipt_details_text",
    "with_receipt_details",
]
