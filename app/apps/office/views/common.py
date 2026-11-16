from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest

from apps.imports import source_runtime
from apps.imports.models import ImportBatch, LegacySource
from apps.office.services.canonical_ledger import (
    CanonicalLedgerContext,
    CanonicalLedgerUnavailable,
    resolve_canonical_ledger_context,
)
from apps.office.web_support import (
    HOUSEHOLD_BROWSER_PREVIEW_MODES as HOUSEHOLD_BROWSER_PREVIEW_MODES,
)
from apps.office.web_support import (
    RECORD_HISTORY_ACTIONS as RECORD_HISTORY_ACTIONS,
)
from apps.office.web_support import (
    _annual_membership_fees_url as _annual_membership_fees_url,
)
from apps.office.web_support import (
    _backup_settings_url as _backup_settings_url,
)
from apps.office.web_support import (
    _default_household_browser_url as _default_household_browser_url,
)
from apps.office.web_support import (
    _default_service_ledger_url as _default_service_ledger_url,
)
from apps.office.web_support import (
    _districts_url as _districts_url,
)
from apps.office.web_support import (
    _household_browser_prefers_list_first_view as _household_browser_prefers_list_first_view,
)
from apps.office.web_support import (
    _household_districts_url as _household_districts_url,
)
from apps.office.web_support import (
    _normalize_household_browser_preview_mode as _normalize_household_browser_preview_mode,
)
from apps.office.web_support import (
    _normalize_record_history_action as _normalize_record_history_action,
)
from apps.office.web_support import (
    _normalize_time_machine_mode as _normalize_time_machine_mode,
)
from apps.office.web_support import (
    _normalized_request_url as _normalized_request_url,
)
from apps.office.web_support import (
    _parse_boolean_flag as _parse_boolean_flag,
)
from apps.office.web_support import (
    _parse_optional_font_size as _parse_optional_font_size,
)
from apps.office.web_support import (
    _parse_optional_year as _parse_optional_year,
)
from apps.office.web_support import (
    _request_actor_label as _request_actor_label,
)
from apps.office.web_support import (
    _resolve_household_edit_context as _resolve_household_edit_context,
)
from apps.office.web_support import (
    _resolve_next_url as _resolve_next_url,
)
from apps.office.web_support import (
    _resolved_household_browser_preview_mode as _resolved_household_browser_preview_mode,
)
from apps.office.web_support import (
    _time_machine_toggle_url as _time_machine_toggle_url,
)
from apps.office.web_support import (
    _user_management_redirect_url as _user_management_redirect_url,
)


def _ensure_source_record(source_id: str | None) -> LegacySource:
    try:
        return source_runtime.ensure_operational_source_record(source_id)
    except KeyError as exc:
        raise Http404(f"unknown source: {source_id}") from exc


def _current_operational_source_id() -> str:
    try:
        return source_runtime.operational_source_id()
    except KeyError as exc:
        raise Http404("unknown operational source") from exc


def _canonical_ledger_context(
    source_id: str | None = None,
) -> CanonicalLedgerContext:
    try:
        return resolve_canonical_ledger_context(source_id)
    except CanonicalLedgerUnavailable as exc:
        raise Http404(str(exc)) from exc


def _current_operational_source_record() -> LegacySource:
    return _ensure_source_record(_current_operational_source_id())


def _ensure_superuser(request: HttpRequest) -> None:
    if not request.user.is_superuser:
        raise PermissionDenied("この画面は管理者のみ利用できます。")


def _resolve_editable_batch(source_id: str | None) -> tuple[str, ImportBatch]:
    context = _canonical_ledger_context(source_id)
    return context.source_id, context.provenance_batch
