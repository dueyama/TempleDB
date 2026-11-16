from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

from apps.core.models import GoogleCalendarSyncSetting
from config.runtime_paths import tenant_root

from . import runtime_role

GOOGLE_CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)


class GoogleCalendarConfigurationError(RuntimeError):
    pass


class GoogleCalendarApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleCalendarNotFoundError(GoogleCalendarApiError):
    pass


class GoogleCalendarConflictError(GoogleCalendarApiError):
    pass


@dataclass(frozen=True)
class GoogleCalendarServiceAccountInfo:
    configured: bool
    path: str
    client_email: str
    project_id: str
    error: str


def get_or_create_google_calendar_sync_setting() -> GoogleCalendarSyncSetting:
    setting, _created = GoogleCalendarSyncSetting.objects.get_or_create(singleton_key=1)
    return setting


def google_calendar_base_url(setting: GoogleCalendarSyncSetting | None = None) -> str:
    env_value = (getattr(settings, "TEMPLEDB_BASE_URL", "") or "").strip()
    if env_value:
        return _normalized_absolute_url(env_value)
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    compatibility_value = (resolved_setting.base_url or "").strip()
    if compatibility_value:
        return _normalized_absolute_url(compatibility_value)
    browser_host = (os.environ.get("TEMPLEDB_BROWSER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (os.environ.get("TEMPLEDB_PORT") or "8000").strip() or "8000"
    return f"http://{browser_host}:{port}"


def google_calendar_external_base_url(setting: GoogleCalendarSyncSetting | None = None) -> str:
    env_value = (getattr(settings, "TEMPLEDB_EXTERNAL_BASE_URL", "") or "").strip()
    if env_value:
        return _normalized_absolute_url(env_value)
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    compatibility_value = (resolved_setting.external_base_url or "").strip()
    if compatibility_value:
        return _normalized_absolute_url(compatibility_value)
    return ""


def google_calendar_base_url_source(setting: GoogleCalendarSyncSetting | None = None) -> str:
    if (getattr(settings, "TEMPLEDB_BASE_URL", "") or "").strip():
        return "env"
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    if (resolved_setting.base_url or "").strip():
        return "database_compatibility"
    return "local_default"


def google_calendar_external_base_url_source(
    setting: GoogleCalendarSyncSetting | None = None,
) -> str:
    if (getattr(settings, "TEMPLEDB_EXTERNAL_BASE_URL", "") or "").strip():
        return "env"
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    if (resolved_setting.external_base_url or "").strip():
        return "database_compatibility"
    return "unset"


def _normalized_absolute_url(raw_value: str) -> str:
    value = (raw_value or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.query or parsed.fragment:
        return ""
    return value.rstrip("/")


def _configured_url_error(raw_value: str, *, label: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"{label}は http:// または https:// で始まる絶対URLにしてください。"
    if parsed.query or parsed.fragment:
        return f"{label}には query や fragment を含められません。"
    return ""


def _google_calendar_url_configuration_errors(
    setting: GoogleCalendarSyncSetting,
) -> list[str]:
    errors: list[str] = []
    internal_env = (getattr(settings, "TEMPLEDB_BASE_URL", "") or "").strip()
    external_env = (getattr(settings, "TEMPLEDB_EXTERNAL_BASE_URL", "") or "").strip()
    internal_value = internal_env or (setting.base_url or "").strip()
    external_value = external_env or (setting.external_base_url or "").strip()
    internal_label = (
        "TEMPLEDB_BASE_URL"
        if internal_env
        else "旧DB互換のTempleDB内部URL"
    )
    external_label = (
        "TEMPLEDB_EXTERNAL_BASE_URL"
        if external_env
        else "旧DB互換のTempleDB外部URL"
    )
    internal_error = _configured_url_error(internal_value, label=internal_label)
    external_error = _configured_url_error(external_value, label=external_label)
    if internal_error:
        errors.append(internal_error)
    if external_error:
        errors.append(external_error)
    return errors


def google_calendar_service_account_info() -> GoogleCalendarServiceAccountInfo:
    raw_path = (os.environ.get("TEMPLEDB_GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    if not raw_path:
        return GoogleCalendarServiceAccountInfo(
            configured=False,
            path="",
            client_email="",
            project_id="",
            error="TEMPLEDB_GOOGLE_SERVICE_ACCOUNT_FILE が未設定です。",
        )
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = tenant_root() / path
    if not path.exists():
        return GoogleCalendarServiceAccountInfo(
            configured=False,
            path=str(path),
            client_email="",
            project_id="",
            error="Service Account JSON ファイルが見つかりません。",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return GoogleCalendarServiceAccountInfo(
            configured=False,
            path=str(path),
            client_email="",
            project_id="",
            error=f"Service Account JSON を読めませんでした: {exc}",
        )
    return GoogleCalendarServiceAccountInfo(
        configured=True,
        path=str(path),
        client_email=str(payload.get("client_email", "") or "").strip(),
        project_id=str(payload.get("project_id", "") or "").strip(),
        error="",
    )


def google_calendar_configuration_errors(
    setting: GoogleCalendarSyncSetting | None = None,
) -> list[str]:
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    errors: list[str] = []
    if not resolved_setting.enabled:
        return errors
    if not runtime_role.google_calendar_access_allowed():
        return [runtime_role.google_calendar_block_message()]
    if not (resolved_setting.calendar_id or "").strip():
        errors.append("Google カレンダー ID が未設定です。")
    errors.extend(_google_calendar_url_configuration_errors(resolved_setting))
    account_info = google_calendar_service_account_info()
    if not account_info.configured:
        errors.append(account_info.error)
    elif not account_info.client_email:
        errors.append("Service Account JSON に client_email がありません。")
    client_import_error = _google_calendar_client_import_error()
    if client_import_error:
        errors.append(client_import_error)
    return errors


def google_calendar_is_ready(setting: GoogleCalendarSyncSetting | None = None) -> bool:
    resolved_setting = setting or get_or_create_google_calendar_sync_setting()
    if not resolved_setting.enabled:
        return False
    return not google_calendar_configuration_errors(resolved_setting)


def create_google_calendar_event(
    *,
    calendar_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    _assert_google_calendar_remote_access_allowed()
    try:
        return _calendar_events_resource().insert(calendarId=calendar_id, body=body).execute()
    except Exception as exc:
        raise _normalize_google_calendar_exception(exc) from exc


def fetch_google_calendar_event(
    *,
    calendar_id: str,
    event_id: str,
) -> dict[str, Any]:
    _assert_google_calendar_remote_access_allowed()
    try:
        return _calendar_events_resource().get(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:
        raise _normalize_google_calendar_exception(exc) from exc


def update_google_calendar_event(
    *,
    calendar_id: str,
    event_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    _assert_google_calendar_remote_access_allowed()
    try:
        return (
            _calendar_events_resource()
            .patch(calendarId=calendar_id, eventId=event_id, body=body)
            .execute()
        )
    except Exception as exc:
        raise _normalize_google_calendar_exception(exc) from exc


def delete_google_calendar_event(
    *,
    calendar_id: str,
    event_id: str,
) -> None:
    _assert_google_calendar_remote_access_allowed()
    try:
        _calendar_events_resource().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:
        # Calendar also answers DELETE of an already-deleted event with 410.
        # Other 410s (for example an expired sync token) remain errors.
        if _http_status_code(exc) == 410 and _google_error_reason(exc) == "deleted":
            return
        raise _normalize_google_calendar_exception(exc) from exc


def _assert_google_calendar_remote_access_allowed() -> None:
    try:
        runtime_role.assert_google_calendar_access_allowed()
    except runtime_role.RuntimeRoleConfigurationError as exc:
        raise GoogleCalendarConfigurationError(str(exc)) from exc


def _calendar_events_resource():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - import error path only
        raise GoogleCalendarConfigurationError(
            "google-auth / google-api-python-client が未導入です。"
        ) from exc
    account_info = google_calendar_service_account_info()
    if not account_info.configured:
        raise GoogleCalendarConfigurationError(account_info.error)
    credentials = service_account.Credentials.from_service_account_file(
        account_info.path,
        scopes=list(GOOGLE_CALENDAR_SCOPES),
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return service.events()


def _normalize_google_calendar_exception(exc: Exception) -> Exception:
    if isinstance(exc, (GoogleCalendarConfigurationError, GoogleCalendarApiError)):
        return exc
    status_code = _http_status_code(exc)
    message = _google_error_message(exc)
    if status_code == 404:
        return GoogleCalendarNotFoundError(message or "Google カレンダー上のイベントが見つかりません。", status_code=404)
    if status_code in {409, 412}:
        return GoogleCalendarConflictError(message or "Google カレンダーとの競合を検出しました。", status_code=status_code)
    return GoogleCalendarApiError(
        message or "Google カレンダー API の呼び出しに失敗しました。",
        status_code=status_code,
    )


def _http_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _google_error_message(exc: Exception) -> str:
    content = getattr(exc, "content", None)
    if isinstance(content, bytes):
        try:
            payload = json.loads(content.decode("utf-8"))
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    return str(error.get("message") or "").strip()
        except (ValueError, UnicodeDecodeError):
            pass
    return str(exc).strip()


def _google_error_reason(exc: Exception) -> str:
    content = getattr(exc, "content", None)
    if not isinstance(content, bytes):
        return ""
    try:
        payload = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        return ""
    return str(errors[0].get("reason") or "").strip()


def _google_calendar_client_import_error() -> str:
    try:
        from google.oauth2 import service_account  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError:
        return "google-auth / google-api-python-client が未導入です。"
    return ""
