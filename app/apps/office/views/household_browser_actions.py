from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_POST

from apps.office.services.household_editing_core import _person_for_edit as _person_for_edit
from apps.office.services.record_history_mutations import (
    _create_record_edit_log as _create_record_edit_log,
)
from apps.office.services.record_history_mutations import (
    perform_record_delete_action as perform_record_delete_action,
)

from . import household_browser_delivery_action_views, household_browser_person_action_views


@require_POST
def update_household_delivery_assignment(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    return household_browser_delivery_action_views.update_household_delivery_assignment(
        request,
        household_id,
    )


@require_POST
def update_person_gender_from_household_browser(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    return household_browser_person_action_views.update_person_gender_from_household_browser(
        request,
        household_id,
        person_id,
    )


def delete_person_from_same_name_candidates(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    return household_browser_person_action_views.delete_person_from_same_name_candidates(
        request,
        household_id,
        person_id,
    )


@require_POST
def bulk_update_people_gender(request: HttpRequest) -> HttpResponse:
    return household_browser_person_action_views.bulk_update_people_gender(request)


@require_POST
def clear_household_address_line2(
    request: HttpRequest,
    household_id: str,
) -> HttpResponse:
    return household_browser_delivery_action_views.clear_household_address_line2(
        request,
        household_id,
    )


@require_POST
def toggle_person_memorial_notice_opt_out(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    return household_browser_person_action_views.toggle_person_memorial_notice_opt_out(
        request,
        household_id,
        person_id,
    )
