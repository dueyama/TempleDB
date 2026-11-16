"""PDF renderer for memorial sheet documents.

This module uses ReportLab by default so opening a PDF never starts a local
Chrome/Edge process. Set `TEMPLEDB_MEMORIAL_SHEET_PDF_RENDERER=chrome` only for
explicit legacy comparison against the old browser-rendered output.
"""

from __future__ import annotations

from io import BytesIO

from apps.core.services import tenant_policy as tenant_policy_services

from . import memorial_sheet_pdf_layout, memorial_sheet_pdf_support

FONT_GOTHIC = memorial_sheet_pdf_support.FONT_GOTHIC
FONT_MINCHO = memorial_sheet_pdf_support.FONT_MINCHO

PAGE_MARGIN_LEFT_MM = memorial_sheet_pdf_support.PAGE_MARGIN_LEFT_MM
PAGE_MARGIN_RIGHT_MM = memorial_sheet_pdf_support.PAGE_MARGIN_RIGHT_MM
PAGE_MARGIN_TOP_MM = memorial_sheet_pdf_support.PAGE_MARGIN_TOP_MM
PAGE_MARGIN_BOTTOM_MM = memorial_sheet_pdf_support.PAGE_MARGIN_BOTTOM_MM

PERSON_DEATH_X_MM = memorial_sheet_pdf_support.PERSON_DEATH_X_MM
PERSON_HOMYO_X_MM = memorial_sheet_pdf_support.PERSON_HOMYO_X_MM
PERSON_ZOKUMYO_X_MM = memorial_sheet_pdf_support.PERSON_ZOKUMYO_X_MM
PERSON_AGE_X_MM = memorial_sheet_pdf_support.PERSON_AGE_X_MM

UPPER_COLUMNS_RIGHT_X_MM = memorial_sheet_pdf_support.UPPER_COLUMNS_RIGHT_X_MM
UPPER_COLUMNS_LEFT_X_MM = memorial_sheet_pdf_support.UPPER_COLUMNS_LEFT_X_MM
LOWER_COLUMNS_RIGHT_X_MM = memorial_sheet_pdf_support.LOWER_COLUMNS_RIGHT_X_MM
LOWER_COLUMN_STEP_MM = memorial_sheet_pdf_support.LOWER_COLUMN_STEP_MM

UPPER_TEMPLE_NAME_X_MM = memorial_sheet_pdf_support.UPPER_TEMPLE_NAME_X_MM
UPPER_TEMPLE_PHONE_X_MM = memorial_sheet_pdf_support.UPPER_TEMPLE_PHONE_X_MM
LOWER_TEMPLE_NAME_X_MM = memorial_sheet_pdf_support.LOWER_TEMPLE_NAME_X_MM
LOWER_TEMPLE_PHONE_X_MM = memorial_sheet_pdf_support.LOWER_TEMPLE_PHONE_X_MM

CHROME_BINARY_CANDIDATES = memorial_sheet_pdf_support.CHROME_BINARY_CANDIDATES
VERTICAL_TEXT_TRANSLATION = memorial_sheet_pdf_support.VERTICAL_TEXT_TRANSLATION


def _load_reportlab():
    return memorial_sheet_pdf_support._load_reportlab()


def _ensure_fonts(pdfmetrics, unicode_cid_font) -> None:
    memorial_sheet_pdf_support._ensure_fonts(pdfmetrics, unicode_cid_font)


def _verticalize_text(text: str) -> str:
    return memorial_sheet_pdf_support._verticalize_text(text)


def _chrome_pdf_binary() -> str | None:
    return memorial_sheet_pdf_support._chrome_pdf_binary()


def _memorial_sheet_pdf_renderer() -> str:
    return memorial_sheet_pdf_support._memorial_sheet_pdf_renderer()


def _render_memorial_sheet_pdf_via_chrome(context: dict) -> bytes | None:
    return memorial_sheet_pdf_support._render_memorial_sheet_pdf_via_chrome(context)


def _draw_vertical_segments(
    pdf_canvas,
    pdfmetrics,
    *,
    x: float,
    top_y: float,
    segments: list[dict],
    base_font_name: str,
    base_font_size: float,
    char_step: float,
) -> None:
    memorial_sheet_pdf_layout._draw_vertical_segments(
        pdf_canvas,
        pdfmetrics,
        x=x,
        top_y=top_y,
        segments=segments,
        base_font_name=base_font_name,
        base_font_size=base_font_size,
        char_step=char_step,
    )


