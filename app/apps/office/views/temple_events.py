from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.imports.models import OfferingPayment, RecordEditLog, ServiceSchedule
from apps.office.forms_temple_events import TempleEventForm, TempleEventPaymentFormSet
from apps.office.services.temple_events import (
    PAYMENT_FIELDS,
    save_temple_event,
    temple_event_households,
    temple_event_list,
)
from apps.office.web_support import _request_actor_label, _resolve_next_url

from .common import _canonical_ledger_context
from .service_schedule_view_shared import _flash_google_calendar_sync_messages


@require_http_methods(["GET"])
def temple_events(request):
    _canonical_ledger_context()
    try:
        year = int(request.GET.get("year", timezone.localdate().year))
        if not 1 <= year <= 9999:
            raise ValueError
    except (TypeError, ValueError):
        year = timezone.localdate().year
    query = request.GET.get("q", "").strip()[:255]
    events = temple_event_list(year=year, query=query)
    # Receipts belong to events here; 会計 instead groups by receipt date.
    total = OfferingPayment.objects.filter(service_schedule__in=events.values("pk")).aggregate(
        total=Sum("amount", default=0)
    )["total"]
    return render(
        request,
        "office/temple_events.html",
        {
            "page": Paginator(events, 50).get_page(request.GET.get("page")),
            "year": year,
            "query": query,
            "total": total,
        },
    )


@require_http_methods(["GET", "POST"])
def edit_temple_event(request, event_id=None):
    context = _canonical_ledger_context()
    next_url = _resolve_next_url(request, reverse("office:temple_events"))
    event = (
        get_object_or_404(
            ServiceSchedule,
            pk=event_id,
            event_scope=ServiceSchedule.EventScope.TEMPLE,
            deleted_at__isnull=True,
        )
        if event_id is not None
        else ServiceSchedule(
            event_scope=ServiceSchedule.EventScope.TEMPLE,
            category=ServiceSchedule.Category.OTHER,
            status=ServiceSchedule.Status.SCHEDULED,
            scheduled_date=timezone.localdate(),
        )
    )
    households = temple_event_households(context)
    data = request.POST.copy() if request.method == "POST" else None
    if data is not None and data.get("save_action") == "complete":
        data["status"] = ServiceSchedule.Status.COMPLETED
    form = TempleEventForm(data, instance=event, households=households)
    formset = TempleEventPaymentFormSet(
        data, instance=event, prefix="payments", form_kwargs={"households": households}
    )
    for payment_form in formset.extra_forms:
        payment_form.fields["received_on"].initial = event.scheduled_date or timezone.localdate()
    if request.method == "POST":
        event_valid, payments_valid = form.is_valid(), formset.is_valid()
        if event_valid and payments_valid:
            rows, delete_ids = [], []
            for payment_form in formset.forms:
                cleaned = payment_form.cleaned_data
                if not cleaned or (not payment_form.instance.pk and not payment_form.has_changed()):
                    continue
                payment_id = cleaned["id"].pk if cleaned.get("id") is not None else None
                if cleaned.get("DELETE"):
                    if payment_id is not None:
                        delete_ids.append(payment_id)
                    continue
                row = {key: cleaned.get(key) for key in PAYMENT_FIELDS}
                row["id"] = payment_id
                rows.append(row)
            try:
                outcome = save_temple_event(
                    event_id=event_id,
                    values=form.cleaned_data,
                    payments=rows,
                    deleted_payment_ids=delete_ids,
                    expected_version=form.cleaned_data.get("version", ""),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", ""),
                )
            except ValidationError as exc:
                form.add_error(None, " / ".join(exc.messages))
            else:
                messages.success(request, "寺の予定と入金を保存しました。")
                _flash_google_calendar_sync_messages(request, outcome.sync_results)
                edit_url = reverse(
                    "office:edit_temple_event", kwargs={"event_id": outcome.event.pk}
                )
                return redirect(f"{edit_url}?{urlencode({'next': next_url})}")
    receipts = (
        OfferingPayment.objects.filter(service_schedule_id=event_id).select_related("household")
        if event_id
        else OfferingPayment.objects.none()
    )
    history = (
        RecordEditLog.objects.filter(
            record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE, record_id=event_id
        ).order_by("-created_at")[:10]
        if event_id
        else []
    )
    return render(
        request,
        "office/temple_event_edit.html",
        {
            "event": event,
            "form": form,
            "payment_formset": formset,
            "receipts": receipts,
            "total": receipts.aggregate(total=Sum("amount", default=0))["total"],
            "history": history,
            "next_url": next_url,
        },
    )
