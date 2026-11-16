"""PDF renderer for memorial notice documents.

This module is the owner for the `?format=pdf` path used by the memorial
notice view. It intentionally stays ReportLab-only so the printed layout does
not depend on a browser binary being available on the operator machine.
"""

from __future__ import annotations

from io import BytesIO

from apps.core.services import tenant_policy as tenant_policy_services

PAGE_MARGIN_LEFT_MM = 14.0
PAGE_MARGIN_RIGHT_MM = 14.0
PAGE_MARGIN_TOP_MM = 14.0
PAGE_MARGIN_BOTTOM_MM = 12.0

FONT_GOTHIC = "HeiseiKakuGo-W5"
FONT_MINCHO = "HeiseiMin-W3"

TABLE_COLUMN_WIDTH_RATIOS = [0.18, 0.16, 0.22, 0.23, 0.21]
TABLE_HEADER_HEIGHT_MM = 8.0
TABLE_ROW_HEIGHT_MM = 19.0
TABLE_REFERENCE_ROW_HEIGHT_MM = 9.0


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
    preserve_newlines: bool = False,
) -> list[str]:
    raw_lines = text.splitlines() if preserve_newlines else [text]
    wrapped: list[str] = []

    for raw_line in raw_lines:
        normalized = raw_line if preserve_newlines else " ".join(raw_line.split())
        if not normalized:
            wrapped.append("")
            continue

        current = ""
        for character in normalized:
            candidate = f"{current}{character}"
            if (
                not current
                or _string_width(pdfmetrics, candidate, font_name, font_size) <= max_width
            ):
                current = candidate
                continue
            wrapped.append(current)
            current = character
        if current:
            wrapped.append(current)

    if max_lines is None or len(wrapped) <= max_lines:
        return wrapped

    kept = wrapped[:max_lines]
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


def _draw_lines(
    pdf_canvas,
    *,
    x: float,
    top_y: float,
    lines: list[str],
    font_name: str,
    font_size: float,
    line_height: float,
) -> float:
    pdf_canvas.setFont(font_name, font_size)
    for index, line in enumerate(lines):
        pdf_canvas.drawString(x, top_y - font_size - (index * line_height), line)
    if not lines:
        return 0.0
    return font_size + ((len(lines) - 1) * line_height)


def _draw_centered_lines(
    pdf_canvas,
    pdfmetrics,
    *,
    center_x: float,
    top_y: float,
    lines: list[str],
    font_name: str,
    font_size: float,
    line_height: float,
) -> float:
    pdf_canvas.setFont(font_name, font_size)
    for index, line in enumerate(lines):
        pdf_canvas.drawString(
            center_x - (_string_width(pdfmetrics, line, font_name, font_size) / 2),
            top_y - font_size - (index * line_height),
            line,
        )
    if not lines:
        return 0.0
    return font_size + ((len(lines) - 1) * line_height)


def _rem_to_pt(rem_value: float) -> float:
    return rem_value * 12.0


def _draw_boxed_table(
    pdf_canvas,
    pdfmetrics,
    *,
    page_width: float,
    table_top_y: float,
    entries: list[dict],
    table_font_size: float,
    mm: float,
) -> float:
    deceased_labels = tenant_policy_services.deceased_field_labels()
    table_labels = tenant_policy_services.memorial_notice_table_labels()
    content_width = page_width - ((PAGE_MARGIN_LEFT_MM + PAGE_MARGIN_RIGHT_MM) * mm)
    left_x = PAGE_MARGIN_LEFT_MM * mm
    column_widths = [content_width * ratio for ratio in TABLE_COLUMN_WIDTH_RATIOS]
    line_height = table_font_size * 1.3

    row_specs: list[dict] = [
        {
            "kind": "header",
            "height": TABLE_HEADER_HEIGHT_MM * mm,
            "values": [
                table_labels["death_date"],
                table_labels["memorial_service"],
                deceased_labels["kaimyo"],
                deceased_labels["zokumyo"],
                table_labels["other_note"],
            ],
        }
    ]
    for entry in entries:
        if entry.get("row_kind") == "reference_heading":
            row_specs.append(
                {
                    "kind": "reference_heading",
                    "height": TABLE_REFERENCE_ROW_HEIGHT_MM * mm,
                    "value": entry.get("reference_heading", ""),
                }
            )
            continue
        row_specs.append(
            {
                "kind": "entry",
                "height": TABLE_ROW_HEIGHT_MM * mm,
                "values": [
                    "\n".join(
                        [
                            line
                            for line in [
                                entry.get("target_date_year", ""),
                                entry.get("target_date_main", ""),
                            ]
                            if line
                        ]
                    ),
                    entry.get("label", ""),
                    entry.get("kaimyo", ""),
                    "\n".join(
                        [
                            line
                            for line in [
                                entry.get("zokumyo_name", ""),
                                entry.get("zokumyo_age", ""),
                            ]
                            if line
                        ]
                    ),
                    entry.get("other_note", ""),
                ],
            }
        )

    current_y = table_top_y
    for row in row_specs:
        row_height = row["height"]
        bottom_y = current_y - row_height
        pdf_canvas.rect(left_x, bottom_y, content_width, row_height, stroke=1, fill=0)

        if row["kind"] == "reference_heading":
            heading_lines = _wrap_text(
                pdfmetrics,
                row["value"],
                font_name=FONT_GOTHIC,
                font_size=table_font_size,
                max_width=content_width - (4 * mm),
                max_lines=1,
                preserve_newlines=True,
            )
            _draw_lines(
                pdf_canvas,
                x=left_x + (2 * mm),
                top_y=current_y - (1.7 * mm),
                lines=heading_lines,
                font_name=FONT_GOTHIC,
                font_size=table_font_size,
                line_height=line_height,
            )
            current_y = bottom_y
            continue

        cell_x = left_x
        for column_index, column_width in enumerate(column_widths):
            if column_index > 0:
                pdf_canvas.line(cell_x, current_y, cell_x, bottom_y)
            raw_value = row["values"][column_index]
            cell_font = FONT_GOTHIC
            if row["kind"] == "header":
                lines = [raw_value]
                draw_top_y = current_y - (1.6 * mm)
                _draw_centered_lines(
                    pdf_canvas,
                    pdfmetrics,
                    center_x=cell_x + (column_width / 2),
                    top_y=draw_top_y,
                    lines=lines,
                    font_name=FONT_GOTHIC,
                    font_size=table_font_size,
                    line_height=line_height,
                )
                cell_x += column_width
                continue

            max_lines = 3 if column_index == 4 else 2
            lines = _wrap_text(
                pdfmetrics,
                raw_value,
                font_name=cell_font,
                font_size=table_font_size,
                max_width=column_width - (3 * mm),
                max_lines=max_lines,
                preserve_newlines=True,
            )
            _draw_lines(
                pdf_canvas,
                x=cell_x + (1.5 * mm),
                top_y=current_y - (1.8 * mm),
                lines=lines,
                font_name=cell_font,
                font_size=table_font_size,
                line_height=line_height,
            )
            cell_x += column_width

        current_y = bottom_y

    return current_y


