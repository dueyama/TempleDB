from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from apps.core.services import tenant_policy as tenant_policy_services

from .importer_parsing import (
    _parse_legacy_household_notice_opt_out as _importer_parse_legacy_household_notice_opt_out,
)
from .models import HouseholdProfile, Person
from .runtime_shared import _clean_value


def relationship_label_choices(
    source_id: str | None,
    *,
    current_value: str = "",
) -> list[tuple[str, str]]:
    labels: list[str] = []
    seen: set[str] = set()

    def add_label(value: str | None) -> None:
        cleaned = _clean_value(value)
        if cleaned and cleaned not in seen:
            labels.append(cleaned)
            seen.add(cleaned)

    for value, _label in tenant_policy_services.relationship_label_choices():
        add_label(value)

    try:
        query = Person.objects.exclude(relationship_label="")
        if source_id:
            query = query.filter(legacy_source_id=source_id)
        db_labels = sorted(
            {
                cleaned
                for value in query.values_list("relationship_label", flat=True).distinct()
                if (cleaned := _clean_value(value))
            }
        )
    except (OperationalError, ProgrammingError):
        db_labels = []
    for label in db_labels:
        add_label(label)
    add_label(current_value)

    return [("", "---------"), *((label, label) for label in labels)]


def _legacy_bool_value(value: bool | None, raw_value: str | None = None) -> str:
    cleaned = _clean_value(raw_value)
    if cleaned:
        return cleaned
    if value is None:
        return ""
    return "1" if value else "0"


def _parse_legacy_boolish(value: str | None) -> bool:
    return _clean_value(value).lower() in {"1", "true", "yes", "on"}


def _parse_legacy_household_notice_opt_out(value: str | None) -> bool:
    return _importer_parse_legacy_household_notice_opt_out(value)


def _parse_household_profile_notice_opt_out(value: str | None) -> bool | None:
    cleaned = _clean_value(value).lower()
    if cleaned == "true":
        return True
    if cleaned == "false":
        return False
    return None


def _household_general_notice_display_value(*, profile_value: bool | None) -> str:
    if profile_value is None:
        return ""
    return "不要" if bool(profile_value) else "要"


def _effective_household_memorial_notice_opt_out(
    *,
    profile_value: bool | None,
    raw_value: str | None,
) -> bool:
    if profile_value is not None:
        return bool(profile_value)
    return _parse_legacy_household_notice_opt_out(raw_value)


def _household_memorial_notice_display_value(
    *,
    profile_value: bool | None,
    raw_value: str | None,
) -> str:
    if profile_value is None:
        return ""
    return "不要" if _effective_household_memorial_notice_opt_out(
        profile_value=profile_value,
        raw_value=raw_value,
    ) else "要"


def _household_profile_for_display(source_id: str, household_id: str) -> HouseholdProfile | None:
    if not household_id:
        return None
    try:
        return (
            HouseholdProfile.objects.select_related("district")
            .filter(source__source_id=source_id, household_uid=household_id)
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None
