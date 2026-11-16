from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from io import BytesIO

PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0
LABEL_WIDTH_MM = 86.4
LABEL_HEIGHT_MM = 42.3
PAGE_MARGIN_LEFT_MM = 18.6
PAGE_MARGIN_TOP_MM = 21.2
PAGE_MARGIN_BOTTOM_MM = 22.0
LABELS_PER_ROW = 2
LABELS_PER_COLUMN = 6
ADDRESS_LEFT_PADDING_MM = 5.5
ADDRESS_TOP_PADDING_MM = 4.8
ADDRESS_BOTTOM_PADDING_MM = 4.2

FONT_GOTHIC = "HeiseiKakuGo-W5"
FONT_MINCHO = "HeiseiMin-W3"


def _load_reportlab():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
        raise RuntimeError("reportlab is required for PDF rendering.") from exc
    return A4, mm, pdfmetrics, UnicodeCIDFont, canvas


def _ensure_fonts(pdfmetrics, unicode_cid_font) -> None:
    for font_name in (FONT_GOTHIC, FONT_MINCHO):
        try:
            pdfmetrics.getFont(font_name)
        except KeyError:
            pdfmetrics.registerFont(unicode_cid_font(font_name))


def _string_width(pdfmetrics, text: str, font_name: str, font_size: float) -> float:
    return pdfmetrics.stringWidth(text, font_name, font_size)


