"""Shared embedded fonts and first-page previews for office PDF documents."""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


@lru_cache(maxsize=1)
def ensure_noto_fonts():
    root = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    for family in ("Sans", "Serif"):
        for weight in ("Regular", "Bold"):
            name = "TempleNoto" + family + ("Bold" if weight == "Bold" else "")
            pdfmetrics.registerFont(TTFont(name, str(root / f"Noto{family}JP-{weight}.ttf")))


def render_pdf_first_page_png(data: bytes) -> bytes:
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(data) as document:
        page = document[0]
        try:
            bitmap = page.render(scale=1.5)
            try:
                output = BytesIO()
                bitmap.to_pil().save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
