from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from apps.imports.forms import HouseholdEditForm
from apps.imports.models import Household
from apps.office.services.record_history_feed import _edit_url as _edit_url
from apps.office.services.record_history_mutations import (
    perform_record_delete_action as perform_record_delete_action,
)
from apps.office.services.record_history_snapshot import (
    _serialize_household_record as _serialize_household_record,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options as _build_time_machine_field_options,
)

from . import household_extinct_views, household_record_edit_views, household_virtual_head_views


def _build_deleted_household_context(
    *,
    household: Household,
    household_id: str,
    safe_return_url: str,
) -> dict[str, object]:
    return household_record_edit_views._build_deleted_household_context(
        household=household,
        household_id=household_id,
        safe_return_url=safe_return_url,
    )


def _build_household_edit_context(
    *,
    request: HttpRequest,
    household: Household,
    household_id: str,
    form: HouseholdEditForm,
    next_url: str,
    safe_return_url: str,
    time_machine_mode: bool,
    time_machine_field_options: dict[str, object],
    resolved_head_person,
    head_person_is_virtual: bool,
    extinct_action_state: dict[str, object],
) -> dict[str, object]:
    return household_record_edit_views._build_household_edit_context(
        request=request,
        household=household,
        household_id=household_id,
        form=form,
        next_url=next_url,
        safe_return_url=safe_return_url,
        time_machine_mode=time_machine_mode,
        time_machine_field_options=time_machine_field_options,
        resolved_head_person=resolved_head_person,
        head_person_is_virtual=head_person_is_virtual,
        extinct_action_state=extinct_action_state,
    )


def edit_household(request: HttpRequest, household_id: str) -> HttpResponse:
    return household_record_edit_views.edit_household(request, household_id)


def replace_virtual_head(request: HttpRequest, household_id: str) -> HttpResponse:
    return household_virtual_head_views.replace_virtual_head(request, household_id)


def mark_household_extinct_view(request: HttpRequest, household_id: str) -> HttpResponse:
    return household_extinct_views.mark_household_extinct_view(request, household_id)


__all__ = [
    "edit_household",
    "mark_household_extinct_view",
    "replace_virtual_head",
]
