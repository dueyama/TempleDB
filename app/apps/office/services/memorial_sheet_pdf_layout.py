from __future__ import annotations

from apps.core.services import tenant_policy as tenant_policy_services

from . import memorial_sheet_pdf_support as support


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
    offset = 0.0
    for segment in segments:
        text = support._verticalize_text(segment.get("text", ""))
        if not text:
            continue
        font_name = segment.get("font_name") or base_font_name
        font_size = segment.get("font_size") or base_font_size
        x_shift = segment.get("x_shift", 0.0)
        for character in text:
            char_width = pdfmetrics.stringWidth(character, font_name, font_size)
            pdf_canvas.setFont(font_name, font_size)
            pdf_canvas.drawString(
                x + x_shift - (char_width / 2),
                top_y - offset - font_size,
                character,
            )
            offset += char_step


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
    for line_index, line in enumerate(lines):
        x = right_x - (line_index * line_gap)
        base_font_name = line.get("font_name") or default_font_name
        base_font_size = line.get("font_size") or default_font_size
        _draw_vertical_segments(
            pdf_canvas,
            pdfmetrics,
            x=x,
            top_y=top_y,
            segments=line["segments"],
            base_font_name=base_font_name,
            base_font_size=base_font_size,
            char_step=line.get("char_step") or (base_font_size * 0.95),
        )


def _plain_vertical_line(
    text: str,
    *,
    font_name: str | None = None,
    font_size: float | None = None,
    x_shift: float = 0.0,
    char_step: float | None = None,
) -> dict:
    return {
        "segments": [
            {
                "text": text,
                "font_name": font_name,
                "font_size": font_size,
                "x_shift": x_shift,
            }
        ],
        "font_name": font_name,
        "font_size": font_size,
        "char_step": char_step,
    }


def _homyo_vertical_line(sheet: dict) -> dict:
    parts = sheet["deceased"].get("homyo_display_parts") or {
        "leading": sheet["deceased"].get("homyo_display_text", ""),
        "small": "",
        "trailing": "",
    }
    base_font_size = 27.0
    return {
        "segments": [
            {"text": parts.get("leading", ""), "font_size": base_font_size},
            {
                "text": parts.get("small", ""),
                "font_size": base_font_size * 0.72,
                "x_shift": base_font_size * 0.18,
            },
            {"text": parts.get("trailing", ""), "font_size": base_font_size},
        ],
        "font_name": support.FONT_MINCHO,
        "font_size": base_font_size,
        "char_step": base_font_size * 0.95,
    }


