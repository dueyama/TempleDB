from __future__ import annotations

from dataclasses import dataclass

from apps.imports import synthetic_household_runtime
from apps.imports.models import Household, Person, RecordEditLog

from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_household_record


@dataclass(frozen=True)
class HouseholdExtinctOutcome:
    household: Household
    extinct_head: Person
    log_entry: RecordEditLog | None
    created_extinct_head: bool
    retired_virtual_head_count: int


def _is_extinct_household_head_person(person: Person | None) -> bool:
    return bool(
        person is not None
        and person.deleted_at is None
        and person.source_table == synthetic_household_runtime.EXTINCT_HOUSEHOLD_HEAD_SOURCE_TABLE
    )


def mark_household_extinct(
    *,
    household: Household,
    editor_label: str,
) -> HouseholdExtinctOutcome:
    resolved_head_person = household.resolve_head_person()
    if _is_extinct_household_head_person(resolved_head_person):
        raise ValueError("この家はすでに絶家です。")

    living_people = synthetic_household_runtime.active_real_current_people(household)
    if living_people:
        people_label = " / ".join(person.name or person.person_uid for person in living_people)
        raise ValueError(
            f"現在帳に生存者が残っているため、絶家にできません。先に次の戸主を設定してください。 ({people_label})"
        )

    before_household = _serialize_household_record(household)
    retired_virtual_head_count = 0
    for virtual_head in synthetic_household_runtime.active_virtual_household_heads(household):
        virtual_head.mark_deleted(
            editor_label=editor_label,
            note="絶家 synthetic head へ置換",
        )
        virtual_head.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
        retired_virtual_head_count += 1

    identity = synthetic_household_runtime.resolve_extinct_household_identity(household)
    extinct_head, created_extinct_head = synthetic_household_runtime.get_or_create_extinct_household_head(
        household=household,
        identity=identity,
    )
    previous_notes = household.notes or ""
    synthetic_household_runtime.append_household_note(
        household,
        synthetic_household_runtime.EXTINCT_HOUSEHOLD_NOTE,
    )
    if household.notes != previous_notes:
        household.save(update_fields=["notes", "updated_at"])

    household = Household.objects.select_related("head_person").get(pk=household.pk)
    log_entry = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD,
        record=household,
        before_data=before_household,
        after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note="戸主レコードを絶家 household に変更",
    )
    return HouseholdExtinctOutcome(
        household=household,
        extinct_head=extinct_head,
        log_entry=log_entry,
        created_extinct_head=created_extinct_head,
        retired_virtual_head_count=retired_virtual_head_count,
    )


__all__ = [
    "HouseholdExtinctOutcome",
    "_is_extinct_household_head_person",
    "mark_household_extinct",
]
