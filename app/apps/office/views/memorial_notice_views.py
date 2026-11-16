from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.imports.models import MemorialNoticeTemplate
from apps.office import services
from apps.office.services.memorial_notice_pdf import render_memorial_notice_pdf
from apps.office.views.common import _ensure_source_record
from apps.office.web_support import (
    _normalized_request_url,
    _parse_boolean_flag,
    _parse_optional_font_size,
    _parse_optional_year,
    _resolve_next_url,
)


def memorial_notices(request: HttpRequest) -> HttpResponse:
    data = request.POST if request.method == "POST" else request.GET
    source_id = None
    wants_pdf = (request.GET.get("format") or "").strip().lower() == "pdf"
    year = _parse_optional_year(data.get("year"))
    include_reference_year = _parse_boolean_flag(data.get("include_reference_year"), default=True)
    intro_text = data.get("intro_text") if "intro_text" in data else None
    outro_text = data.get("outro_text") if "outro_text" in data else None
    signature_text = data.get("signature_text") if "signature_text" in data else None
    recipient_font_size = _parse_optional_font_size(data.get("recipient_font_size"))
    body_font_size = _parse_optional_font_size(data.get("body_font_size"))
    signature_font_size = _parse_optional_font_size(data.get("signature_font_size"))
    table_font_size = _parse_optional_font_size(data.get("table_font_size"))
    if request.method == "POST" and request.POST.get("action") == "save_template":
        resolved_year = (
            year if isinstance(year, int) and 1900 <= year <= 2100 else date.today().year + 1
        )
        source_record = _ensure_source_record(source_id)
        MemorialNoticeTemplate.objects.update_or_create(
            source=source_record,
            target_year=resolved_year,
            defaults={
                "intro_text": intro_text or "",
                "outro_text": outro_text or "",
                "signature_text": signature_text or "",
                "recipient_font_size": recipient_font_size,
                "body_font_size": body_font_size,
                "signature_font_size": signature_font_size,
                "table_font_size": table_font_size,
            },
        )
        messages.success(request, f"{resolved_year}年の翌年回忌案内文面を保存しました。")
        query = urlencode(
            {
                "year": resolved_year,
                "include_reference_year": "1" if include_reference_year else "0",
            }
        )
        return redirect(_resolve_next_url(request, f"{reverse('office:memorial_notices')}?{query}"))
    context = services.build_memorial_notice_context(
        source_id=None,
        year=year,
        include_reference_year=include_reference_year,
        intro_text=intro_text,
        outro_text=outro_text,
        signature_text=signature_text,
        recipient_font_size=recipient_font_size,
        body_font_size=body_font_size,
        signature_font_size=signature_font_size,
        table_font_size=table_font_size,
        data_backend="db",
    )
    context["current_url"] = _normalized_request_url(request)
    if wants_pdf and context.get("available"):
        pdf_bytes = render_memorial_notice_pdf(context=context)
        target_year = context.get("target_year") or "memorial"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="memorial-notices-{target_year}.pdf"'
        )
        return response
    return render(request, "office/memorial_notices.html", context)
