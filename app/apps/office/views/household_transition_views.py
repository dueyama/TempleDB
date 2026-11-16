from __future__ import annotations

from apps.office.services.household_editing_core import _apply_household_contact_defaults_to_person
from apps.office.services.household_head_editing import move_household_head_person
from apps.office.services.household_person_lifecycle import _register_person_memorial_transition
from apps.office.services.record_history_feed import _edit_url
from apps.office.services.record_history_mutations import perform_record_delete_action
from apps.office.services.record_history_snapshot import (
    _serialize_household_record,
    _serialize_person_record,
)
from apps.office.services.record_history_time_machine import _build_time_machine_field_options

from .household_edit_views import (
    edit_household,
    mark_household_extinct_view,
    replace_virtual_head,
)
from .household_head_transition_views import (
    _move_household_head,
    household_head_transition,
    move_household_head_to_current,
    move_household_head_to_memorial,
)
from .household_transition_shared import (
    _flash_record_action_message,
    _household_extinct_action_state,
)

__all__ = [
    "_apply_household_contact_defaults_to_person",
    "_build_time_machine_field_options",
    "_flash_record_action_message",
    "_household_extinct_action_state",
    "_move_household_head",
    "_register_person_memorial_transition",
    "_serialize_household_record",
    "_serialize_person_record",
    "_edit_url",
    "edit_household",
    "household_head_transition",
    "mark_household_extinct_view",
    "move_household_head_to_current",
    "move_household_head_to_memorial",
    "move_household_head_person",
    "perform_record_delete_action",
    "replace_virtual_head",
]
