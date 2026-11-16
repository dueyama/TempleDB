from __future__ import annotations

from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.services import temple_identity as temple_identity_services
from apps.imports.forms import GENDER_CHOICES
from apps.office import services
from apps.office.services.household_browser_event_history import (
    attach_household_browser_event_history_context as _attach_household_browser_event_history_context,
)
from apps.office.services.household_profile_editing import _attach_household_browser_edit_context
from apps.office.services.memorial_sheet_pdf import render_memorial_sheet_pdf
from apps.office.services.offering_payments import (
    attach_household_browser_payment_context as _attach_household_browser_payment_context,
)
from apps.office.web_support import (
    HOUSEHOLD_BROWSER_PREVIEW_MODES,
    _household_browser_prefers_list_first_view,
    _normalize_household_browser_focus_mode,
    _normalize_time_machine_mode,
    _resolved_household_browser_preview_mode,
)


def household_browser(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    include_memorial_search = _normalize_time_machine_mode(
        request.GET.get("include_memorial_search")
    )
    household_id = request.GET.get("household_id") or None
    candidate_from = request.GET.get("candidate_from") or None
    candidate_to = request.GET.get("candidate_to") or None
    kana_group = request.GET.get("kana_group") or None
    preview_mode = _resolved_household_browser_preview_mode(request)
    requested_focus_mode = request.GET.get("focus")
    focus_mode = _normalize_household_browser_focus_mode(requested_focus_mode)
    if preview_mode == "mobile" and household_id and requested_focus_mode is None:
        focus_mode = "detail"
    auto_select_first = not (
        household_id is None
        and _household_browser_prefers_list_first_view(request, preview_mode)
    )
    context = services.build_household_browser_context(
        query=query,
        household_id=household_id,
        candidate_from=candidate_from,
        candidate_to=candidate_to,
        kana_group=kana_group,
        include_memorial_search=include_memorial_search,
        auto_select_first=auto_select_first,
    )
    context.pop("selected_source_id", None)
    context.setdefault("data_backend", "db")
    context["preview_mode"] = preview_mode
    context["household_focus_mode"] = focus_mode
    context["mobile_detail_first"] = (
        preview_mode == "mobile"
        and focus_mode == "detail"
        and bool(context.get("detail"))
    )
    context["preview_modes"] = [
        {**item, "selected": item["key"] == preview_mode}
        for item in HOUSEHOLD_BROWSER_PREVIEW_MODES
    ]
    context["gender_choices"] = [
        {"value": value, "label": label} for value, label in GENDER_CHOICES
    ]
    current_url = request.get_full_path()
    _attach_household_browser_edit_context(context)
    _attach_household_browser_payment_context(
        context,
        batch=None,
        current_url=current_url,
        payment_category_filter=request.GET.get("payment_category", ""),
        payment_person_filter=request.GET.get("payment_person", ""),
    )
    _attach_household_browser_event_history_context(
        context,
        current_url=current_url,
    )
    context["current_url"] = current_url
    return render(request, "office/household_browser.html", context)


def memorial_sheet(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    wants_pdf = (request.GET.get("format") or "").strip().lower() == "pdf"
    wants_print_page = (request.GET.get("print") or "").strip() == "1"
    context = services.build_memorial_sheet_context(
        household_id=household_id,
        person_id=person_id,
    )
    context.pop("selected_source_id", None)
    context["temple_identity"] = temple_identity_services.current_temple_identity()
    if wants_pdf and context.get("available"):
        pdf_bytes = render_memorial_sheet_pdf(context=context)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="memorial-sheet-{household_id}-{person_id}.pdf"'
        )
        return response
    if wants_print_page and context.get("available"):
        return render(request, "office/memorial_sheet_print.html", context)
    return render(request, "office/memorial_sheet.html", context)


def household_memorial_list(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    start_date = request.GET.get("start") or None
    print_mode = (request.GET.get("print") or "").strip() == "1"
    context = services.build_household_memorial_list_context(
        household_id=household_id,
        start_date=start_date,
    )
    context.pop("selected_source_id", None)
    context["temple_identity"] = temple_identity_services.current_temple_identity()
    context["generated_on"] = timezone.localdate()
    context["print_mode"] = print_mode
    selected_start_date = str(context.get("selected_start_date") or start_date or "")
    list_query = {}
    if selected_start_date:
        list_query["start"] = selected_start_date
    print_query = {**list_query, "print": "1"}
    context["list_url"] = (
        f"{request.path}?{urlencode(list_query)}" if list_query else request.path
    )
    context["print_url"] = f"{request.path}?{urlencode(print_query)}"
    return render(request, "office/household_memorial_list.html", context)
