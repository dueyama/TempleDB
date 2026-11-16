from __future__ import annotations

from apps.office.services.record_history_feed import (
    _build_record_history_context as _build_record_history_context,
)
from apps.office.services.record_history_feed import (
    _edit_url as _edit_url,
)
from apps.office.services.record_history_feed import (
    _history_field_changes as _history_field_changes,
)
from apps.office.services.record_history_feed import (
    _record_current_state_label as _record_current_state_label,
)
from apps.office.services.record_history_feed import (
    _record_field_change_rows as _record_field_change_rows,
)
from apps.office.services.record_history_feed import (
    _record_history_edit_url as _record_history_edit_url,
)
from apps.office.services.record_history_feed import (
    _record_history_entry as _record_history_entry,
)
from apps.office.services.record_history_feed import (
    _record_log_action as _record_log_action,
)
from apps.office.services.record_history_feed import (
    _resolve_current_record_for_log as _resolve_current_record_for_log,
)
from apps.office.services.record_history_feed import (
    _source_operation_history_entries as _source_operation_history_entries,
)
from apps.office.services.record_history_mutations import (
    _create_record_edit_log as _create_record_edit_log,
)
from apps.office.services.record_history_snapshot import (
    _changed_snapshot_fields as _changed_snapshot_fields,
)
from apps.office.services.record_history_snapshot import (
    _deleted_meta as _deleted_meta,
)
from apps.office.services.record_history_snapshot import (
    _format_history_value as _format_history_value,
)
from apps.office.services.record_history_snapshot import (
    _infer_record_edit_action_kind as _infer_record_edit_action_kind,
)
from apps.office.services.record_history_snapshot import (
    _normalize_snapshot_value as _normalize_snapshot_value,
)
from apps.office.services.record_history_snapshot import (
    _record_label as _record_label,
)
from apps.office.services.record_history_snapshot import (
    _serialize_household_record as _serialize_household_record,
)
from apps.office.services.record_history_snapshot import (
    _serialize_person_record as _serialize_person_record,
)
from apps.office.services.record_history_snapshot import (
    _serialize_service_schedule_record as _serialize_service_schedule_record,
)
from apps.office.services.record_history_snapshot import (
    _snapshot_value as _snapshot_value,
)
from apps.office.services.record_history_snapshot import (
    _write_record_field_changes as _write_record_field_changes,
)
from apps.office.services.record_history_time_machine import (
    _build_time_machine_field_options as _build_time_machine_field_options,
)
from apps.office.services.record_history_time_machine import (
    _recent_record_history as _recent_record_history,
)
from apps.office.services.record_history_time_machine import (
    _time_machine_display_value as _time_machine_display_value,
)
from apps.office.services.record_history_time_machine import (
    _time_machine_field_kind as _time_machine_field_kind,
)
from apps.office.services.record_history_time_machine import (
    _time_machine_normalize_field_value as _time_machine_normalize_field_value,
)
from apps.office.services.record_history_time_machine import (
    _time_machine_snapshot_value as _time_machine_snapshot_value,
)

# These renamed exports preserve the historic apps.imports import paths.
from apps.office.views.quality import (
    data_quality as _legacy_data_quality,  # noqa: F401
)
from apps.office.views.quality import (
    data_science as _legacy_data_science,  # noqa: F401
)
from apps.office.views.quality import (
    record_history as _legacy_record_history,  # noqa: F401
)
from apps.office.views.quality import (
    special_searches as _legacy_special_searches,  # noqa: F401
)
from apps.office.web_actions import (
    _add_record_action_message as _add_record_action_message,
)
from apps.office.web_actions import (
    _handle_record_delete_action as _handle_record_delete_action,
)