def _draw_vertical_text(
    pdf_canvas,
    pdfmetrics,
    *,
    right_x: float,
    top_y: float,
    lines: list[dict],
    default_font_name: str,
    default_font_size: float,
    line_gap: float,
) -> None:
    memorial_sheet_pdf_layout._draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=right_x,
        top_y=top_y,
        lines=lines,
        default_font_name=default_font_name,
        default_font_size=default_font_size,
        line_gap=line_gap,
    )


def _plain_vertical_line(
    text: str,
    *,
    font_name: str | None = None,
    font_size: float | None = None,
    x_shift: float = 0.0,
    char_step: float | None = None,
) -> dict:
    return memorial_sheet_pdf_layout._plain_vertical_line(
        text,
        font_name=font_name,
        font_size=font_size,
        x_shift=x_shift,
        char_step=char_step,
    )


def _homyo_vertical_line(sheet: dict) -> dict:
    return memorial_sheet_pdf_layout._homyo_vertical_line(sheet)


def _special_kijitsu_lines(label: str) -> list[dict]:
    return memorial_sheet_pdf_layout._special_kijitsu_lines(label)


def _draw_memorial_sheet_block(
    pdf_canvas,
    pdfmetrics,
    *,
    sheet: dict,
    temple_identity: dict,
    top_y: float,
    lower: bool,
    mm: float,
) -> None:
    memorial_sheet_pdf_layout._draw_memorial_sheet_block(
        pdf_canvas,
        pdfmetrics,
        sheet=sheet,
        temple_identity=temple_identity,
        top_y=top_y,
        lower=lower,
        mm=mm,
    )


def render_memorial_sheet_pdf(*, context: dict) -> bytes:
    context.setdefault("deceased_labels", tenant_policy_services.deceased_field_labels())
    context.setdefault("print_heading_labels", tenant_policy_services.print_heading_labels())
    renderer = _memorial_sheet_pdf_renderer()
    if renderer == "chrome":
        chrome_pdf = _render_memorial_sheet_pdf_via_chrome(context)
        if chrome_pdf:
            return chrome_pdf

    A4, mm, pdfmetrics, unicode_cid_font, canvas = _load_reportlab()
    _ensure_fonts(pdfmetrics, unicode_cid_font)

    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    heading_labels = tenant_policy_services.print_heading_labels()
    household_name = context.get("household", {}).get("name", "")
    deceased_name = context.get("sheet", {}).get("deceased", {}).get("zokumyo", "")
    pdf_canvas.setTitle(f"{heading_labels['memorial_sheet']} {household_name} {deceased_name}".strip())

    page_width, page_height = A4
    inner_left = PAGE_MARGIN_LEFT_MM * mm
    inner_bottom = PAGE_MARGIN_BOTTOM_MM * mm
    inner_width = page_width - ((PAGE_MARGIN_LEFT_MM + PAGE_MARGIN_RIGHT_MM) * mm)
    inner_height = page_height - ((PAGE_MARGIN_TOP_MM + PAGE_MARGIN_BOTTOM_MM) * mm)
    pdf_canvas.rect(inner_left, inner_bottom, inner_width, inner_height, stroke=1, fill=0)

    separator_y = inner_bottom + (inner_height / 2)
    pdf_canvas.line(inner_left, separator_y, inner_left + inner_width, separator_y)

    sheet = context["sheet"]
    temple_identity = context.get("temple_identity") or {}

    _draw_memorial_sheet_block(
        pdf_canvas,
        pdfmetrics,
        sheet=sheet,
        temple_identity=temple_identity,
        top_y=page_height - (48.0 * mm),
        lower=False,
        mm=mm,
    )
    _draw_memorial_sheet_block(
        pdf_canvas,
        pdfmetrics,
        sheet=sheet,
        temple_identity=temple_identity,
        top_y=page_height - (177.0 * mm),
        lower=True,
        mm=mm,
    )

    pdf_canvas.showPage()
    pdf_canvas.save()
    return buffer.getvalue()


__all__ = ["render_memorial_sheet_pdf"]
