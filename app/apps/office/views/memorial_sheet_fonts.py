from __future__ import annotations

from django.http import FileResponse, Http404, HttpRequest, HttpResponse

from apps.office.services.memorial_sheet_web_fonts import (
    build_memorial_sheet_web_font_css,
    memorial_sheet_web_font_path,
)


def memorial_sheet_font_css(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(
        build_memorial_sheet_web_font_css(),
        content_type="text/css; charset=utf-8",
    )
    response["Cache-Control"] = "private, max-age=300"
    return response


def memorial_sheet_font_file(request: HttpRequest, font_slug: str) -> HttpResponse:
    try:
        path = memorial_sheet_web_font_path(font_slug)
    except KeyError as exc:
        raise Http404("unknown memorial sheet font") from exc
    if not path.is_file():
        raise Http404("memorial sheet font file not found")
    response = FileResponse(path.open("rb"), content_type="font/ttf", filename=path.name)
    response["Cache-Control"] = "private, max-age=86400"
    return response