def render_memorial_notice_pdf(*, context: dict) -> bytes:
    A4, mm, pdfmetrics, unicode_cid_font, canvas = _load_reportlab()
    _ensure_fonts(pdfmetrics, unicode_cid_font)

    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    heading_labels = tenant_policy_services.print_heading_labels()
    pdf_canvas.setTitle(
        f"{heading_labels['memorial_notice']} {context.get('target_year_label', '')}".strip()
    )

    page_width, page_height = A4
    recipient_font_size = _rem_to_pt(context["notice_style"]["recipient_font_size"])
    body_font_size = _rem_to_pt(context["notice_style"]["body_font_size"])
    signature_font_size = _rem_to_pt(context["notice_style"]["signature_font_size"])
    table_font_size = _rem_to_pt(context["notice_style"]["table_font_size"])

    content_width = page_width - ((PAGE_MARGIN_LEFT_MM + PAGE_MARGIN_RIGHT_MM) * mm)
    intro_max_width = content_width

    for document in context.get("documents", []):
        current_y = page_height - (PAGE_MARGIN_TOP_MM * mm)

        recipient_lines = _wrap_text(
            pdfmetrics,
            f"{document.get('recipient_name', '').strip()} 様".strip(),
            font_name=FONT_MINCHO,
            font_size=recipient_font_size,
            max_width=content_width,
            max_lines=2,
            preserve_newlines=True,
        )
        recipient_height = _draw_lines(
            pdf_canvas,
            x=PAGE_MARGIN_LEFT_MM * mm,
            top_y=current_y,
            lines=recipient_lines,
            font_name=FONT_MINCHO,
            font_size=recipient_font_size,
            line_height=recipient_font_size * 1.15,
        )
        current_y -= recipient_height + (7 * mm)

        intro_lines = _wrap_text(
            pdfmetrics,
            context.get("intro_text", ""),
            font_name=FONT_GOTHIC,
            font_size=body_font_size,
            max_width=intro_max_width,
            max_lines=5,
            preserve_newlines=True,
        )
        intro_height = _draw_lines(
            pdf_canvas,
            x=PAGE_MARGIN_LEFT_MM * mm,
            top_y=current_y,
            lines=intro_lines,
            font_name=FONT_GOTHIC,
            font_size=body_font_size,
            line_height=body_font_size * 1.45,
        )
        current_y -= intro_height + (6 * mm)

        current_y = _draw_boxed_table(
            pdf_canvas,
            pdfmetrics,
            page_width=page_width,
            table_top_y=current_y,
            entries=document.get("table_entries", []),
            table_font_size=table_font_size,
            mm=mm,
        )
        current_y -= 7 * mm

        outro_lines = _wrap_text(
            pdfmetrics,
            context.get("outro_text", ""),
            font_name=FONT_GOTHIC,
            font_size=body_font_size,
            max_width=content_width,
            max_lines=6,
            preserve_newlines=True,
        )
        outro_height = _draw_lines(
            pdf_canvas,
            x=PAGE_MARGIN_LEFT_MM * mm,
            top_y=current_y,
            lines=outro_lines,
            font_name=FONT_GOTHIC,
            font_size=body_font_size,
            line_height=body_font_size * 1.45,
        )
        current_y -= outro_height + (8 * mm)

        signature_lines = _wrap_text(
            pdfmetrics,
            context.get("signature_text", ""),
            font_name=FONT_GOTHIC,
            font_size=signature_font_size,
            max_width=content_width,
            max_lines=4,
            preserve_newlines=True,
        )
        _draw_lines(
            pdf_canvas,
            x=page_width - (PAGE_MARGIN_RIGHT_MM * mm) - (54 * mm),
            top_y=current_y,
            lines=signature_lines,
            font_name=FONT_GOTHIC,
            font_size=signature_font_size,
            line_height=signature_font_size * 1.35,
        )

        pdf_canvas.showPage()

    pdf_canvas.save()
    return buffer.getvalue()


__all__ = ["render_memorial_notice_pdf"]