def _wrap_text(
    pdfmetrics,
    text: str,
    *,
    font_name: str,
    font_size: float,
    max_width: float,
    max_lines: int | None = None,
) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    for character in normalized:
        candidate = f"{current}{character}"
        if not current or _string_width(pdfmetrics, candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = character

    if current:
        lines.append(current)

    if max_lines is None or len(lines) <= max_lines:
        return lines

    kept = lines[:max_lines]
    ellipsis = "..."
    last_line = kept[-1]
    while last_line and _string_width(
        pdfmetrics,
        f"{last_line}{ellipsis}",
        font_name,
        font_size,
    ) > max_width:
        last_line = last_line[:-1]
    kept[-1] = f"{last_line}{ellipsis}" if last_line else ellipsis
    return kept


def _draw_left_aligned_lines(
    pdf_canvas,
    *,
    x: float,
    top_y: float,
    lines: Iterable[str],
    font_name: str,
    font_size: float,
    line_height: float,
) -> None:
    for index, line in enumerate(lines):
        pdf_canvas.setFont(font_name, font_size)
        pdf_canvas.drawString(x, top_y - (index * line_height) - font_size, line)


def _draw_right_aligned_lines(
    pdf_canvas,
    pdfmetrics,
    *,
    right_x: float,
    top_y: float,
    lines: Iterable[str],
    font_name: str,
    font_size: float,
    line_height: float,
) -> None:
    for index, line in enumerate(lines):
        text_width = _string_width(pdfmetrics, line, font_name, font_size)
        pdf_canvas.setFont(font_name, font_size)
        pdf_canvas.drawString(
            right_x - text_width,
            top_y - (index * line_height) - font_size,
            line,
        )


def _draw_centered_lines(
    pdf_canvas,
    pdfmetrics,
    *,
    center_x: float,
    top_y: float,
    lines: Iterable[str],
    font_name: str,
    font_size: float,
    line_height: float,
) -> None:
    for index, line in enumerate(lines):
        text_width = _string_width(pdfmetrics, line, font_name, font_size)
        pdf_canvas.setFont(font_name, font_size)
        pdf_canvas.drawString(
            center_x - (text_width / 2),
            top_y - (index * line_height) - font_size,
            line,
        )


def _wrap_address_lines(pdfmetrics, label: dict, *, font_size: float, max_width: float) -> list[str]:
    return [
        line
        for raw_line in label.get("address_lines", [])
        for line in _wrap_text(
            pdfmetrics,
            raw_line,
            font_name=FONT_GOTHIC,
            font_size=font_size,
            max_width=max_width,
            max_lines=2,
        )
    ][:3]


def _draw_address_label(
    pdf_canvas,
    pdfmetrics,
    *,
    label: dict,
    origin_x: float,
    origin_y: float,
    mm: float,
    monto_sodai_layout: bool = False,
) -> None:
    content_x = origin_x + (ADDRESS_LEFT_PADDING_MM * mm)
    top_y = origin_y + (LABEL_HEIGHT_MM * mm) - (ADDRESS_TOP_PADDING_MM * mm)
    content_width = (LABEL_WIDTH_MM - (ADDRESS_LEFT_PADDING_MM * 2)) * mm

    marker_font_size = 9
    postal_font_size = 11.5
    address_font_size = 10
    addressee_font_size = 16

    # The monto-sodai HTML puts the role just above the indented addressee,
    # while ordinary postal labels retain their existing marker positions.
    if monto_sodai_layout:
        marker_font_size = 3.9 * mm
        postal_font_size = 4.1 * mm
        address_font_size = 3.6 * mm
        addressee_font_size = 5.8 * mm

    marker_text = (label.get("marker_text") or "").strip()
    marker_lines: list[str] = []
    marker_position = (label.get("marker_position") or "").strip().lower()
    if marker_text:
        marker_lines = _wrap_text(
            pdfmetrics,
            marker_text,
            font_name=FONT_GOTHIC,
            font_size=marker_font_size,
            max_width=(32 * mm) if marker_position == "bottom_right" else content_width,
            max_lines=2,
        )
        if monto_sodai_layout:
            _draw_left_aligned_lines(
                pdf_canvas,
                x=content_x,
                top_y=origin_y + ((LABEL_HEIGHT_MM - 22.8) * mm),
                lines=marker_lines,
                font_name=FONT_GOTHIC,
                font_size=marker_font_size,
                line_height=3.9 * mm,
            )
        elif marker_position == "bottom_right":
            marker_bottom_y = origin_y + (ADDRESS_BOTTOM_PADDING_MM * mm)
            marker_top_y = marker_bottom_y + marker_font_size + (max(len(marker_lines) - 1, 0) * (4.4 * mm))
            _draw_right_aligned_lines(
                pdf_canvas,
                pdfmetrics,
                right_x=origin_x + (LABEL_WIDTH_MM * mm) - (ADDRESS_LEFT_PADDING_MM * mm),
                top_y=marker_top_y,
                lines=marker_lines,
                font_name=FONT_GOTHIC,
                font_size=marker_font_size,
                line_height=4.4 * mm,
            )
        else:
            _draw_left_aligned_lines(
                pdf_canvas,
                x=content_x,
                top_y=top_y,
                lines=marker_lines,
                font_name=FONT_GOTHIC,
                font_size=marker_font_size,
                line_height=4.4 * mm,
            )

    marker_vertical_offset = (
        max(len(marker_lines) - 1, 0) * (4.4 * mm)
        if marker_lines and marker_position != "bottom_right" and not monto_sodai_layout
        else 0
    )
    postal_top_y = top_y if monto_sodai_layout else top_y - (5.2 * mm) - marker_vertical_offset
    postal_code = (label.get("postal_code_display") or "").strip()
    if postal_code:
        _draw_left_aligned_lines(
            pdf_canvas,
            x=content_x,
            top_y=postal_top_y,
            lines=[postal_code],
            font_name=FONT_GOTHIC,
            font_size=postal_font_size,
            line_height=5.2 * mm,
        )

    address_lines = _wrap_address_lines(
        pdfmetrics, label, font_size=address_font_size, max_width=content_width,
    )
    if monto_sodai_layout and len(address_lines) == 3:
        # Keep a third address line above the fixed role title, rather than
        # letting it overlap the role as the unbounded HTML text can do.
        address_font_size = 3.0 * mm
        address_lines = _wrap_address_lines(
            pdfmetrics, label, font_size=address_font_size, max_width=content_width,
        )
    if address_lines:
        # HTML: postal line (4.1mm * 1.1) followed by the 1.4mm grid gap.
        address_top_y = (
            top_y - ((4.1 * 1.1 + 1.4) * mm)
            if monto_sodai_layout else top_y - (11.5 * mm) - marker_vertical_offset
        )
        _draw_left_aligned_lines(
            pdf_canvas,
            x=content_x,
            top_y=address_top_y,
            lines=address_lines,
            font_name=FONT_GOTHIC,
            font_size=address_font_size,
            line_height=address_font_size * 1.28 + 0.35 * mm if monto_sodai_layout else 4.7 * mm,
        )

    addressee_padding = 7.4 * mm if monto_sodai_layout else 0
    addressee_lines = _wrap_text(
        pdfmetrics,
        (label.get("addressee") or "").strip(),
        font_name=FONT_MINCHO,
        font_size=addressee_font_size,
        max_width=content_width - addressee_padding,
        max_lines=2,
    )
    if addressee_lines:
        # HTML keeps its 15.4mm address area and the addressee's 0.1mm margin,
        # including when the role title is omitted.
        addressee_top_y = (
            top_y - ((4.1 * 1.1 + 1.4 + 15.4 + 1.4 + 0.1) * mm)
            if monto_sodai_layout else origin_y + (14.5 * mm)
        )
        _draw_left_aligned_lines(
            pdf_canvas,
            x=content_x + addressee_padding,
            top_y=addressee_top_y,
            lines=addressee_lines,
            font_name=FONT_MINCHO,
            font_size=addressee_font_size,
            line_height=5.8 * 1.12 * mm if monto_sodai_layout else 6.8 * mm,
        )


def _draw_delivery_label(
    pdf_canvas,
    pdfmetrics,
    *,
    label: dict,
    origin_x: float,
    origin_y: float,
    mm: float,
) -> None:
    center_x = origin_x + ((LABEL_WIDTH_MM * mm) / 2)
    meta_font_size = 12
    officer_font_size = 18
    delivery_count = label.get("delivery_count")
    if delivery_count is None:
        delivery_count = label.get("household_count")
    if delivery_count is None:
        delivery_count = label.get("person_count") or 0
    meta_text = (
        f"{(label.get('district_short_name') or '').strip()}  "
        f"{delivery_count}名"
    ).strip()
    officer_text = f"{(label.get('officer_name') or '').strip()} 様".strip()

    meta_lines = _wrap_text(
        pdfmetrics,
        meta_text,
        font_name=FONT_GOTHIC,
        font_size=meta_font_size,
        max_width=(LABEL_WIDTH_MM - 12) * mm,
        max_lines=2,
    )
    officer_lines = _wrap_text(
        pdfmetrics,
        officer_text,
        font_name=FONT_MINCHO,
        font_size=officer_font_size,
        max_width=(LABEL_WIDTH_MM - 12) * mm,
        max_lines=2,
    )

    _draw_centered_lines(
        pdf_canvas,
        pdfmetrics,
        center_x=center_x,
        top_y=origin_y + (29.5 * mm),
        lines=meta_lines,
        font_name=FONT_GOTHIC,
        font_size=meta_font_size,
        line_height=5.0 * mm,
    )
    _draw_centered_lines(
        pdf_canvas,
        pdfmetrics,
        center_x=center_x,
        top_y=origin_y + (18.0 * mm),
        lines=officer_lines,
        font_name=FONT_MINCHO,
        font_size=officer_font_size,
        line_height=7.3 * mm,
    )


def _render_label_pdf(
    *,
    label_pages: list[list[dict | None]],
    title: str,
    draw_label,
) -> bytes:
    A4, mm, pdfmetrics, unicode_cid_font, canvas = _load_reportlab()
    _ensure_fonts(pdfmetrics, unicode_cid_font)

    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    pdf_canvas.setTitle(title)

    for page in label_pages:
        for index, label in enumerate(page):
            if not label:
                continue
            column = index % LABELS_PER_ROW
            row = index // LABELS_PER_ROW
            if row >= LABELS_PER_COLUMN:
                continue
            origin_x = PAGE_MARGIN_LEFT_MM * mm + (column * LABEL_WIDTH_MM * mm)
            origin_y = (
                (PAGE_MARGIN_BOTTOM_MM * mm)
                + ((LABELS_PER_COLUMN - 1 - row) * LABEL_HEIGHT_MM * mm)
            )
            draw_label(
                pdf_canvas,
                pdfmetrics,
                label=label,
                origin_x=origin_x,
                origin_y=origin_y,
                mm=mm,
            )
        pdf_canvas.showPage()

    pdf_canvas.save()
    return buffer.getvalue()


def render_address_label_pdf(*, label_pages: list[list[dict | None]], title: str) -> bytes:
    return _render_label_pdf(
        label_pages=label_pages,
        title=title,
        draw_label=_draw_address_label,
    )


def render_delivery_label_pdf(*, label_pages: list[list[dict | None]], title: str) -> bytes:
    return _render_label_pdf(
        label_pages=label_pages,
        title=title,
        draw_label=_draw_delivery_label,
    )


def render_monto_sodai_label_pdf(*, label_pages: list[list[dict | None]], title: str) -> bytes:
    return _render_label_pdf(
        label_pages=label_pages,
        title=title,
        draw_label=partial(_draw_address_label, monto_sodai_layout=True),
    )


__all__ = [
    "render_address_label_pdf",
    "render_delivery_label_pdf",
    "render_monto_sodai_label_pdf",
]
