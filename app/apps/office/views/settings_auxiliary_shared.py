from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages

from apps.imports.models import (
    AnnualMembershipFeePayment,
    Household,
    LegacySource,
    Person,
    RecordEditLog,
    ServiceSchedule,
)
from apps.office.services.record_history_mutations import record_action_message_text
from apps.office.services.record_history_snapshot import (
    _serialize_household_record,
    _serialize_person_record,
)


def _with_optional_query(url: str, **params: object) -> str:
    query = {
        key: value
        for key, value in params.items()
        if value not in {None, ""}
    }
    if not query:
        return url
    return f"{url}?{urlencode(query)}"


def _flash_record_action_message(
    request,
    log_entry: RecordEditLog | None,
    message_text: str,
) -> None:
    messages.success(request, record_action_message_text(log_entry, message_text))


def _rollbackable_created_auxiliary_household(
    *,
    source_record: LegacySource,
    household: Household,
    expected_household_source_table: str,
    expected_head_source_table: str,
) -> tuple[bool, str, list[Person]]:
    if household.source_table != expected_household_source_table:
        return False, "この家は review の新規作成 household ではありません。", []
    active_people = list(
        Person.objects.filter(household=household, deleted_at__isnull=True).order_by("id")
    )
    if len(active_people) != 1:
        return (
            False,
            "この家には追加の現在帳/過去帳 person があるため、自動で作成取消できません。",
            active_people,
        )
    head_person = active_people[0]
    if head_person.source_table != expected_head_source_table:
        return False, "戸主 person が review 作成由来ではないため、自動で作成取消できません。", active_people
    if ServiceSchedule.objects.filter(household=household, deleted_at__isnull=True).exists():
        return False, "この家には法要予定があるため、自動で作成取消できません。", active_people
    if AnnualMembershipFeePayment.objects.filter(
        source=source_record,
        household_uid=household.household_uid,
    ).exists():
        return False, "この家には護持会費記録があるため、自動で作成取消できません。", active_people
    return True, "", active_people


__all__ = [
    "_flash_record_action_message",
    "_rollbackable_created_auxiliary_household",
    "_serialize_household_record",
    "_serialize_person_record",
    "_with_optional_query",
]