def _special_kijitsu_lines(label: str) -> list[dict]:
    if label == "満中陰（四十九日）":
        return [
            _plain_vertical_line("満中陰", font_size=15.0, char_step=14.2),
            _plain_vertical_line("（四十九日）", font_size=10.5, char_step=10.0),
        ]
    if label == "五七日":
        return [
            _plain_vertical_line("五七日", font_size=15.0, char_step=14.2),
            _plain_vertical_line("（三十五日）", font_size=10.5, char_step=10.0),
        ]
    return [_plain_vertical_line(label, font_size=15.0, char_step=14.2)]


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
    death_top_y = top_y
    homyo_top_y = top_y - (sheet["deceased"].get("homyo_center_offset_em", 0.0) * 27.0)
    zokumyo_top_y = top_y - (25.0 * mm)
    age_top_y = top_y - (20.0 * mm)

    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=support.PERSON_DEATH_X_MM * mm,
        top_y=death_top_y,
        lines=[
            _plain_vertical_line(
                f"{sheet['death_date_wareki']}往生",
                font_name=support.FONT_MINCHO,
                font_size=14.5,
                char_step=14.0,
            )
        ],
        default_font_name=support.FONT_MINCHO,
        default_font_size=14.5,
        line_gap=10.0,
    )
    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=support.PERSON_HOMYO_X_MM * mm,
        top_y=homyo_top_y,
        lines=[_homyo_vertical_line(sheet)],
        default_font_name=support.FONT_MINCHO,
        default_font_size=27.0,
        line_gap=10.0,
    )
    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=support.PERSON_ZOKUMYO_X_MM * mm,
        top_y=zokumyo_top_y,
        lines=[
            _plain_vertical_line(
                (
                    f"{tenant_policy_services.deceased_field_labels()['zokumyo']}　{sheet['deceased']['zokumyo']}"
                    if sheet["deceased"].get("homyo")
                    else "　"
                ),
                font_name=support.FONT_MINCHO,
                font_size=12.6,
                char_step=12.2,
            )
        ],
        default_font_name=support.FONT_MINCHO,
        default_font_size=12.6,
        line_gap=9.0,
    )
    age_text = (
        f"享年{sheet['deceased']['age_at_death']}{sheet['deceased']['age_unit']}"
        if sheet["deceased"].get("age_at_death")
        else "享年未記載"
    )
    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=support.PERSON_AGE_X_MM * mm,
        top_y=age_top_y,
        lines=[
            _plain_vertical_line(
                age_text,
                font_name=support.FONT_MINCHO,
                font_size=8.9,
                char_step=8.7,
            )
        ],
        default_font_name=support.FONT_MINCHO,
        default_font_size=8.9,
        line_gap=7.0,
    )

    if lower:
        rows = sheet["memorial_rows"]
        columns_right_x = support.LOWER_COLUMNS_RIGHT_X_MM * mm
        year_offset_y = 50.0 * mm
        temple_name_x = support.LOWER_TEMPLE_NAME_X_MM * mm
        temple_phone_x = support.LOWER_TEMPLE_PHONE_X_MM * mm
    else:
        rows = sheet["kijitsu_rows"]
        columns_right_x = support.UPPER_COLUMNS_RIGHT_X_MM * mm
        columns_left_x = support.UPPER_COLUMNS_LEFT_X_MM * mm
        year_offset_y = 48.0 * mm
        temple_name_x = support.UPPER_TEMPLE_NAME_X_MM * mm
        temple_phone_x = support.UPPER_TEMPLE_PHONE_X_MM * mm

    row_count = len(rows)
    if row_count > 1:
        if lower:
            column_step = support.LOWER_COLUMN_STEP_MM * mm
        else:
            column_step = (columns_right_x - columns_left_x) / (row_count - 1)
    else:
        column_step = 0.0

    for index, row in enumerate(rows):
        column_x = columns_right_x - (index * column_step)
        if lower:
            _draw_vertical_text(
                pdf_canvas,
                pdfmetrics,
                right_x=column_x,
                top_y=top_y,
                lines=[
                    _plain_vertical_line(
                        row["label"],
                        font_name=support.FONT_MINCHO,
                        font_size=17.0,
                        char_step=16.2,
                    )
                ],
                default_font_name=support.FONT_MINCHO,
                default_font_size=17.0,
                line_gap=10.0,
            )
            _draw_vertical_text(
                pdf_canvas,
                pdfmetrics,
                right_x=column_x,
                top_y=top_y - year_offset_y,
                lines=[
                    _plain_vertical_line(
                        f"{row['year_kanji']}年",
                        font_name=support.FONT_MINCHO,
                        font_size=14.6,
                        char_step=13.8,
                    )
                ],
                default_font_name=support.FONT_MINCHO,
                default_font_size=14.6,
                line_gap=10.0,
            )
        else:
            _draw_vertical_text(
                pdf_canvas,
                pdfmetrics,
                right_x=column_x,
                top_y=top_y,
                lines=_special_kijitsu_lines(row["label"]),
                default_font_name=support.FONT_MINCHO,
                default_font_size=15.0,
                line_gap=12.0,
            )
            _draw_vertical_text(
                pdf_canvas,
                pdfmetrics,
                right_x=column_x,
                top_y=top_y - year_offset_y,
                lines=[
                    _plain_vertical_line(
                        f"{row['month_day']}（{row['weekday']}）",
                        font_name=support.FONT_MINCHO,
                        font_size=13.7,
                        char_step=13.0,
                    )
                ],
                default_font_name=support.FONT_MINCHO,
                default_font_size=13.7,
                line_gap=10.0,
            )

    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=temple_name_x,
        top_y=top_y - (10.0 * mm if lower else 0.0),
        lines=[
            _plain_vertical_line(
                temple_identity.get("name", ""),
                font_name=support.FONT_MINCHO,
                font_size=13.7,
                char_step=13.1,
            )
        ],
        default_font_name=support.FONT_MINCHO,
        default_font_size=13.7,
        line_gap=10.0,
    )
    _draw_vertical_text(
        pdf_canvas,
        pdfmetrics,
        right_x=temple_phone_x,
        top_y=top_y - (10.0 * mm if lower else 0.0),
        lines=[
            _plain_vertical_line(
                temple_identity.get("phone", ""),
                font_name=support.FONT_MINCHO,
                font_size=9.8,
                char_step=9.4,
            )
        ],
        default_font_name=support.FONT_MINCHO,
        default_font_size=9.8,
        line_gap=8.0,
    )
