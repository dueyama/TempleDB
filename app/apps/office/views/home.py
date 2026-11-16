from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.services.recovery_health_display import get_recovery_health_warning
from apps.office.forms_home import HomeServiceCompletionForm
from apps.office.services.home import build_home_context
from apps.office.services.home_service_completion import complete_home_service
from apps.office.web_support import _request_actor_label

from .common import _canonical_ledger_context
from .service_schedule_view_shared import (
    _flash_google_calendar_sync_messages,
    _queue_google_calendar_sync,
)


def home(request: HttpRequest) -> HttpResponse:
    return _home_response(request)


def _home_response(request, *, bound_form=None, schedule_id=None, status=200):
    context = build_home_context()
    context["current_url"] = request.get_full_path() if request.method == "GET" else reverse("office:home")
    context["recovery_health_warning"] = get_recovery_health_warning()
    for key in ("today_events", "next_events", "overdue_events"):
        for entry in context["home_schedule"].get(key, []):
            quick = entry.get("quick_completion")
            if quick:
                quick["form"] = bound_form if quick["schedule_id"] == schedule_id else HomeServiceCompletionForm(
                    initial={"state": quick["state"], "completed_on": quick["completed_on"], "payment_method": "cash"},
                    auto_id=f"home-complete-{quick['schedule_id']}-%s",
                )
    context["home_completion_errors"] = (
        [error for errors in bound_form.errors.values() for error in errors]
        if bound_form is not None else []
    )
    return render(request, "office/home.html", context, status=status)


@require_POST
def complete_service_from_home(request: HttpRequest, schedule_id: int) -> HttpResponse:
    ledger = _canonical_ledger_context()
    form = HomeServiceCompletionForm(request.POST, auto_id=f"home-complete-{schedule_id}-%s")
    if not form.is_valid():
        return _home_response(request, bound_form=form, schedule_id=schedule_id, status=422)
    sync_results = []
    try:
        with transaction.atomic():
            keys = complete_home_service(
                schedule_id=schedule_id, **form.cleaned_data,
                source_id=ledger.source_id, editor_label=_request_actor_label(request),
            )
            _queue_google_calendar_sync(keys, results_buffer=sync_results)
    except ValidationError as exc:
        form.add_error(None, exc)
        return _home_response(request, bound_form=form, schedule_id=schedule_id, status=409)
    messages.success(request, "お布施を記録し、法要を完了しました。" if form.cleaned_data.get("amount") is not None else "法要を完了しました。")
    _flash_google_calendar_sync_messages(request, sync_results)
    return redirect("office:home")
