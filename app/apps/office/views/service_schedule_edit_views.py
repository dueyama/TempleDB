from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render

from apps.imports.models import ServiceSchedule
from apps.office.services.record_history_feed import _edit_url as _edit_url
from apps.office.services.record_history_snapshot import (
    _serialize_service_schedule_record as _serialize_service_schedule_record,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options as _build_time_machine_field_options,
)
from apps.office.services.service_schedule_core import (
    _service_payment_formset as _service_payment_formset,
)
from apps.office.services.service_schedule_links import (
    _build_household_service_link_candidates as _build_household_service_link_candidates,
)

from .service_schedule_edit_actions import _handle_service_schedule_special_post_actions
from .service_schedule_edit_form_flow import (
    _build_service_schedule_edit_form_bundle,
    _build_service_schedule_edit_render_context,
    _save_service_schedule_edit_form,
)
from .service_schedule_edit_state import _service_schedule_edit_state


def edit_service_schedule(request: HttpRequest, household_id: str, event_id: str) -> HttpResponse:
    temple_event = ServiceSchedule.objects.filter(household_uid=household_id, schedule_uid=event_id, event_scope=ServiceSchedule.EventScope.TEMPLE).first()
    if temple_event is not None:
        if request.method == "POST":
            return HttpResponseBadRequest("寺の予定の編集画面から保存してください。")
        return redirect("office:edit_temple_event", event_id=temple_event.pk)
    state = _service_schedule_edit_state(
        request,
        household_id=household_id,
        event_id=event_id,
    )
    special_response = _handle_service_schedule_special_post_actions(request, state)
    if special_response is not None:
        return special_response
    form_bundle = _build_service_schedule_edit_form_bundle(request, state)
    save_response = _save_service_schedule_edit_form(request, state, form_bundle)
    if save_response is not None:
        return save_response
    return render(
        request,
        "office/record_edit.html",
        _build_service_schedule_edit_render_context(
            request,
            state,
            form=form_bundle["form"],
            payment_formset=form_bundle["payment_formset"],
        ),
    )
