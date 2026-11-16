from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_POST

from . import console_views
from .legacy_household_views import (
    _create_new_household_current_person as _create_new_household_current_person,
)
from .legacy_household_views import (
    _create_new_household_memorial_person as _create_new_household_memorial_person,
)
from .legacy_household_views import (
    _legacy_create_household_current_person as _legacy_create_household_current_person,
)
from .legacy_household_views import (
    _legacy_create_household_memorial_person as _legacy_create_household_memorial_person,
)
from .legacy_household_views import (
    _legacy_edit_household as _legacy_edit_household,
)
from .legacy_household_views import (
    _legacy_edit_person as _legacy_edit_person,
)
from .legacy_household_views import (
    _legacy_household_browser as _legacy_household_browser,
)
from .legacy_household_views import (
    _legacy_household_head_transition as _legacy_household_head_transition,
)
from .legacy_household_views import (
    _legacy_move_household_head_to_current as _legacy_move_household_head_to_current,
)
from .legacy_household_views import (
    _legacy_move_household_head_to_memorial as _legacy_move_household_head_to_memorial,
)
from .legacy_household_views import (
    _legacy_person_memorial_transition as _legacy_person_memorial_transition,
)
from .legacy_household_views import (
    _legacy_toggle_person_memorial_notice_opt_out as _legacy_toggle_person_memorial_notice_opt_out,
)
from .legacy_household_views import (
    _legacy_update_household_delivery_assignment as _legacy_update_household_delivery_assignment,
)
from .legacy_household_views import (
    _legacy_update_person_gender_from_household_browser as _legacy_update_person_gender_from_household_browser,
)
from .legacy_household_views import (
    _register_person_memorial_transition as _register_person_memorial_transition,
)
from .legacy_household_views import (
    _sync_household_head_person_identity_from_form as _sync_household_head_person_identity_from_form,
)
from .legacy_household_views import (
    _sync_household_head_snapshot_from_person as _sync_household_head_snapshot_from_person,
)
from .legacy_memorial_views import (
    _build_household_service_link_candidates as _build_household_service_link_candidates,
)
from .legacy_memorial_views import (
    _build_service_schedule_print_card as _build_service_schedule_print_card,
)
from .legacy_memorial_views import (
    _legacy_create_service_schedule as _legacy_create_service_schedule,
)
from .legacy_memorial_views import (
    _legacy_edit_service_schedule as _legacy_edit_service_schedule,
)
from .legacy_memorial_views import (
    _legacy_memorial_notices as _legacy_memorial_notices,
)
from .legacy_memorial_views import (
    _legacy_memorial_sheet as _legacy_memorial_sheet,
)
from .legacy_memorial_views import (
    _legacy_service_ledger as _legacy_service_ledger,
)
from .legacy_memorial_views import (
    _service_payment_formset as _service_payment_formset,
)
from .legacy_memorial_views import (
    _sync_linked_service_schedule_members as _sync_linked_service_schedule_members,
)
from .legacy_memorial_views import (
    print_service_schedule as print_service_schedule,
)
from .legacy_quality_views import (
    _build_record_history_context as _build_record_history_context,
)
from .legacy_quality_views import (
    _build_time_machine_field_options as _build_time_machine_field_options,
)
from .legacy_quality_views import (
    _legacy_data_quality as _legacy_data_quality,
)
from .legacy_quality_views import (
    _legacy_data_science as _legacy_data_science,
)
from .legacy_quality_views import (
    _legacy_record_history as _legacy_record_history,
)
from .legacy_quality_views import (
    _legacy_special_searches as _legacy_special_searches,
)
from .legacy_quality_views import (
    _recent_record_history as _recent_record_history,
)
from .legacy_quality_views import (
    _time_machine_snapshot_value as _time_machine_snapshot_value,
)
from .legacy_settings_views import (
    _build_annual_membership_fee_context as _build_annual_membership_fee_context,
)
from .legacy_settings_views import (
    _create_household_from_hand_delivery_entry as _create_household_from_hand_delivery_entry,
)
from .legacy_settings_views import (
    _create_household_from_postal_entry as _create_household_from_postal_entry,
)
from .legacy_settings_views import (
    _ensure_postal_recipient_current_person as _ensure_postal_recipient_current_person,
)
from .legacy_settings_views import (
    _find_hand_delivery_review_entry as _find_hand_delivery_review_entry,
)
from .legacy_settings_views import (
    _find_postal_review_entry as _find_postal_review_entry,
)
from .legacy_settings_views import (
    _legacy_settings_home as _legacy_settings_home,
)
from .legacy_settings_views import (
    _legacy_user_management as _legacy_user_management,
)
from .legacy_settings_views import (
    _next_generated_household_id as _next_generated_household_id,
)
from .legacy_settings_views import (
    _next_generated_household_row_number as _next_generated_household_row_number,
)
from .legacy_settings_views import (
    _record_hand_delivery_review_resolution as _record_hand_delivery_review_resolution,
)
from .legacy_settings_views import (
    _record_postal_review_resolution as _record_postal_review_resolution,
)
from .legacy_settings_views import (
    _replace_household_head_from_hand_delivery_entry as _replace_household_head_from_hand_delivery_entry,
)
from .legacy_settings_views import (
    _replace_household_head_from_postal_entry as _replace_household_head_from_postal_entry,
)
from .legacy_settings_views import (
    _rollbackable_created_auxiliary_household as _rollbackable_created_auxiliary_household,
)
from .legacy_settings_views import (
    annual_membership_fees as annual_membership_fees,
)
from .legacy_settings_views import (
    assign_postal_override as assign_postal_override,
)
from .legacy_settings_views import (
    create_hand_delivery_review_household as create_hand_delivery_review_household,
)
from .legacy_settings_views import (
    create_postal_review_household as create_postal_review_household,
)
from .legacy_settings_views import (
    districts as districts,
)
from .legacy_settings_views import (
    hand_delivery_review as hand_delivery_review,
)
from .legacy_settings_views import (
    household_districts as household_districts,
)
from .legacy_settings_views import (
    import_hand_delivery_districts as import_hand_delivery_districts,
)
from .legacy_settings_views import (
    import_postal_assignments as import_postal_assignments,
)
from .legacy_settings_views import (
    postal_compare as postal_compare,
)
from .legacy_settings_views import (
    postal_review as postal_review,
)
from .legacy_settings_views import (
    replace_hand_delivery_household_head as replace_hand_delivery_household_head,
)
from .legacy_settings_views import (
    replace_postal_household_head as replace_postal_household_head,
)
from .legacy_settings_views import (
    rollback_created_hand_delivery_review_household as rollback_created_hand_delivery_review_household,
)
from .legacy_settings_views import (
    rollback_created_postal_review_household as rollback_created_postal_review_household,
)


