from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.core.services import tenant_policy
from apps.office.services.memorial_distribution import build_memorial_distribution_context
from apps.office.views.common import _ensure_source_record
from apps.office.web_support import _parse_boolean_flag


def _options(request: HttpRequest) -> dict:
    value = request.GET.get("year", str(date.today().year + 1))
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("対象年は1900〜2100年で指定してください。") from exc
    if not 1900 <= year <= 2100:
        raise ValueError("対象年は1900〜2100年で指定してください。")
    return {
        "target_year": year,
        "include_reference_year": _parse_boolean_flag(
            request.GET.get("include_reference_year"), default=True,
        ),
    }


def _context(options: dict) -> dict:
    source = _ensure_source_record(None)
    context = build_memorial_distribution_context(source.source_id, **options)
    context["current_page"] = "memorial_distribution"
    context["marker_labels"] = tenant_policy.marker_labels()
    context["selection_query"] = urlencode({
        "year": options["target_year"],
        "include_reference_year": "1" if options["include_reference_year"] else "0",
    })
    return context


@require_GET
def memorial_distribution(request: HttpRequest) -> HttpResponse:
    try:
        context = _context(_options(request))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return render(request, "office/memorial_distribution.html", context)


@require_GET
def memorial_distribution_print(request: HttpRequest) -> HttpResponse:
    group = request.GET.get("group", "district")
    district_titles = {
        "district": "地区別まとめ印刷",
        "district_with_notices": "年回案内がある地区だけ印刷",
        "district_without_notices": "年回案内がない地区だけ印刷",
    }
    if group not in {*district_titles, "postal", "unknown"}:
        return HttpResponseBadRequest("印刷区分を選び直してください。")
    try:
        context = _context(_options(request))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    district_id = request.GET.get("district", "")
    print_items = []
    if group in district_titles:
        groups = context["district_groups"]
        if group == "district_with_notices":
            groups = [row for row in groups if row["household_count"] > 0]
        elif group == "district_without_notices":
            groups = [row for row in groups if row["household_count"] == 0]
        if district_id:
            groups = [row for row in groups if str(row["district_id"]) == district_id]
            if not groups:
                return HttpResponseBadRequest("印刷する地区を選び直してください。")
        for row in groups:
            print_items.extend(row["print_items"])
        title = district_titles[group]
    else:
        if district_id:
            return HttpResponseBadRequest("地区指定は地区別まとめ印刷で使用してください。")
        print_items = [
            {"kind": "notice", "document": document, "marker": document["distribution_marker"]}
            for document in context[f"{group}_documents"]
        ]
        title = "郵送分の年回表" if group == "postal" else "不明分の年回表"
    context.update({
        "print_items": print_items,
        "print_group": group,
        "print_title": title,
        "return_url": f"{reverse('office:memorial_distribution')}?{context['selection_query']}",
    })
    return render(request, "office/memorial_distribution_print.html", context)
