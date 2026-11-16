from __future__ import annotations

from apps.imports.auxiliary_generated_ids import (
    _next_generated_household_id as _next_generated_household_id,
)
from apps.imports.auxiliary_generated_ids import (
    _next_generated_household_row_number as _next_generated_household_row_number,
)

from ..views.settings_district_admin import districts as districts
from ..web_actions import (
    _add_record_action_message as _add_record_action_message,
)
from ..web_actions import (
    _apply_service_schedule_prefill as _apply_service_schedule_prefill,
)
from ..web_actions import (
    _handle_record_delete_action as _handle_record_delete_action,
)
from ..web_actions import (
    _move_household_head_person as _move_household_head_person,
)
from .auxiliary_hand_delivery_households import (
    _create_household_from_hand_delivery_entry as _create_household_from_hand_delivery_entry,
)
from .auxiliary_hand_delivery_households import (
    _replace_household_head_from_hand_delivery_entry as _replace_household_head_from_hand_delivery_entry,
)
from .auxiliary_postal_households import (
    _create_household_from_postal_entry as _create_household_from_postal_entry,
)
from .auxiliary_postal_households import (
    _ensure_postal_recipient_current_person as _ensure_postal_recipient_current_person,
)
from .auxiliary_postal_households import (
    _replace_household_head_from_postal_entry as _replace_household_head_from_postal_entry,
)
from .district_ops import (
    _assign_district_officer_to_household as _assign_district_officer_to_household,
)
from .district_ops import (
    _assign_district_officer_to_person as _assign_district_officer_to_person,
)
from .district_ops import (
    _clear_district_officer_for_district as _clear_district_officer_for_district,
)
from .district_ops import (
    _district_officer_choices as _district_officer_choices,
)
from .district_ops import (
    _district_officer_person_for_district as _district_officer_person_for_district,
)
from .district_ops import (
    _ensure_district_from_hand_delivery_entry as _ensure_district_from_hand_delivery_entry,
)
from .district_ops import (
    _refresh_district_officer_name_snapshots as _refresh_district_officer_name_snapshots,
)
from .district_ops import (
    _refresh_district_officer_name_snapshots_for_person as _refresh_district_officer_name_snapshots_for_person,
)
from .district_ops import (
    _sync_person_district_officer_flag as _sync_person_district_officer_flag,
)
from .household_editing_core import (
    _apply_household_contact_defaults_to_person as _apply_household_contact_defaults_to_person,
)
from .household_editing_core import (
    _clean_household_head_value as _clean_household_head_value,
)
from .household_editing_core import (
    _household_display_head_name as _household_display_head_name,
)
from .household_editing_core import (
    _household_display_head_name_kana as _household_display_head_name_kana,
)
from .household_editing_core import (
    _matching_household_head_people as _matching_household_head_people,
)
from .household_editing_core import (
    _next_generated_person_id as _next_generated_person_id,
)
from .household_editing_core import (
    _normalize_generated_head_person_id as _normalize_generated_head_person_id,
)
from .household_editing_core import (
    _normalize_household_head_name as _normalize_household_head_name,
)
from .household_editing_core import (
    _person_for_edit as _person_for_edit,
)
from .household_editing_core import (
    _resolved_household_head_person as _resolved_household_head_person,
)
from .household_head_editing import (
    _apply_household_head_transition_successor as _apply_household_head_transition_successor,
)
from .household_head_editing import (
    _create_household_head_person as _create_household_head_person,
)
from .household_head_editing import (
    _create_manual_successor_head_person as _create_manual_successor_head_person,
)
from .household_head_editing import (
    _household_head_successor_choices as _household_head_successor_choices,
)
from .household_head_editing import (
    _is_virtual_household_head_person as _is_virtual_household_head_person,
)
from .household_head_editing import (
    _next_household_head_person_id as _next_household_head_person_id,
)
from .household_head_editing import (
    _prepare_household_head_person_move as _prepare_household_head_person_move,
)
from .household_head_editing import (
    _replace_virtual_household_head as _replace_virtual_household_head,
)
from .household_head_editing import (
    _sync_household_head_person_identity_from_form as _sync_household_head_person_identity_from_form,
)
from .household_head_editing import (
    _sync_household_head_snapshot_from_person as _sync_household_head_snapshot_from_person,
)
from .household_person_lifecycle import (
    _create_new_household_current_person as _create_new_household_current_person,
)
from .household_person_lifecycle import (
    _create_new_household_memorial_person as _create_new_household_memorial_person,
)
from .household_person_lifecycle import (
    _household_head_memorial_transition_initial as _household_head_memorial_transition_initial,
)
from .household_person_lifecycle import (
    _person_memorial_transition_initial as _person_memorial_transition_initial,
)
from .household_person_lifecycle import (
    _register_person_memorial_transition as _register_person_memorial_transition,
)
from .household_profile_editing import (
    _apply_household_delivery_profile_from_form as _apply_household_delivery_profile_from_form,
)
from .household_profile_editing import (
    _apply_household_head_gender_from_form as _apply_household_head_gender_from_form,
)
from .household_profile_editing import (
    _attach_household_browser_edit_context as _attach_household_browser_edit_context,
)
from .household_profile_editing import (
    _attach_person_gender_state as _attach_person_gender_state,
)
from .household_profile_editing import (
    _household_profile_has_state as _household_profile_has_state,
)
from .household_profile_editing import (
    _household_profile_initial_values as _household_profile_initial_values,
)
from .household_profile_editing import (
    _member_gender_value as _member_gender_value,
)
from .household_profile_editing import (
    _resolved_household_general_notice_opt_out as _resolved_household_general_notice_opt_out,
)
from .household_profile_editing import (
    _resolved_household_head_gender as _resolved_household_head_gender,
)
from .household_profile_editing import (
    _resolved_household_memorial_notice_opt_out as _resolved_household_memorial_notice_opt_out,
)
from .record_history_feed import (
    _build_record_history_context as _build_record_history_context,
)
from .record_history_feed import (
    _edit_url as _edit_url,
)
from .record_history_feed import (
    _history_field_changes as _history_field_changes,
)
from .record_history_feed import (
    _history_log_text_value as _history_log_text_value,
)
from .record_history_feed import (
    _record_current_state_label as _record_current_state_label,
)
from .record_history_feed import (
    _record_field_change_rows as _record_field_change_rows,
)
from .record_history_feed import (
    _record_history_change_digest as _record_history_change_digest,
)
from .record_history_feed import (
    _record_history_edit_url as _record_history_edit_url,
)
from .record_history_feed import (
    _record_history_entry as _record_history_entry,
)
from .record_history_feed import (
    _record_history_headline as _record_history_headline,
)
from .record_history_feed import (
    _record_history_subject as _record_history_subject,
)
from .record_history_feed import (
    _record_history_summary as _record_history_summary,
)
from .record_history_feed import (
    _record_history_target_facts as _record_history_target_facts,
)
from .record_history_feed import (
    _record_log_action as _record_log_action,
)
from .record_history_feed import (
    _resolve_current_record_for_log as _resolve_current_record_for_log,
)
from .record_history_feed import (
    _source_operation_headline as _source_operation_headline,
)
from .record_history_feed import (
    _source_operation_history_entries as _source_operation_history_entries,
)
from .record_history_feed import (
    _source_operation_payload_changes as _source_operation_payload_changes,
)
from .record_history_feed import (
    _source_operation_summary as _source_operation_summary,
)
from .record_history_mutations import _create_record_edit_log as _create_record_edit_log
from .record_history_snapshot import (
    _changed_snapshot_fields as _changed_snapshot_fields,
)
from .record_history_snapshot import (
    _deleted_meta as _deleted_meta,
)
from .record_history_snapshot import (
    _format_history_value as _format_history_value,
)
from .record_history_snapshot import (
    _infer_record_edit_action_kind as _infer_record_edit_action_kind,
)
from .record_history_snapshot import (
    _normalize_snapshot_value as _normalize_snapshot_value,
)
from .record_history_snapshot import (
    _record_label as _record_label,
)
from .record_history_snapshot import (
    _serialize_household_record as _serialize_household_record,
)
from .record_history_snapshot import (
    _serialize_person_record as _serialize_person_record,
)
from .record_history_snapshot import (
    _serialize_service_schedule_record as _serialize_service_schedule_record,
)
from .record_history_snapshot import (
    _snapshot_value as _snapshot_value,
)
from .record_history_snapshot import (
    _write_record_field_changes as _write_record_field_changes,
)
from .record_history_time_machine import (
    _build_time_machine_field_options as _build_time_machine_field_options,
)
from .record_history_time_machine import (
    _recent_record_history as _recent_record_history,
)
from .record_history_time_machine import (
    _time_machine_display_value as _time_machine_display_value,
)
from .record_history_time_machine import (
    _time_machine_field_kind as _time_machine_field_kind,
)
from .record_history_time_machine import (
    _time_machine_normalize_field_value as _time_machine_normalize_field_value,
)
from .record_history_time_machine import (
    _time_machine_snapshot_value as _time_machine_snapshot_value,
)
from .service_schedule_core import (
    _apply_manual_service_schedule_defaults as _apply_manual_service_schedule_defaults,
)
from .service_schedule_core import (
    _new_manual_service_schedule as _new_manual_service_schedule,
)
from .service_schedule_core import (
    _normalize_service_schedule_target_date as _normalize_service_schedule_target_date,
)
from .service_schedule_core import (
    _parse_prefill_date as _parse_prefill_date,
)
from .service_schedule_core import (
    _persist_manual_service_schedule_identity as _persist_manual_service_schedule_identity,
)
from .service_schedule_core import (
    _prepare_service_schedule_post_data as _prepare_service_schedule_post_data,
)
from .service_schedule_core import (
    _service_payment_formset as _service_payment_formset,
)
from .service_schedule_core import (
    _service_payment_summary as _service_payment_summary,
)
from .service_schedule_core import (
    _service_schedule_for_edit as _service_schedule_for_edit,
)
from .service_schedule_lifecycle import (
    _create_funeral_service_schedule_for_person as _create_funeral_service_schedule_for_person,
)
from .service_schedule_lifecycle import (
    _is_manual_service_schedule as _is_manual_service_schedule,
)
from .service_schedule_lifecycle import (
    _manual_service_schedule_has_blocking_relations as _manual_service_schedule_has_blocking_relations,
)
from .service_schedule_lifecycle import (
    _refresh_manual_service_schedule_household_snapshots as _refresh_manual_service_schedule_household_snapshots,
)
from .service_schedule_lifecycle import (
    _refresh_offering_payment_household_snapshots as _refresh_offering_payment_household_snapshots,
)
from .service_schedule_lifecycle import (
    _reset_service_schedule_planning_fields as _reset_service_schedule_planning_fields,
)
from .service_schedule_lifecycle import (
    _soft_delete_service_schedule as _soft_delete_service_schedule,
)
from .service_schedule_lifecycle import (
    _sync_linked_service_schedule_members as _sync_linked_service_schedule_members,
)
from .service_schedule_links import (
    LINKED_GROUP_SHARED_FIELDS as LINKED_GROUP_SHARED_FIELDS,
)
from .service_schedule_links import (
    SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS as SERVICE_LINK_DEFAULT_LOOKAHEAD_YEARS,
)
from .service_schedule_links import (
    SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS as SERVICE_LINK_EXTENDED_LOOKAHEAD_YEARS,
)
from .service_schedule_links import (
    SERVICE_LINK_LOOKBACK_DAYS as SERVICE_LINK_LOOKBACK_DAYS,
)
from .service_schedule_links import (
    _apply_linked_group_updates as _apply_linked_group_updates,
)
from .service_schedule_links import (
    _build_household_service_link_candidates as _build_household_service_link_candidates,
)
from .service_schedule_links import (
    _create_linked_service_schedules as _create_linked_service_schedules,
)
from .service_schedule_links import (
    _linked_service_schedule_choices as _linked_service_schedule_choices,
)
from .service_schedule_links import (
    _linked_service_schedule_members as _linked_service_schedule_members,
)
from .service_schedule_links import (
    _new_service_link_group_key as _new_service_link_group_key,
)
from .service_schedule_links import (
    _parse_service_link_candidate_token as _parse_service_link_candidate_token,
)
from .service_schedule_links import (
    _selected_service_link_candidates as _selected_service_link_candidates,
)
from .service_schedule_links import (
    _service_link_candidate_token as _service_link_candidate_token,
)
from .service_schedule_printing import (
    _build_service_schedule_print_card as _build_service_schedule_print_card,
)
from .service_schedule_printing import (
    _household_future_memorial_rows as _household_future_memorial_rows,
)
from .service_schedule_printing import (
    _person_related_visit_notes as _person_related_visit_notes,
)
from .service_schedule_printing import (
    _service_schedule_print_group as _service_schedule_print_group,
)
from .service_schedule_printing import (
    _service_schedule_print_url as _service_schedule_print_url,
)
