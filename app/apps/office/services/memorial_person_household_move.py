from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.imports.model_households import safe_display_head_name
from apps.imports.models import (
    FAMILY_CATEGORY_MEMORIAL,
    Household,
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
    VisitNote,
)
from apps.imports.runtime_shared import _clean_value, _int_sort, _search_text, _sort_text
from apps.office.services.household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _person_for_edit,
)
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import _serialize_person_record

_MEMORIAL_MOVE_RESULT_LIMIT = 20


@dataclass(frozen=True)
class MemorialPersonMoveLinkedRecordCounts:
    schedule_count: int = 0
    visit_note_count: int = 0
    offering_payment_count: int = 0

    @property
    def total(self) -> int:
        return self.schedule_count + self.visit_note_count + self.offering_payment_count


@dataclass(frozen=True)
class MemorialPersonMoveOutcome:
    person: Person
    target_household: Household
    log_entry: RecordEditLog | None


def memorial_person_move_is_available(person: Person) -> bool:
    if person.deleted_at is not None:
        return False
    if person.family_category == FAMILY_CATEGORY_MEMORIAL:
        return True
    return bool(person.is_deceased)


def memorial_person_move_linked_record_counts(person: Person) -> MemorialPersonMoveLinkedRecordCounts:
    return MemorialPersonMoveLinkedRecordCounts(
        schedule_count=ServiceSchedule.objects.filter(person=person, deleted_at__isnull=True).count(),
        visit_note_count=VisitNote.objects.filter(person=person).count(),
        offering_payment_count=OfferingPayment.objects.filter(person=person).count(),
    )


def memorial_person_move_blocker_message(person: Person) -> str:
    counts = memorial_person_move_linked_record_counts(person)
    if counts.total == 0:
        return ""
    labels: list[str] = []
    if counts.schedule_count:
        labels.append(f"法要予定 {counts.schedule_count} 件")
    if counts.visit_note_count:
        labels.append(f"訪問メモ {counts.visit_note_count} 件")
    if counts.offering_payment_count:
        labels.append(f"入金 {counts.offering_payment_count} 件")
    return " / ".join(labels) + " がぶら下がっているため、まだ故人の家移動はできません。"


def search_memorial_person_move_households(
    *,
    query: str,
    exclude_household_id: str,
) -> list[dict]:
    needle = _search_text(query)
    if not needle:
        return []
    households = (
        Household.objects.filter(deleted_at__isnull=True)
        .select_related("head_person")
        .order_by("household_uid", "id")
    )
    entries: list[dict] = []
    normalized_query = _clean_value(query)
    for household in households:
        if household.household_uid == exclude_household_id:
            continue
        head_name = safe_display_head_name(household) or household.household_uid
        values = (
            household.household_uid,
            head_name,
            household.snapshot_head_name(),
            household.address_line1,
            household.address_line2,
            household.phone,
        )
        if not any(needle in _search_text(value) for value in values):
            continue
        entry = build_memorial_person_move_household_entry(household)
        entries.append(entry)
    return sorted(
        entries,
        key=lambda item: (
            0 if normalized_query and item["household_id"] == normalized_query else 1,
            0 if normalized_query and _search_text(item["household_name"]) == needle else 1,
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
        ),
    )[:_MEMORIAL_MOVE_RESULT_LIMIT]


def build_memorial_person_move_household_entry(household: Household) -> dict:
    active_people = list(
        household.persons.filter(deleted_at__isnull=True).order_by(
            "person_uid",
            "id",
        )
    )
    current_count = sum(
        1 for person in active_people if person.family_category != FAMILY_CATEGORY_MEMORIAL and not person.is_deceased
    )
    memorial_count = len(active_people) - current_count
    return {
        "household_id": household.household_uid,
        "household_name": safe_display_head_name(household) or household.household_uid,
        "address": " ".join(
            value for value in (household.address_line1, household.address_line2, household.address_line3) if value
        ),
        "phone": household.phone,
        "member_summary": f"現在帳 {current_count} 人 / 過去帳 {memorial_count} 人",
        "source_table": household.source_table,
    }


def resolve_memorial_person_move_target(
    *,
    target_household_id: str,
    source_household_id: str,
) -> Household:
    normalized_target_household_id = _clean_value(target_household_id)
    if not normalized_target_household_id:
        raise ValueError("移動先台帳IDを選んでください。")
    if normalized_target_household_id == source_household_id:
        raise ValueError("同じ家には移せません。")
    target_household = (
        Household.objects.filter(
            deleted_at__isnull=True,
            household_uid=normalized_target_household_id,
        )
        .select_related("head_person")
        .first()
    )
    if target_household is None:
        raise ValueError(f"移動先の台帳ID {normalized_target_household_id} が見つかりません。")
    return target_household


def move_memorial_person_to_household(
    *,
    person: Person,
    target_household: Household,
    editor_label: str,
    change_note: str,
) -> MemorialPersonMoveOutcome:
    if not memorial_person_move_is_available(person):
        raise ValueError("過去帳 person だけ移動できます。")
    if person.household_id == target_household.pk:
        raise ValueError("同じ家には移せません。")
    if person.household.deleted_at is not None:
        raise ValueError("元の家が削除済みのため、この画面からは移せません。")
    if target_household.deleted_at is not None:
        raise ValueError("移動先の家が削除済みです。")
    if person.batch_id != target_household.batch_id:
        raise ValueError("現行台帳内の家だけを移動先に選べます。")
    if person.household.head_person_id == person.pk:
        raise ValueError("戸主参照中の person はまだ移動できません。先に戸主整理をしてください。")
    blocker_message = memorial_person_move_blocker_message(person)
    if blocker_message:
        raise ValueError(blocker_message)

    before_data = _serialize_person_record(person)
    raw_record = dict(person.raw_record or {})
    raw_record["台帳ID"] = target_household.household_uid

    with transaction.atomic():
        person.household = target_household
        person.household_uid = target_household.household_uid
        person.raw_record = raw_record
        _apply_household_contact_defaults_to_person(person, target_household)
        person.save()
        refreshed_person = _person_for_edit(person.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=refreshed_person,
            before_data=before_data,
            after_data=_serialize_person_record(refreshed_person),
            editor_label=editor_label,
            change_note=change_note,
        )

    return MemorialPersonMoveOutcome(
        person=refreshed_person,
        target_household=target_household,
        log_entry=log_entry,
    )
