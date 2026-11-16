from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.core.services import temple_identity as temple_identity_services
from apps.core.services import tenant_policy
from apps.imports import canonical_population
from apps.imports.models import ServiceSchedule
from apps.office import services
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.services.service_information_pdf import (
    render_service_information_pdf,
    render_service_information_pdf_preview,
)
from apps.office.services.service_schedule_printing import (
    _build_service_schedule_print_card,
    _household_future_memorial_rows,
    _service_schedule_print_group,
)
from apps.office.web_support import (
    SERVICE_LEDGER_CARD_VIEW_MODES,
    _default_service_ledger_url,
    _normalize_service_ledger_card_view,
    _normalized_service_ledger_request_url,
    _resolve_next_url,
    _service_ledger_card_view_url,
)


def service_ledger(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    card_view_mode = _normalize_service_ledger_card_view(request.GET.get("card_view"))
    context = services.build_service_ledger_context(
        query=query,
        candidate_page=request.GET.get("candidate_page", "1"),
    )
    context.pop("selected_source_id", None)
    clear_query = request.GET.copy()
    clear_query.pop("q", None)
    clear_query.pop("candidate_page", None)
    clear_query.pop("source_id", None)
    clear_query.pop("backend", None)
    clear_query["card_view"] = card_view_mode
    encoded_clear_query = clear_query.urlencode()
    context["card_view_mode"] = card_view_mode
    context["card_view_modes"] = [
        {
            **item,
            "selected": item["key"] == card_view_mode,
            "url": _service_ledger_card_view_url(request, card_view=item["key"]),
        }
        for item in SERVICE_LEDGER_CARD_VIEW_MODES
    ]
    context["clear_url"] = (
        f"{request.path}?{encoded_clear_query}" if encoded_clear_query else request.path
    )
    context["current_url"] = _normalized_service_ledger_request_url(request)
    candidate_page = context.get("candidate_pagination")
    if candidate_page is not None:
        page_query = request.GET.copy()
        for key in ("source_id", "backend"):
            page_query.pop(key, None)
        page_query["card_view"] = card_view_mode

        def candidate_page_url(number: int) -> str:
            page_query["candidate_page"] = str(number)
            return f"{request.path}?{page_query.urlencode()}#section-candidates"

        context["candidate_navigation"] = {
            "page": candidate_page,
            "previous_url": (
                candidate_page_url(candidate_page.previous_page_number())
                if candidate_page.has_previous() else ""
            ),
            "next_url": (
                candidate_page_url(candidate_page.next_page_number())
                if candidate_page.has_next() else ""
            ),
        }
    return render(request, "office/service_ledger.html", context)


def print_service_schedule(request: HttpRequest, household_id: str, event_id: str) -> HttpResponse:
    schedule_uid = event_id
    source_table = request.GET.get("source_table") or ""
    print_mode = (request.GET.get("print") or "").strip() == "1"
    active_source_id = services.operational_source_id()
    canonical_population.canonical_provenance_import_batch(source_id=active_source_id)
    schedules = ServiceSchedule.objects.select_related("household", "person", "person__deceased_profile").filter(
        household_uid=household_id,
        schedule_uid=schedule_uid,
        deleted_at__isnull=True,
    )
    if source_table:
        schedules = schedules.filter(source_table=source_table)
    schedule = get_object_or_404(schedules)
    next_url = _resolve_next_url(
        request,
        _default_service_ledger_url(),
    )
    sutra_cycle = temple_identity_services.service_schedule_sutra_cycle()
    participant_schedules = _service_schedule_print_group(schedule)
    participant_cards = []
    for item in participant_schedules:
        card = _build_service_schedule_print_card(item, sutra_cycle=sutra_cycle)
        card["is_current"] = item.pk == schedule.pk
        participant_cards.append(card)
    service_labels = []
    for item in participant_cards:
        label = item.get("service_label", "")
        if label and label not in service_labels:
            service_labels.append(label)
    participant_names = [item["person_name"] for item in participant_cards if item["person_name"]]
    participant_count = len(participant_cards)
    future_memorial_rows = _household_future_memorial_rows(
        schedule,
        participant_schedules,
        years_ahead=3,
    )
    print_query = request.GET.copy()
    print_query["print"] = "1"
    print_query["format"] = "html"
    preview_query = request.GET.copy()
    preview_query.pop("print", None)
    preview_query["format"] = "html"
    preview_query_string = preview_query.urlencode()
    context = {
        "schedule": schedule,
        "next_url": next_url,
        "print_mode": print_mode,
        "print_page_url": f"{request.path}?{print_query.urlencode()}",
        "print_preview_url": f"{request.path}?{preview_query_string}" if preview_query_string else request.path,
        "print_date": timezone.localdate(),
        "household_label": schedule.household_name_snapshot
        or (_household_display_head_name(schedule.household) if schedule.household_id else household_id),
        "scheduled_date_label": schedule.scheduled_date.isoformat() if schedule.scheduled_date else "",
        "scheduled_time_label": schedule.scheduled_time.strftime("%H:%M") if schedule.scheduled_time else "",
        "completed_on_label": schedule.completed_on.isoformat() if schedule.completed_on else "",
        "participant_count": participant_count,
        "participant_names": participant_names,
        "participant_cards": participant_cards,
        "future_memorial_rows": future_memorial_rows,
        "service_labels": service_labels,
        "document_title": f"{schedule.household_name_snapshot or (_household_display_head_name(schedule.household) if schedule.household_id else household_id)}の法要情報",
        "service_notes": (schedule.notes or "").strip(),
        "card_grid_class": "cols-3" if participant_count >= 3 else "cols-2",
    }
    context["deceased_labels"] = tenant_policy.deceased_field_labels()
    def format_url(value):
        query = request.GET.copy()
        query.pop("print", None)
        query["format"] = value
        return f"{request.path}?{query.urlencode()}"

    context["pdf_url"] = format_url("pdf")
    context["pdf_preview_url"] = format_url("preview")
    context["pdf_image_url"] = format_url("pdf-image")
    context["browser_print_url"] = format_url("html")
    output_format = request.GET.get("format") or ("html" if print_mode else "preview")
    if output_format == "pdf-image":
        response = HttpResponse(render_service_information_pdf_preview(context), content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        return response
    # Old direct-print links now return an ordinary PDF without a print action.
    if output_format in ("pdf", "pdf-print"):
        response = HttpResponse(
            render_service_information_pdf(context),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = 'inline; filename="service-information.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response
    if output_format != "html":
        return render(request, "office/service_information_pdf_preview.html", context)
    return render(request, "office/service_schedule_print.html", context)
