"""Server-generated service information; embeds bundled Japanese Noto fonts."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .pdf_rendering import ensure_noto_fonts as _fonts
from .pdf_rendering import render_pdf_first_page_png


def render_service_information_pdf(context):
    _fonts()
    output = BytesIO()
    normal = ParagraphStyle(
        "text", fontName="TempleNotoSans", fontSize=9, leading=13, wordWrap="CJK", alignment=TA_LEFT
    )
    small = ParagraphStyle("small", parent=normal, fontSize=8, leading=11)
    title = ParagraphStyle(
        "title", parent=normal, fontName="TempleNotoSerifBold", fontSize=19, leading=25
    )
    heading = ParagraphStyle("heading", parent=title, fontSize=11, leading=16, spaceAfter=6)

    def p(value, style=normal):
        return Paragraph(escape(str(value or "未設定")).replace("\n", "<br/>"), style)

    def table(rows, widths, *, repeat=0):
        result = Table(rows, colWidths=widths, hAlign="LEFT", repeatRows=repeat)
        result.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return result

    card_label = ParagraphStyle(
        "card-label", parent=small, fontName="TempleNotoSansBold", fontSize=7, leading=9
    )
    card_text = ParagraphStyle("card-text", parent=small, fontSize=8, leading=10)
    card_name = ParagraphStyle(
        "card-name", parent=card_text, fontName="TempleNotoSansBold", fontSize=8.5, leading=11
    )
    secondary = ParagraphStyle("secondary", parent=small, fontSize=7, leading=9)

    def box(content, width, *, dashed=False, padding=3 * mm, height=None):
        result = Table(
            [[content]], colWidths=[width], rowHeights=[height], hAlign="LEFT", splitInRow=1
        )
        line = ("BOX", (0, 0), (-1, -1), 0.5, colors.black)
        if dashed:
            line += (1, [2, 2])
        result.setStyle(
            TableStyle(
                [
                    line,
                    ("LEFTPADDING", (0, 0), (-1, -1), padding),
                    ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ]
            )
        )
        return result

    def columns(items, widths, gap):
        cells, sizes = [], []
        for index, (item, width) in enumerate(zip(items, widths, strict=False)):
            if index:
                cells.append("")
                sizes.append(gap)
            cells.append(item)
            sizes.append(width)
        result = Table([cells], colWidths=sizes, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return result

    story = []
    cards = []
    labels = context.get("deceased_labels", {})
    for item in context["participant_cards"]:

        def lines(*keys, item=item):
            return "\n".join(str(item.get(key) or "") for key in keys if item.get(key))

        name = item.get("person_name", "") + (" （基準）" if item.get("is_current") else "")
        rows = [
            (
                labels.get("zokumyo", "俗名"),
                name + ("\n" + item["person_kana"] if item.get("person_kana") else ""),
            ),
            (labels.get("kaimyo", "法名"), lines("kaimyo", "kaimyo_kana")),
            ("法要", item.get("service_label")),
        ]
        if item.get("sutra_label"):
            rows.append(("読経", item["sutra_label"]))
        rows += [
            ("続柄", item.get("relationship_label")),
            ("命日", lines("death_date", "death_date_wareki")),
            ("予定命日", lines("planned_death_date", "planned_death_date_wareki")),
            ("享年", lines("age_at_death", "estimated_birth_year")),
            ("戸主", item.get("household_name")),
        ]
        cells = []
        for index, (label, value) in enumerate(rows):
            parts = str(value or "未設定").split("\n")
            values = [p(parts[0], card_name if index < 2 else card_text)]
            values.extend(p(part, secondary) for part in parts[1:])
            cells.append([p(label, card_label), values])
        card = table(cells, [14 * mm, 41 * mm])
        card.setStyle(
            TableStyle(
                [("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]
            )
        )
        cards.append(box(card, 60 * mm, dashed=True, padding=2.5 * mm))
    for index in range(0, len(cards), 3):
        batch = cards[index : index + 3]
        story += [columns(batch, [60 * mm] * len(batch), 3 * mm), Spacer(1, 6 * mm)]
    story += [
        p(context["document_title"], title),
        columns(
            [
                p(f"{context['household_label']} / 出力日 {context['print_date']}", small),
                p(f"対象 {context['participant_count']}名", small),
            ],
            [159 * mm, 27 * mm],
            0,
        ),
        Spacer(1, 3 * mm),
    ]
    summary = [
        ("対象法要", " / ".join(context["service_labels"])),
        ("予定日", context["scheduled_date_label"]),
        ("予定時刻", context["scheduled_time_label"]),
        ("場所", context["schedule"].location),
        ("状態", context["schedule"].get_status_display()),
    ]
    summary_boxes = [box([p(a, secondary), Spacer(1, 2 * mm), p(b)], 34 * mm) for a, b in summary]
    # Give every overview box the same height, like the web grid.
    max_height = max(item.wrap(34 * mm, 1000)[1] for item in summary_boxes)
    summary_boxes = [
        box([p(a, secondary), Spacer(1, 2 * mm), p(b)], 34 * mm, height=max_height)
        for a, b in summary
    ]
    story += [columns(summary_boxes, [34 * mm] * 5, 4 * mm), Spacer(1, 5 * mm)]
    if context["service_notes"]:
        story += [
            box([p("今回の法要メモ", heading), p(context["service_notes"])], 186 * mm),
            Spacer(1, 4 * mm),
        ]
    future = context["future_memorial_rows"]
    future_content = [p("この家の今後3年の回忌予定", heading)]
    if future:
        rows = [[p(v, small) for v in ["対象", "回忌", "基準日", "予定", "状態"]]]
        for row in future:
            status = f"{row['kind_label']} / {row['status_label']}"
            if row.get("completion_note"):
                status += "\n" + row["completion_note"]
            rows.append(
                [
                    p(v, small)
                    for v in [
                        row["person_name"],
                        row["service_label"],
                        row["target_date"],
                        row.get("scheduled_date"),
                        status,
                    ]
                ]
            )
        future_table = table(rows, [39 * mm, 28 * mm, 32 * mm, 32 * mm, 49 * mm], repeat=1)
        future_table.setStyle(
            TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f4"))])
        )
        future_content.append(future_table)
    else:
        future_content.append(p("この家の今後3年の回忌予定はありません。", small))
    story += [box(future_content, 186 * mm), Spacer(1, 6 * mm), p("個人別メモ", heading)]
    for item in context["participant_cards"]:
        memo_content = [p(f"{item['person_name']} に対するメモ", heading)]
        if not item.get("note_items"):
            memo_content.append(
                box(p("この個人に紐づく過去メモはありません。", small), 180 * mm, padding=2 * mm)
            )
        for note in item.get("note_items", []):
            memo_content += [
                box(
                    [p(f"{note['label']} {note.get('meta', '')}", small), p(note["body"])],
                    180 * mm,
                    padding=2 * mm,
                ),
                Spacer(1, 2 * mm),
            ]
        story += [box(memo_content, 186 * mm), Spacer(1, 4 * mm)]
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=context["document_title"],
        author="TempleDB",
    )

    doc.build(story)
    return output.getvalue()


def render_service_information_pdf_preview(context):
    """Render the actual PDF first page, without depending on browser PDF plugins."""
    return render_pdf_first_page_png(render_service_information_pdf(context))
