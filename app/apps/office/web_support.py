from __future__ import annotations

from urllib.parse import urlencode, urlparse

from django.http import HttpRequest, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.imports.models import Household

HOUSEHOLD_BROWSER_PREVIEW_MODES = (
    {"key": "auto", "label": "Auto"},
    {"key": "desktop", "label": "Desktop"},
    {"key": "tablet", "label": "iPad"},
    {"key": "mobile", "label": "iPhone"},
)
SERVICE_LEDGER_CARD_VIEW_MODES = (
    {"key": "compact", "label": "閉じて表示"},
    {"key": "expanded", "label": "開いて表示"},
)
RECORD_HISTORY_ACTIONS = (
    {"key": "all", "label": "すべて"},
    {"key": "update", "label": "更新"},
    {"key": "delete", "label": "削除"},
    {"key": "restore", "label": "復元"},
    {"key": "reset_schedule", "label": "予定リセット"},
    {"key": "link_update", "label": "法要リンク調整"},
)


def _normalize_household_browser_preview_mode(preview: str | None) -> str:
    valid_modes = {item["key"] for item in HOUSEHOLD_BROWSER_PREVIEW_MODES}
    if preview in valid_modes:
        return preview
    return "auto"


def _resolved_household_browser_preview_mode(request: HttpRequest) -> str:
    requested = _normalize_household_browser_preview_mode(request.GET.get("preview"))
    if requested != "auto":
        return requested
    user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if "iphone" in user_agent or "ipod" in user_agent:
        return "mobile"
    if "ipad" in user_agent:
        return "tablet"
    return requested


def _normalize_household_browser_focus_mode(focus: str | None) -> str:
    if focus == "detail":
        return "detail"
    return "list"


def _normalize_service_ledger_card_view(card_view: str | None) -> str:
    valid_modes = {item["key"] for item in SERVICE_LEDGER_CARD_VIEW_MODES}
    if card_view in valid_modes:
        return str(card_view)
    return "compact"


def _household_browser_prefers_list_first_view(
    request: HttpRequest,
    preview_mode: str,
) -> bool:
    if preview_mode in {"mobile", "tablet"}:
        return True
    if preview_mode != "auto":
        return False
    user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    mobile_markers = ("iphone", "ipod", "android", "mobile")
    return any(marker in user_agent for marker in mobile_markers)


def _normalize_record_history_action(action: str | None) -> str:
    valid_actions = {item["key"] for item in RECORD_HISTORY_ACTIONS}
    if action in valid_actions:
        return str(action)
    return "all"


def _normalize_time_machine_mode(value: str | None) -> bool:
    return str(value or "").strip() in {"1", "true", "on", "yes"}


