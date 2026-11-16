"""Read-only household contact sheet; PDF and HTML share the same rows."""

from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.imports.models import Household, HouseholdProfile

from .household_editing_core import _household_display_head_name, _household_display_head_name_kana
from .pdf_rendering import ensure_noto_fonts


def build_household_information(household: Household) -> dict:
    source_id = household.legacy_source_id or household.batch.source.source_id
    profile = HouseholdProfile.objects.select_related("district").filter(
        source__source_id=source_id, household_uid=household.household_uid,
    ).first()
    postal_code = (household.postal_code or "").strip()
    if len(postal_code) == 7 and postal_code.isdigit():
        postal_code = f"{postal_code[:3]}-{postal_code[3:]}"
    rows = [
        ("氏名", _household_display_head_name(household)),
        ("フリガナ", _household_display_head_name_kana(household)),
        ("郵便番号", f"〒{postal_code}" if postal_code else ""),
        ("住所", "\n".join(value.strip() for value in (
            household.address_line1, household.address_line2, household.address_line3,
        ) if value and value.strip())),
        ("電話番号", household.phone),
        ("携帯電話", household.mobile),
        ("FAX", household.fax),
        ("メール", household.email),
        ("地区", profile.district.name if profile is not None and profile.district_id else ""),
        ("送付区分", profile.get_delivery_method_display() if profile is not None else ""),
    ]
    return {
        "household_uid": household.household_uid,
        "household_name": _household_display_head_name(household),
        "print_date": timezone.localdate(),
        "information_rows": [{"label": label, "value": value or "未設定"} for label, value in rows],
    }


def render_household_information_pdf(context: dict) -> bytes:
    ensure_noto_fonts()
    output = BytesIO()
    text = ParagraphStyle("contact", fontName="TempleNotoSans", fontSize=11, leading=17, wordWrap="CJK")
    label = ParagraphStyle("label", parent=text, fontName="TempleNotoSansBold", fontSize=10)
    title = ParagraphStyle("title", parent=text, fontName="TempleNotoSerifBold", fontSize=22, leading=30)
    meta = ParagraphStyle("meta", parent=text, fontSize=9, leading=14)

    def paragraph(value, style=text):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)

    table = Table([
        [paragraph(row["label"], label), paragraph(row["value"])] for row in context["information_rows"]
    ], colWidths=[34 * mm, 152 * mm], hAlign="LEFT", splitInRow=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"{context['household_name']}の戸主情報", author="TempleDB",
    )
    document.build([
        paragraph("戸主情報", title), Spacer(1, 3 * mm),
        paragraph(f"台帳ID {context['household_uid']} / 出力日 {context['print_date'].isoformat()}", meta),
        Spacer(1, 7 * mm), table,
    ])
    return output.getvalue()