def console(request: HttpRequest) -> HttpResponse:
    return console_views.console(request)


@require_POST
def run_action(request: HttpRequest, action: str) -> HttpResponse:
    return console_views.run_action(request, action)


@require_POST
def register_source(request: HttpRequest) -> HttpResponse:
    return console_views.register_source(request)


@require_POST
def set_default_source(request: HttpRequest) -> HttpResponse:
    return console_views.set_default_source(request)


_WRAPPER_FUNCTION_EXPORTS = (
    "console",
    "run_action",
    "register_source",
    "set_default_source",
)

_PUBLIC_COMPATIBILITY_VIEW_EXPORTS = (
    "annual_membership_fees",
    "assign_postal_override",
    "create_hand_delivery_review_household",
    "create_postal_review_household",
    "districts",
    "hand_delivery_review",
    "household_districts",
    "import_hand_delivery_districts",
    "import_postal_assignments",
    "postal_compare",
    "postal_review",
    "print_service_schedule",
    "replace_hand_delivery_household_head",
    "replace_postal_household_head",
    "rollback_created_hand_delivery_review_household",
    "rollback_created_postal_review_household",
)

_LEGACY_VIEW_ALIAS_EXPORTS = (
    "_legacy_create_household_current_person",
    "_legacy_create_household_memorial_person",
    "_legacy_create_service_schedule",
    "_legacy_data_quality",
    "_legacy_data_science",
    "_legacy_edit_household",
    "_legacy_edit_person",
    "_legacy_edit_service_schedule",
    "_legacy_household_browser",
    "_legacy_household_head_transition",
    "_legacy_memorial_notices",
    "_legacy_memorial_sheet",
    "_legacy_move_household_head_to_current",
    "_legacy_move_household_head_to_memorial",
    "_legacy_person_memorial_transition",
    "_legacy_record_history",
    "_legacy_service_ledger",
    "_legacy_settings_home",
    "_legacy_special_searches",
    "_legacy_toggle_person_memorial_notice_opt_out",
    "_legacy_update_household_delivery_assignment",
    "_legacy_update_person_gender_from_household_browser",
    "_legacy_user_management",
)

_PRIVATE_COMPATIBILITY_ALIAS_EXPORTS = (
    "_build_annual_membership_fee_context",
    "_build_household_service_link_candidates",
    "_build_record_history_context",
    "_build_service_schedule_print_card",
    "_build_time_machine_field_options",
    "_create_household_from_hand_delivery_entry",
    "_create_household_from_postal_entry",
    "_create_new_household_current_person",
    "_create_new_household_memorial_person",
    "_ensure_postal_recipient_current_person",
    "_find_hand_delivery_review_entry",
    "_find_postal_review_entry",
    "_next_generated_household_id",
    "_next_generated_household_row_number",
    "_recent_record_history",
    "_record_hand_delivery_review_resolution",
    "_record_postal_review_resolution",
    "_register_person_memorial_transition",
    "_replace_household_head_from_hand_delivery_entry",
    "_replace_household_head_from_postal_entry",
    "_rollbackable_created_auxiliary_household",
    "_service_payment_formset",
    "_sync_household_head_person_identity_from_form",
    "_sync_household_head_snapshot_from_person",
    "_sync_linked_service_schedule_members",
    "_time_machine_snapshot_value",
)


# Unsupported compatibility attrs remain as module attributes for now, but the
# supported surface is the explicit keep-set below.
__all__ = [
    *_WRAPPER_FUNCTION_EXPORTS,
    *_PUBLIC_COMPATIBILITY_VIEW_EXPORTS,
    *_LEGACY_VIEW_ALIAS_EXPORTS,
    *_PRIVATE_COMPATIBILITY_ALIAS_EXPORTS,
]
