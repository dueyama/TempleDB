from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from apps.imports.models import Household, Person, RecordEditLog, ServiceSchedule

from .services import service_schedule_editing
from .services.household_head_editing import move_household_head_person
from .services.record_history_mutations import (
    perform_record_delete_action,
    record_action_message_text,
)
from .web_support import _request_actor_label, _resolve_household_edit_context


def _handle_record_delete_action(
    *,
    request: HttpRequest,
    action: str,
    record_type: str,
    record: Household | Person | ServiceSchedule,
    serializer,
    refresh,
    redirect_url: str,
    deleted_message: str,
    restored_message: str,
) -> HttpResponse | None:
    outcome = perform_record_delete_action(
        action=action,
        record_type=record_type,
        record=record,
        serializer=serializer,
        refresh=refresh,
        editor_label=_request_actor_label(request),
        change_note=request.POST.get("change_note", ""),
        deleted_message=deleted_message,
        restored_message=restored_message,
    )
    if outcome is None:
        return None
    messages.success(request, outcome.user_message)
    return redirect(redirect_url)


def _add_record_action_message(
    request: HttpRequest,
    log_entry: RecordEditLog | None,
    message_text: str,
) -> None:
    messages.success(request, record_action_message_text(log_entry, message_text))


def _move_household_head_person(
    request: HttpRequest,
    household_id: str,
    target_category: str,
) -> HttpResponse:
    _active_source_id, household, next_url = _resolve_household_edit_context(
        request,
        None,
        household_id,
    )
    try:
        outcome = move_household_head_person(
            household=household,
            target_category=target_category,
            editor_label=_request_actor_label(request),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(next_url)
    messages.success(request, outcome.success_message)
    return redirect(next_url)


def _apply_service_schedule_prefill(schedule: ServiceSchedule, request: HttpRequest) -> None:
    service_schedule_editing.apply_service_schedule_prefill_values(
        schedule,
        category=request.GET.get("category") or "",
        service_label=request.GET.get("service_label") or "",
        target_date=request.GET.get("target_date") or "",
    )
