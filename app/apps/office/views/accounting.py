from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.imports import canonical_population
from apps.imports.models import OfferingPayment
from apps.office.services.accounting import (
    build_accounting_context,
    build_multi_year_accounting_context,
)
from apps.office.views.common import _current_operational_source_id
from apps.office.web_support import _normalized_request_url, _parse_optional_year


def accounting(request: HttpRequest) -> HttpResponse:
    return _render_accounting_page(
        request,
        page_title="会計",
        page_heading_template="{year}年 会計",
        page_description=(
            "法要と法要外の入金を、納骨壇を除いて新しい月から順に月別に確認します。"
            " 納骨壇は納骨壇会計で確認します。"
            " 法要紐づきは法要編集へ、法要外は入金編集へ進めます。"
        ),
        subnav_current_page="accounting",
        payment_categories=tuple(
            value
            for value, _label in OfferingPayment.Category.choices
            if value != OfferingPayment.Category.NOKOTSUDAN
        ),
    )


def nokotsudan_accounting(request: HttpRequest) -> HttpResponse:
    active_source_id = _current_operational_source_id()
    batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if batch is None:
        raise Http404("canonical provenance batch not found")
    context = build_multi_year_accounting_context(
        source_id=active_source_id,
        batch=batch,
        current_url=request.path,
        payment_categories=(OfferingPayment.Category.NOKOTSUDAN,),
    )
    context.pop("selected_source_id", None)
    context.update(
        {
            "title": "納骨壇会計",
            "template_page_title": "納骨壇会計",
            "page_heading": "納骨壇会計",
            "page_description": "納骨壇の入金を全年度まとめて、年ごとに確認します。",
            "subnav_current_page": "nokotsudan_accounting",
        }
    )
    return render(request, "office/accounting.html", context)


def _render_accounting_page(
    request: HttpRequest,
    *,
    page_title: str,
    page_heading_template: str,
    page_description: str,
    subnav_current_page: str,
    payment_categories: tuple[str, ...],
) -> HttpResponse:
    active_source_id = _current_operational_source_id()
    batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if batch is None:
        raise Http404("canonical provenance batch not found")
    year = _parse_optional_year(request.GET.get("year")) or timezone.localdate().year
    context = build_accounting_context(
        source_id=active_source_id,
        batch=batch,
        year=year,
        current_url=_normalized_request_url(request),
        payment_categories=payment_categories,
    )
    context.pop("selected_source_id", None)
    context.update(
        {
            "title": page_title,
            "template_page_title": page_title,
            "page_heading": page_heading_template.format(year=year),
            "page_description": page_description,
            "subnav_current_page": subnav_current_page,
        }
    )
    return render(request, "office/accounting.html", context)
