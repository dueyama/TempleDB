from __future__ import annotations

from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.imports.models import Household
from apps.office.services.household_information import (
    build_household_information,
    render_household_information_pdf,
)
from apps.office.services.pdf_rendering import render_pdf_first_page_png
from apps.office.web_support import _default_household_browser_url, _resolve_next_url


@require_GET
def print_household_information(request: HttpRequest, household_id: str) -> HttpResponse:
    household = get_object_or_404(
        Household.objects.select_related("head_person", "batch__source"),
        household_uid=household_id, deleted_at__isnull=True,
    )
    output_format = request.GET.get("format") or "preview"
    if output_format not in {"preview", "pdf", "pdf-image", "html"}:
        return HttpResponseBadRequest("印刷形式が不正です。")
    context = build_household_information(household)
    context["title"] = "戸主情報印刷"
    context["next_url"] = _resolve_next_url(
        request, _default_household_browser_url(household_id, focus="detail"),
    )
    for name, value in (("pdf_url", "pdf"), ("pdf_image_url", "pdf-image"),
                        ("pdf_preview_url", "preview"), ("browser_print_url", "html")):
        context[name] = f"{request.path}?{urlencode({'format': value, 'next': context['next_url']})}"
    if output_format in {"pdf", "pdf-image"}:
        data = render_household_information_pdf(context)
        if output_format == "pdf-image":
            response = HttpResponse(render_pdf_first_page_png(data), content_type="image/png")
        else:
            response = HttpResponse(data, content_type="application/pdf")
            response["Content-Disposition"] = 'inline; filename="household-information.pdf"'
    else:
        template = "office/household_information_print.html" if output_format == "html" else "office/household_information_pdf_preview.html"
        response = render(request, template, context)
    response["Cache-Control"] = "private, no-store"
    return response
