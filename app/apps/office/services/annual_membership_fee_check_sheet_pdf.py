from __future__ import annotations

from io import BytesIO

FONT_GOTHIC = "HeiseiKakuGo-W5"
FONT_MINCHO = "HeiseiMin-W3"

PAGE_WIDTH_MM = 420.0
PAGE_HEIGHT_MM = 297.0
PAGE_MARGIN_X_MM = 11.5
PAGE_MARGIN_TOP_MM = 10.0
PAGE_MARGIN_BOTTOM_MM = 9.0
COLUMN_GAP_MM = 5.2
REGISTRATION_MARKER_MARGIN_MM = 6.0
REGISTRATION_MARKER_SIZE_MM = 4.5


def _load_reportlab():
    try:
        from reportlab.lib.pagesizes import A3, landscape
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
        raise RuntimeError("reportlab is required for PDF rendering.") from exc
    return landscape(A3), mm, pdfmetrics, UnicodeCIDFont, canvas


def _ensure_fonts(pdfmetrics, unicode_cid_font) -> None:
    for font_name in (FONT_GOTHIC, FONT_MINCHO):
        try:
            pdfmetrics.getFont(font_name)
        except KeyError:
            pdfmetrics.registerFont(unicode_cid_font(font_name))


def _string_width(pdfmetrics, text: str, font_name: str, font_size: float) -> float:
    return pdfmetrics.stringWidth(text, font_name, font_size)


def _fit_text(pdfmetrics, text: str, *, font_name: str, font_size: float, max_width: float) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned or _string_width(pdfmetrics, cleaned, font_name, font_size) <= max_width:
        return cleaned
    ellipsis = "..."
    trimmed = cleaned
    while trimmed and _string_width(
        pdfmetrics,
        f"{trimmed}{ellipsis}",
        font_name,
        font_size,
    ) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}{ellipsis}" if trimmed else ellipsis


def _metrics_for_density(density: str) -> dict[str, float]:
    if density == "tight":
        return {
            "district_font": 7.4,
            "member_font": 6.9,
            "header_height_mm": 5.6,
            "row_height_mm": 4.25,
            "box_size_mm": 3.55,
            "district_gap_mm": 1.3,
        }
    if density == "compact":
        return {
            "district_font": 8.7,
            "member_font": 8.1,
            "header_height_mm": 6.4,
            "row_height_mm": 5.1,
            "box_size_mm": 4.1,
            "district_gap_mm": 1.8,
        }
    return {
        "district_font": 10.2,
        "member_font": 9.3,
        "header_height_mm": 7.4,
        "row_height_mm": 6.2,
        "box_size_mm": 4.8,
        "district_gap_mm": 2.2,
    }


def _page_header_content_top_mm() -> float:
    return PAGE_HEIGHT_MM - PAGE_MARGIN_TOP_MM - 22.0 - 5.0


def _registration_markers() -> list[dict]:
    margin = REGISTRATION_MARKER_MARGIN_MM
    size = REGISTRATION_MARKER_SIZE_MM
    return [
        {"key": "top_left", "x": margin, "bottom_y": PAGE_HEIGHT_MM - margin - size, "size": size},
        {
            "key": "top_right",
            "x": PAGE_WIDTH_MM - margin - size,
            "bottom_y": PAGE_HEIGHT_MM - margin - size,
            "size": size,
        },
        {"key": "bottom_left", "x": margin, "bottom_y": margin, "size": size},
        {
            "key": "bottom_right",
            "x": PAGE_WIDTH_MM - margin - size,
            "bottom_y": margin,
            "size": size,
        },
    ]


def build_annual_membership_fee_check_sheet_layout(*, context: dict) -> dict:
    column_count = max(int(context.get("column_count") or 1), 1)
    column_gap = COLUMN_GAP_MM
    content_left = PAGE_MARGIN_X_MM
    content_width = PAGE_WIDTH_MM - (PAGE_MARGIN_X_MM * 2)
    column_width = (content_width - (column_gap * (column_count - 1))) / column_count
    metrics = _metrics_for_density(str(context.get("density") or "normal"))
    header_height = metrics["header_height_mm"]
    row_height = metrics["row_height_mm"]
    box_size = metrics["box_size_mm"]
    district_gap = metrics["district_gap_mm"]
    content_top_y = _page_header_content_top_mm()
    bottom_y = PAGE_MARGIN_BOTTOM_MM

    events: list[dict] = []
    boxes: list[dict] = []
    column_index = 0
    y = content_top_y

    for group in context.get("district_groups", []):
        rows = group.get("rows", [])
        if not rows:
            continue
        group_height = header_height + (len(rows) * row_height) + district_gap
        if y - group_height < bottom_y and y < content_top_y:
            column_index = min(column_index + 1, column_count - 1)
            y = content_top_y
        x = content_left + (column_index * (column_width + column_gap))
        events.append(
            {
                "type": "district",
                "x": x,
                "y": y,
                "width": column_width,
                "name": group.get("name", ""),
                "metrics": metrics,
            }
        )
        y -= header_height

        for row in rows:
            if y - row_height < bottom_y:
                column_index = min(column_index + 1, column_count - 1)
                y = content_top_y
                x = content_left + (column_index * (column_width + column_gap))
                events.append(
                    {
                        "type": "district",
                        "x": x,
                        "y": y,
                        "width": column_width,
                        "name": f"{group.get('name', '')}（続き）",
                        "metrics": metrics,
                    }
                )
                y -= header_height

            box_bottom_y = y - (row_height * 0.76)
            event = {
                "type": "row",
                "x": x,
                "y": y,
                "width": column_width,
                "row_height": row_height,
                "box_x": x,
                "box_bottom_y": box_bottom_y,
                "box_size": box_size,
                "row": row,
                "district_name": group.get("name", ""),
                "metrics": metrics,
            }
            events.append(event)
            boxes.append(
                {
                    "household_id": row.get("household_id", ""),
                    "head_name": row.get("head_name", ""),
                    "district_name": group.get("name", ""),
                    "x": x,
                    "bottom_y": box_bottom_y,
                    "size": box_size,
                }
            )
            y -= row_height
        y -= district_gap

    return {
        "page_width_mm": PAGE_WIDTH_MM,
        "page_height_mm": PAGE_HEIGHT_MM,
        "column_count": column_count,
        "registration_markers": _registration_markers(),
        "events": events,
        "boxes": boxes,
    }