def _time_machine_toggle_url(request: HttpRequest, *, enabled: bool) -> str:
    query = request.GET.copy()
    if enabled:
        query["time_machine"] = "1"
    else:
        query.pop("time_machine", None)
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _service_ledger_card_view_url(request: HttpRequest, *, card_view: str) -> str:
    query = request.GET.copy()
    for key in ("source_id", "backend"):
        query.pop(key, None)
    query["card_view"] = _normalize_service_ledger_card_view(card_view)
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _normalized_service_ledger_request_url(request: HttpRequest) -> str:
    query = request.GET.copy()
    for key in ("source_id", "backend"):
        query.pop(key, None)
    query["card_view"] = _normalize_service_ledger_card_view(request.GET.get("card_view"))
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _parse_optional_year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_font_size(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if 0.4 <= parsed <= 4.0:
        return parsed
    return None


def _parse_boolean_flag(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"", "0", "false", "off", "no"}


def _normalized_request_url(
    request: HttpRequest,
    *,
    drop_keys: tuple[str, ...] = ("source_id", "backend"),
) -> str:
    query = request.GET.copy()
    for key in drop_keys:
        query.pop(key, None)
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _request_actor_label(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return ""
    return user.get_username().strip()


def _resolve_next_url(request: HttpRequest, fallback_url: str) -> str:
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback_url


def _default_household_browser_url(
    household_id: str | None = None,
    *,
    focus: str | None = None,
) -> str:
    url = reverse("office:household_browser")
    query: dict[str, str] = {}
    if household_id:
        query["household_id"] = household_id
    if focus:
        query["focus"] = focus
    if not query:
        return url
    return f"{url}?{urlencode(query)}"


def _resolved_relative_view_name(url: str) -> str | None:
    parsed = urlparse(url)
    try:
        return resolve(parsed.path).view_name
    except Resolver404:
        return None


def _relative_url_with_query(path: str, query: QueryDict) -> str:
    encoded = query.urlencode()
    return f"{path}?{encoded}" if encoded else path


def _normalized_household_browser_return_url(
    next_url: str,
    *,
    household_id: str,
    keep_household_detail: bool,
) -> str:
    browser_path = reverse("office:household_browser")
    parsed = urlparse(next_url)
    query = QueryDict(parsed.query, mutable=True)
    for key in ("source_id", "backend"):
        query.pop(key, None)
    selected_household_id = (query.get("household_id") or "").strip()
    if keep_household_detail:
        if selected_household_id == household_id:
            query["focus"] = "detail"
        return _relative_url_with_query(browser_path, query)
    if selected_household_id == household_id:
        query.pop("household_id", None)
        query.pop("focus", None)
    return _relative_url_with_query(browser_path, query)


def _safe_deleted_record_return_url(
    next_url: str,
    *,
    household_id: str,
    deleted_record_type: str,
) -> str:
    view_name = _resolved_relative_view_name(next_url)
    if view_name == "office:household_browser":
        return _normalized_household_browser_return_url(
            next_url,
            household_id=household_id,
            keep_household_detail=deleted_record_type != "household",
        )
    if view_name in {"office:edit_person", "office:edit_household"}:
        if deleted_record_type == "household":
            return _default_household_browser_url()
        return _default_household_browser_url(household_id, focus="detail")
    return next_url


def _deleted_record_return_label(
    return_url: str,
    *,
    household_id: str,
) -> str:
    return _record_action_return_label(return_url, household_id=household_id)


def _record_action_return_label(
    return_url: str,
    *,
    household_id: str,
) -> str:
    view_name = _resolved_relative_view_name(return_url)
    if view_name == "office:household_browser":
        query = QueryDict(urlparse(return_url).query)
        if (query.get("household_id") or "").strip() == household_id:
            return "家へ戻る"
        return "一覧へ戻る"
    if view_name and view_name.startswith("office:"):
        return "一覧へ戻る"
    return "戻る"


def _safe_household_action_return_url(
    next_url: str,
    *,
    household_id: str,
    stale_view_names: tuple[str, ...] = (),
) -> str:
    view_name = _resolved_relative_view_name(next_url)
    if view_name == "office:household_browser":
        return _normalized_household_browser_return_url(
            next_url,
            household_id=household_id,
            keep_household_detail=True,
        )
    if view_name in {
        "office:edit_person",
        "office:edit_household",
        *stale_view_names,
    }:
        return _default_household_browser_url(household_id, focus="detail")
    return next_url


def _safe_memorial_person_move_return_url(
    next_url: str,
    *,
    source_household_id: str,
    target_household_id: str,
) -> str:
    view_name = _resolved_relative_view_name(next_url)
    if view_name == "office:household_browser":
        parsed = urlparse(next_url)
        query = QueryDict(parsed.query, mutable=True)
        for key in ("source_id", "backend"):
            query.pop(key, None)
        selected_household_id = (query.get("household_id") or "").strip()
        if selected_household_id == source_household_id:
            query["household_id"] = target_household_id
            query["focus"] = "detail"
        return _relative_url_with_query(reverse("office:household_browser"), query)
    if view_name in {
        "office:edit_person",
        "office:edit_household",
        "office:move_memorial_person_household",
    }:
        return _default_household_browser_url(target_household_id, focus="detail")
    return next_url


def _default_service_ledger_url() -> str:
    return reverse("office:service_ledger")


def _districts_url(*, edit: int | None = None) -> str:
    url = reverse("office:districts")
    if edit is not None:
        url += f"?edit={edit}"
    return url


def _household_districts_url(*, q: str = "", filter_district_id: str = "") -> str:
    url = reverse("office:household_districts")
    params = {}
    if q:
        params["q"] = q
    if filter_district_id:
        params["filter_district_id"] = filter_district_id
    if params:
        url += f"?{urlencode(params)}"
    return url


def _annual_membership_fees_url(
    *,
    year: int | None = None,
    payment_status: str = "",
) -> str:
    url = reverse("office:annual_membership_fees")
    params = {}
    if year is not None:
        params["year"] = str(year)
    if payment_status in {"billable", "paid", "unpaid"}:
        params["payment_status"] = payment_status
    if params:
        url += f"?{urlencode(params)}"
    return url


def _annual_membership_fee_receipts_url(*, year: int | None = None) -> str:
    url = reverse("office:annual_membership_fee_receipts")
    if year is not None:
        url += f"?year={year}"
    return url


def _annual_membership_fee_check_sheets_url(
    *,
    year: int | None = None,
    format_pdf: bool = False,
    mode: str = "",
) -> str:
    url = reverse("office:annual_membership_fee_check_sheets")
    params = {}
    if year is not None:
        params["year"] = str(year)
    if format_pdf:
        params["format"] = "pdf"
    if mode in {"print", "review"}:
        params["mode"] = mode
    if params:
        url += f"?{urlencode(params)}"
    return url


def _annual_membership_fee_postal_scans_url(*, year: int | None = None) -> str:
    url = reverse("office:annual_membership_fee_postal_scans")
    if year is not None:
        url += f"?{urlencode({'year': str(year)})}"
    return url


def _annual_membership_fee_postal_scan_anchor_url(
    *,
    year: int,
    scan_id: int | str | None,
) -> str:
    url = _annual_membership_fee_postal_scans_url(year=year)
    try:
        normalized_scan_id = int(scan_id) if scan_id else None
    except (TypeError, ValueError):
        normalized_scan_id = None
    if normalized_scan_id:
        url = f"{url}#postal-scan-{normalized_scan_id}"
    return url


def _backup_settings_url() -> str:
    return reverse("office:backup_settings")


def _backup_migration_guide_url(*, run_id: int | None = None) -> str:
    url = reverse("office:backup_migration_guide")
    if run_id is None:
        return url
    return f"{url}?{urlencode({'run_id': str(run_id)})}"


def _google_calendar_settings_url() -> str:
    return reverse("office:google_calendar_settings")


def _google_calendar_bulk_sync_status_url() -> str:
    return reverse("office:google_calendar_bulk_sync_status")


def _user_management_redirect_url(
    *,
    password_user_id: int | None = None,
) -> str:
    query = {}
    if password_user_id is not None:
        query["password_user"] = str(password_user_id)
    if not query:
        return reverse("office:user_management")
    return f"{reverse('office:user_management')}?{urlencode(query)}"


def _resolve_household_edit_context(
    request: HttpRequest,
    source_id: str | None,
    household_id: str,
) -> tuple[str, Household, str]:
    from django.http import Http404

    from apps.imports import canonical_population, source_runtime

    try:
        active_source_id = source_runtime.operational_source_id(source_id)
    except KeyError as exc:
        raise Http404(f"unknown source: {source_id}") from exc
    if (
        canonical_population.canonical_provenance_import_batch(
            source_id=active_source_id,
        )
        is None
    ):
        raise Http404("canonical provenance batch not found")
    household = get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=household_id,
    )
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    return active_source_id, household, next_url
