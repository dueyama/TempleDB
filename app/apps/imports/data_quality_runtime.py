from __future__ import annotations

from . import data_science_runtime
from .data_quality_duplicates import (
    _address_line2_duplicate_candidates,
    _duplicated_address_line2_suffix,
)
from .data_quality_page_context import (
    _legacy_build_data_quality_context,
    build_data_quality_context,
)
from .data_quality_same_name import _decorate_same_name_groups as _decorate_same_name_groups

# Owner modules resolve these shared dependencies through the facade at call time.
from .quality_runtime_shared import (
    _load_household_browser_dataset as _load_household_browser_dataset,
)
from .quality_runtime_shared import (
    latest_export_snapshot as latest_export_snapshot,
)
from .quality_runtime_shared import (
    latest_succeeded_import_batch as latest_succeeded_import_batch,
)
from .quality_runtime_shared import (
    registered_sources as registered_sources,
)
from .quality_runtime_shared import (
    resolve_runtime_source_entry as resolve_runtime_source_entry,
)
from .quality_runtime_shared import (
    source_summary as source_summary,
)

latest_import_issue_breakdown = data_science_runtime.latest_import_issue_breakdown
_SAME_NAME_PREVIEW_MEMBER_LIMIT = 3


__all__ = [
    "_address_line2_duplicate_candidates",
    "_duplicated_address_line2_suffix",
    "_legacy_build_data_quality_context",
    "build_data_quality_context",
]