def _draw_right_text(
    pdf_canvas,
    pdfmetrics,
    *,
    right_x: float,
    y: float,
    text: str,
    font: str,
    size: float,
) -> None:
    pdf_canvas.setFont(font, size)
    pdf_canvas.drawString(right_x - _string_width(pdfmetrics, text, font, size), y, text)


def _draw_page_header(
    pdf_canvas,
    pdfmetrics,
    *,
    context: dict,
    page_width: float,
    page_height: float,
    mm: float,
) -> float:
    left_x = PAGE_MARGIN_X_MM * mm
    right_x = page_width - (PAGE_MARGIN_X_MM * mm)
    top_y = page_height - (PAGE_MARGIN_TOP_MM * mm)

    pdf_canvas.setFont(FONT_MINCHO, 23)
    pdf_canvas.drawString(left_x, top_y - (9.0 * mm), f"{context['year']}年 護持会費")
    pdf_canvas.setFont(FONT_GOTHIC, 12)
    pdf_canvas.drawString(left_x, top_y - (16.8 * mm), "受領チェックシート")
    _draw_right_text(
        pdf_canvas,
        pdfmetrics,
        right_x=right_x,
        y=top_y - (9.5 * mm),
        text=f"{context['district_count']}地区 / {context['member_count']}件",
        font=FONT_GOTHIC,
        size=11,
    )
    separator_y = top_y - (22.0 * mm)
    pdf_canvas.setLineWidth(1.1)
    pdf_canvas.line(left_x, separator_y, right_x, separator_y)


def _draw_registration_markers(pdf_canvas, *, mm: float) -> None:
    pdf_canvas.setFillColorRGB(0, 0, 0)
    for marker in _registration_markers():
        pdf_canvas.rect(
            marker["x"] * mm,
            marker["bottom_y"] * mm,
            marker["size"] * mm,
            marker["size"] * mm,
            stroke=0,
            fill=1,
        )
    pdf_canvas.setFillColorRGB(0, 0, 0)


def render_annual_membership_fee_check_sheet_pdf(*, context: dict) -> bytes:
    page_size, mm, pdfmetrics, unicode_cid_font, canvas = _load_reportlab()
    _ensure_fonts(pdfmetrics, unicode_cid_font)

    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=page_size, pageCompression=1)
    pdf_canvas.setTitle(f"{context['year']}年 護持会費 受領チェックシート")

    page_width, page_height = page_size
    _draw_registration_markers(pdf_canvas, mm=mm)
    _draw_page_header(
        pdf_canvas,
        pdfmetrics,
        context=context,
        page_width=page_width,
        page_height=page_height,
        mm=mm,
    )
    layout = build_annual_membership_fee_check_sheet_layout(context=context)
    for event in layout["events"]:
        metrics = event["metrics"]
        x = event["x"] * mm
        y = event["y"] * mm
        width = event["width"] * mm
        if event["type"] == "district":
            header_height = metrics["header_height_mm"] * mm
            pdf_canvas.setLineWidth(0.65)
            pdf_canvas.line(
                x,
                y - (header_height * 0.92),
                x + width,
                y - (header_height * 0.92),
            )
            pdf_canvas.setFont(FONT_GOTHIC, metrics["district_font"])
            pdf_canvas.drawString(
                x,
                y - (metrics["district_font"] * 0.92),
                _fit_text(
                    pdfmetrics,
                    event.get("name", ""),
                    font_name=FONT_GOTHIC,
                    font_size=metrics["district_font"],
                    max_width=width,
                ),
            )
            continue

        row = event["row"]
        row_height = event["row_height"] * mm
        box_size = event["box_size"] * mm
        box_y = event["box_bottom_y"] * mm
        pdf_canvas.setLineWidth(0.7)
        pdf_canvas.rect(x, box_y, box_size, box_size, stroke=1, fill=0)
        name_x = x + box_size + (2.0 * mm)
        name_width = width - box_size - (2.0 * mm)
        pdf_canvas.setFont(FONT_GOTHIC, metrics["member_font"])
        pdf_canvas.drawString(
            name_x,
            y - (metrics["member_font"] * 0.85),
            _fit_text(
                pdfmetrics,
                row.get("head_name", ""),
                font_name=FONT_GOTHIC,
                font_size=metrics["member_font"],
                max_width=name_width,
            ),
        )
        pdf_canvas.setLineWidth(0.25)
        pdf_canvas.line(
            x,
            y - row_height + (0.3 * mm),
            x + width,
            y - row_height + (0.3 * mm),
        )

    pdf_canvas.showPage()
    pdf_canvas.save()
    return buffer.getvalue()


__all__ = [
    "build_annual_membership_fee_check_sheet_layout",
    "render_annual_membership_fee_check_sheet_pdf",
]
