from __future__ import annotations

from apps.office.services.household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _clean_household_head_value,
    _household_display_head_name,
    _household_display_head_name_kana,
    _matching_household_head_people,
    _next_generated_person_id,
    _normalize_generated_head_person_id,
    _normalize_household_head_name,
    _person_for_edit,
    _resolved_household_head_person,
)
from apps.office.services.household_head_editing import (
    _apply_household_head_transition_successor,
    _create_household_head_person,
    _create_manual_successor_head_person,
    _household_head_successor_choices,
    _next_household_head_person_id,
    _prepare_household_head_person_move,
    _sync_household_head_person_identity_from_form,
    _sync_household_head_snapshot_from_person,
)
from apps.office.services.household_person_lifecycle import (
    _create_new_household_current_person,
    _create_new_household_memorial_person,
    _household_head_memorial_transition_initial,
    _person_memorial_transition_initial,
    _register_person_memorial_transition,
)
from apps.office.services.household_profile_editing import (
    _apply_household_delivery_profile_from_form,
    _apply_household_head_gender_from_form,
    _attach_household_browser_edit_context,
    _attach_person_gender_state,
    _household_head_person_candidates,
    _household_profile_has_state,
    _household_profile_initial_values,
    _member_gender_value,
    _resolved_household_general_notice_opt_out,
    _resolved_household_head_gender,
    _resolved_household_memorial_notice_opt_out,
)
from apps.office.views.household_browser_actions import (
    toggle_person_memorial_notice_opt_out as _legacy_toggle_person_memorial_notice_opt_out,
)
from apps.office.views.household_browser_actions import (
    update_household_delivery_assignment as _legacy_update_household_delivery_assignment,
)
from apps.office.views.household_browser_actions import (
    update_person_gender_from_household_browser as _legacy_update_person_gender_from_household_browser,
)
from apps.office.views.household_browser_views import (
    household_browser as _legacy_household_browser,
)
from apps.office.views.household_edit_views import (
    edit_household as _legacy_edit_household,
)
from apps.office.views.household_head_transition_views import (
    household_head_transition as _legacy_household_head_transition,
)
from apps.office.views.household_head_transition_views import (
    move_household_head_to_current as _legacy_move_household_head_to_current,
)
from apps.office.views.household_head_transition_views import (
    move_household_head_to_memorial as _legacy_move_household_head_to_memorial,
)
from apps.office.views.household_person_views import (
    create_household_current_person as _legacy_create_household_current_person,
)
from apps.office.views.household_person_views import (
    create_household_memorial_person as _legacy_create_household_memorial_person,
)
from apps.office.views.household_person_views import (
    edit_person as _legacy_edit_person,
)
from apps.office.views.household_person_views import (
    person_memorial_transition as _legacy_person_memorial_transition,
)
from apps.office.web_actions import _move_household_head_person

__all__ = [
    "_apply_household_contact_defaults_to_person",
    "_apply_household_delivery_profile_from_form",
    "_apply_household_head_gender_from_form",
    "_apply_household_head_transition_successor",
    "_attach_household_browser_edit_context",
    "_attach_person_gender_state",
    "_clean_household_head_value",
    "_create_household_head_person",
    "_create_manual_successor_head_person",
    "_create_new_household_current_person",
    "_create_new_household_memorial_person",
    "_household_display_head_name",
    "_household_display_head_name_kana",
    "_household_head_memorial_transition_initial",
    "_household_head_person_candidates",
    "_household_head_successor_choices",
    "_household_profile_has_state",
    "_household_profile_initial_values",
    "_legacy_create_household_current_person",
    "_legacy_create_household_memorial_person",
    "_legacy_edit_household",
    "_legacy_edit_person",
    "_legacy_household_browser",
    "_legacy_household_head_transition",
    "_legacy_move_household_head_to_current",
    "_legacy_move_household_head_to_memorial",
    "_legacy_person_memorial_transition",
    "_legacy_toggle_person_memorial_notice_opt_out",
    "_legacy_update_household_delivery_assignment",
    "_legacy_update_person_gender_from_household_browser",
    "_matching_household_head_people",
    "_member_gender_value",
    "_move_household_head_person",
    "_next_generated_person_id",
    "_next_household_head_person_id",
    "_normalize_generated_head_person_id",
    "_normalize_household_head_name",
    "_person_for_edit",
    "_person_memorial_transition_initial",
    "_prepare_household_head_person_move",
    "_register_person_memorial_transition",
    "_resolved_household_general_notice_opt_out",
    "_resolved_household_head_gender",
    "_resolved_household_head_person",
    "_resolved_household_memorial_notice_opt_out",
    "_sync_household_head_person_identity_from_form",
    "_sync_household_head_snapshot_from_person",
]
