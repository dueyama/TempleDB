from __future__ import annotations

from apps.core.services import tenant_policy_memorial_notice as memorial_notice_policy

from . import memorial_shared
from .household_browser_dataset_runtime import (
    _load_household_browser_dataset as _load_household_browser_dataset,
)
from .household_browser_runtime_shared import (
    latest_export_snapshot as latest_export_snapshot,
)
from .household_browser_runtime_shared import (
    latest_succeeded_import_batch as latest_succeeded_import_batch,
)
from .household_browser_runtime_shared import (
    resolve_runtime_source_entry as resolve_runtime_source_entry,
)
from .household_browser_runtime_shared import (
    source_summary as source_summary,
)
from .memorial_notice_columns import (
    _build_memorial_notice_column,
    _memorial_notice_linked_summary,
    _memorial_notice_note,
    _memorial_notice_schedule_status,
)
from .memorial_notice_context_runtime import (
    _household_ids_with_memorial_notice_targets as _household_ids_with_memorial_notice_targets,
)
from .memorial_notice_context_runtime import (
    _legacy_build_memorial_notice_context,
    build_memorial_notice_context,
)
from .memorial_notice_layout import _memorial_notice_zokumyo_text as _memorial_notice_zokumyo_text
from .memorial_notice_template_runtime import (
    _effective_memorial_notice_defaults as _effective_memorial_notice_defaults,
)
from .memorial_notice_template_runtime import (
    _get_saved_memorial_notice_template,
    _memorial_notice_template_token_rows,
    _memorial_notice_template_values,
    _render_memorial_notice_template_text,
    _resolve_memorial_notice_style_value,
)

DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT
DEFAULT_MEMORIAL_NOTICE_STYLE = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_STYLE
LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES = memorial_shared.LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES
MEMORIAL_NOTICE_ROWS_PER_PAGE = memorial_notice_policy.MEMORIAL_NOTICE_ROWS_PER_PAGE
MEMORIAL_NOTICE_TEMPLATE_TOKENS = (
    {"token": "{{YEAR}}", "description": "西暦年"},
    {"token": "{{WAREKI_YEAR}}", "description": "和暦年"},
    {"token": "{{YEAR_LABEL}}", "description": "和暦と西暦"},
    {"token": "{{TEMPLE_SECT}}", "description": "寺院情報の宗派名"},
    {"token": "{{TEMPLE_NAME}}", "description": "寺院情報の寺院名"},
    {"token": "{{TEMPLE_POSTAL_CODE}}", "description": "寺院情報の郵便番号"},
    {"token": "{{TEMPLE_ADDRESS}}", "description": "寺院情報の住所"},
    {"token": "{{TEMPLE_PHONE}}", "description": "寺院情報の電話"},
    {"token": "{{TEMPLE_CHIEF_PRIEST_NAME}}", "description": "寺院情報の住職名"},
)
DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE


__all__ = [
    "DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE",
    "MEMORIAL_NOTICE_TEMPLATE_TOKENS",
    "_build_memorial_notice_column",
    "_get_saved_memorial_notice_template",
    "_legacy_build_memorial_notice_context",
    "_memorial_notice_linked_summary",
    "_memorial_notice_note",
    "_memorial_notice_schedule_status",
    "_memorial_notice_template_token_rows",
    "_memorial_notice_template_values",
    "_render_memorial_notice_template_text",
    "_resolve_memorial_notice_style_value",
    "build_memorial_notice_context",
]
