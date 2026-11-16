from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.urls import reverse

from config.runtime_paths import private_root


@dataclass(frozen=True)
class MemorialSheetWebFont:
    slug: str
    display_name: str
    css_family: str
    filename: str
    mac_resource_name: str
    resource_id: int
    fallback_family: str


MEMORIAL_SHEET_WEB_FONTS: dict[str, MemorialSheetWebFont] = {
    "hg-gyosho": MemorialSheetWebFont(
        slug="hg-gyosho",
        display_name="HG行書体",
        css_family="TempleDB-HGGyoshotai",
        filename="hg-gyosho.ttf",
        mac_resource_name="HG行書体",
        resource_id=16536,
        fallback_family='"HGGyoshotai", "HG行書体", "Hiragino Mincho ProN", "ヒラギノ明朝 ProN", serif',
    ),
    "agenda-jinmei-gyosho-l1": MemorialSheetWebFont(
        slug="agenda-jinmei-gyosho-l1",
        display_name="AGENDA人名行書体L1",
        css_family="TempleDB-AGENDAJinmeiGyoshotaiL1",
        filename="agenda-jinmei-gyosho-l1.ttf",
        mac_resource_name="AGENDA人名行書体L1",
        resource_id=16620,
        fallback_family='"AGENDAJinmeiGyoshotaiL1", "AGENDA人名行書体L1", "Hiragino Mincho ProN", "ヒラギノ明朝 ProN", serif',
    ),
    "dfp-gyosho": MemorialSheetWebFont(
        slug="dfp-gyosho",
        display_name="DFP行書体",
        css_family="TempleDB-DFPGyoSho-Lt",
        filename="dfp-gyosho.ttf",
        mac_resource_name="ＤＦＰ行書体",
        resource_id=16547,
        fallback_family='"DFPGyoSho-Lt", "DFGyoSho-Lt-MP-RKSJ-H", "ＤＦＰ行書体", "Hiragino Mincho ProN", serif',
    ),
}


def memorial_sheet_private_font_dir() -> Path:
    return private_root() / "fonts" / "memorial_sheet"


def memorial_sheet_web_font_path(font_slug: str) -> Path:
    font = MEMORIAL_SHEET_WEB_FONTS.get(font_slug)
    if font is None:
        raise KeyError(font_slug)
    return memorial_sheet_private_font_dir() / font.filename


def available_memorial_sheet_web_fonts() -> list[MemorialSheetWebFont]:
    return [
        font
        for font in MEMORIAL_SHEET_WEB_FONTS.values()
        if memorial_sheet_web_font_path(font.slug).is_file()
    ]


def memorial_sheet_font_family_value(font_slug: str) -> str:
    font = MEMORIAL_SHEET_WEB_FONTS[font_slug]
    return f'"{font.css_family}", {font.fallback_family}'


def build_memorial_sheet_web_font_css() -> str:
    lines = [
        "/* TempleDB local memorial sheet fonts. Font files are private runtime assets. */",
    ]
    for font in available_memorial_sheet_web_fonts():
        font_url = reverse(
            "office:memorial_sheet_font_file",
            kwargs={"font_slug": font.slug},
        )
        lines.extend(
            [
                "@font-face {",
                f'  font-family: "{font.css_family}";',
                f'  src: url("{font_url}") format("truetype");',
                "  font-style: normal;",
                "  font-weight: 400;",
                "  font-display: swap;",
                "}",
            ]
        )
    return "\n".join(lines) + "\n"
