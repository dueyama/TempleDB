from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

FONT_GOTHIC = "HeiseiKakuGo-W5"
FONT_MINCHO = "HeiseiMin-W3"
MEMORIAL_SHEET_PDF_RENDERER_ENV = "TEMPLEDB_MEMORIAL_SHEET_PDF_RENDERER"
MEMORIAL_SHEET_PDF_RENDERER_REPORTLAB = "reportlab"
MEMORIAL_SHEET_PDF_RENDERER_CHROME = "chrome"

PAGE_MARGIN_LEFT_MM = 10.0
PAGE_MARGIN_RIGHT_MM = 10.0
PAGE_MARGIN_TOP_MM = 8.0
PAGE_MARGIN_BOTTOM_MM = 8.0

PERSON_DEATH_X_MM = 182.0
PERSON_HOMYO_X_MM = 167.0
PERSON_ZOKUMYO_X_MM = 150.5
PERSON_AGE_X_MM = 142.0

UPPER_COLUMNS_RIGHT_X_MM = 124.0
UPPER_COLUMNS_LEFT_X_MM = 64.0
LOWER_COLUMNS_RIGHT_X_MM = 124.0
LOWER_COLUMN_STEP_MM = 8.0

UPPER_TEMPLE_NAME_X_MM = 34.0
UPPER_TEMPLE_PHONE_X_MM = 24.0
LOWER_TEMPLE_NAME_X_MM = 46.0
LOWER_TEMPLE_PHONE_X_MM = 35.0

CHROME_BINARY_CANDIDATES = (
    os.environ.get("TEMPLEDB_PDF_CHROME_BIN"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

VERTICAL_TEXT_TRANSLATION = str.maketrans(
    {
        "(": "︵",
        ")": "︶",
        "（": "︵",
        "）": "︶",
        "[": "﹇",
        "]": "﹈",
        "［": "﹇",
        "］": "﹈",
        "{": "︷",
        "}": "︸",
        "｛": "︷",
        "｝": "︸",
        "〈": "︿",
        "〉": "﹀",
        "《": "︽",
        "》": "︾",
        "「": "﹁",
        "」": "﹂",
        "『": "﹃",
        "』": "﹄",
        "【": "︻",
        "】": "︼",
        "〔": "︹",
        "〕": "︺",
    }
)


def _load_reportlab():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError("reportlab is required for PDF rendering.") from exc
    return A4, mm, pdfmetrics, UnicodeCIDFont, canvas


def _ensure_fonts(pdfmetrics, unicode_cid_font) -> None:
    for font_name in (FONT_GOTHIC, FONT_MINCHO):
        try:
            pdfmetrics.getFont(font_name)
        except KeyError:
            pdfmetrics.registerFont(unicode_cid_font(font_name))


def _verticalize_text(text: str) -> str:
    return str(text).translate(VERTICAL_TEXT_TRANSLATION)


def _chrome_pdf_binary() -> str | None:
    for candidate in CHROME_BINARY_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _memorial_sheet_pdf_renderer() -> str:
    renderer = os.environ.get(MEMORIAL_SHEET_PDF_RENDERER_ENV, "").strip().lower()
    if renderer in {"reportlab", "pdf", "stable"}:
        return MEMORIAL_SHEET_PDF_RENDERER_REPORTLAB
    if renderer in {"chrome", "chromium", "edge", "browser", "legacy"}:
        return MEMORIAL_SHEET_PDF_RENDERER_CHROME
    return MEMORIAL_SHEET_PDF_RENDERER_REPORTLAB


def _render_memorial_sheet_pdf_via_chrome(context: dict) -> bytes | None:
    # Browser rendering is only an optimization for CSS fidelity. Callers must
    # treat `None` as "use the stable ReportLab fallback instead".
    chrome_binary = _chrome_pdf_binary()
    if chrome_binary is None:
        return None

    try:
        from django.template.loader import render_to_string

        html = render_to_string("office/memorial_sheet_pdf.html", context)
    except Exception:
        return None
    with tempfile.TemporaryDirectory(prefix="templedb-memorial-sheet-") as tmpdir:
        html_path = Path(tmpdir) / "memorial_sheet.html"
        pdf_path = Path(tmpdir) / "memorial_sheet.pdf"
        html_path.write_text(html, encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    chrome_binary,
                    "--headless",
                    "--disable-gpu",
                    "--print-to-pdf-no-header",
                    f"--print-to-pdf={pdf_path}",
                    html_path.as_uri(),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0 or not pdf_path.exists():
            return None
        return pdf_path.read_bytes()
