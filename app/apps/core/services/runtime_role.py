from __future__ import annotations

from django.conf import settings

RUNTIME_ROLE_PRIMARY = "primary"
RUNTIME_ROLE_STAGING = "staging"
RUNTIME_ROLE_STANDBY = "standby"
VALID_RUNTIME_ROLES = frozenset(
    {
        RUNTIME_ROLE_PRIMARY,
        RUNTIME_ROLE_STAGING,
        RUNTIME_ROLE_STANDBY,
    }
)


class RuntimeRoleConfigurationError(RuntimeError):
    """Raised when a machine runtime role is invalid or blocks an operation."""


def current_runtime_role() -> str:
    role = str(
        getattr(settings, "TEMPLEDB_RUNTIME_ROLE", RUNTIME_ROLE_PRIMARY) or ""
    ).strip().lower()
    if role not in VALID_RUNTIME_ROLES:
        valid_values = ", ".join(sorted(VALID_RUNTIME_ROLES))
        raise RuntimeRoleConfigurationError(
            f"TEMPLEDB_RUNTIME_ROLE must be one of: {valid_values}."
        )
    return role


def google_calendar_access_allowed() -> bool:
    return current_runtime_role() == RUNTIME_ROLE_PRIMARY


def openai_requests_allowed() -> bool:
    role = current_runtime_role()
    if role == RUNTIME_ROLE_PRIMARY:
        return True
    if role == RUNTIME_ROLE_STAGING:
        return bool(getattr(settings, "TEMPLEDB_STAGING_ALLOW_OPENAI", False))
    return False


def scheduled_maintenance_allowed() -> bool:
    return current_runtime_role() == RUNTIME_ROLE_PRIMARY


def google_calendar_block_message() -> str:
    role = current_runtime_role()
    return (
        f"TEMPLEDB_RUNTIME_ROLE={role} のため、"
        "Google カレンダーへのアクセスと同期を停止しています。"
    )


def openai_request_block_message() -> str:
    role = current_runtime_role()
    if role == RUNTIME_ROLE_STAGING:
        return (
            "TEMPLEDB_RUNTIME_ROLE=staging でOpenAI APIを使用するには、"
            "machine profileでTEMPLEDB_STAGING_ALLOW_OPENAI=1を明示してください。"
        )
    return (
        f"TEMPLEDB_RUNTIME_ROLE={role} のため、"
        "OpenAI APIへのデータ送信を停止しています。"
    )


def assert_google_calendar_access_allowed() -> None:
    if not google_calendar_access_allowed():
        raise RuntimeRoleConfigurationError(google_calendar_block_message())


def assert_openai_requests_allowed() -> None:
    if not openai_requests_allowed():
        raise RuntimeRoleConfigurationError(openai_request_block_message())


def external_service_writes_allowed() -> bool:
    """Compatibility alias for the original Google Calendar guard."""
    return google_calendar_access_allowed()


def external_service_block_message() -> str:
    """Compatibility alias for the original Google Calendar message."""
    return google_calendar_block_message()


def assert_external_service_writes_allowed() -> None:
    """Compatibility alias for the original Google Calendar assertion."""
    assert_google_calendar_access_allowed()


__all__ = [
    "RUNTIME_ROLE_PRIMARY",
    "RUNTIME_ROLE_STAGING",
    "RUNTIME_ROLE_STANDBY",
    "RuntimeRoleConfigurationError",
    "VALID_RUNTIME_ROLES",
    "assert_external_service_writes_allowed",
    "assert_google_calendar_access_allowed",
    "assert_openai_requests_allowed",
    "current_runtime_role",
    "external_service_block_message",
    "external_service_writes_allowed",
    "google_calendar_access_allowed",
    "google_calendar_block_message",
    "openai_request_block_message",
    "openai_requests_allowed",
    "scheduled_maintenance_allowed",
]
