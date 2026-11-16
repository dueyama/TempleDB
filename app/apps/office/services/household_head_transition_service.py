from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.core.services.kana import normalize_kana_storage
from apps.imports import household_head_runtime, household_head_snapshot
from apps.imports.forms import HouseholdHeadTransitionForm
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    Household,
    Person,
    RecordEditLog,
)
from apps.imports.source_runtime import current_source_path

from .household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _household_display_head_name,
    _matching_household_head_people,
    _normalize_generated_head_person_id,
    _person_for_edit,
    _resolved_household_head_person,
)
from .record_history_mutations import _create_record_edit_log, record_action_message_text
from .record_history_snapshot import _serialize_household_record, _serialize_person_record


def _current_household_source_mdb_file(household: Household) -> str:
    return str(
        current_source_path(
            household.legacy_source_id,
            legacy_file_path=household.source_mdb_file,
        )
    )


@dataclass(frozen=True)
class HouseholdHeadMoveOutcome:
    person: Person
    log_entry: RecordEditLog | None
    success_message: str
    target_label: str
    created_person: bool


def _sync_household_head_snapshot_from_person(
    *,
    household: Household,
    head_person: Person,
) -> list[str]:
    return household_head_snapshot.sync_household_head_snapshot_from_person(
        household=household,
        head_person=head_person,
    )


def _is_virtual_household_head_person(person: Person | None) -> bool:
    return bool(
        person is not None
        and person.deleted_at is None
        and person.source_table == household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE
    )


def _sync_household_head_person_identity_from_form(
    *,
    household: Household,
    head_name: str,
    head_name_kana: str,
    editor_label: str,
    change_note: str,
) -> None:
    head_name_kana = normalize_kana_storage(head_name_kana)
    head_person = _resolved_household_head_person(household)
    if head_person is None and head_name:
        head_person = _create_manual_successor_head_person(
            household=household,
            manual_head_name=head_name,
            manual_head_name_kana=head_name_kana,
        )
    if head_person is None:
        return
    before_data = _serialize_person_record(head_person)
    updated_fields: list[str] = []
    if head_person.name != head_name:
        head_person.name = head_name
        updated_fields.append("name")
    if head_person.kana != head_name_kana:
        head_person.kana = head_name_kana
        updated_fields.append("kana")
    if not updated_fields:
        household_updated_fields = _sync_household_head_snapshot_from_person(
            household=household,
            head_person=head_person,
        )
        if household_updated_fields:
            household.save(update_fields=[*dict.fromkeys(household_updated_fields), "updated_at"])
        return
    head_person.save(update_fields=[*dict.fromkeys(updated_fields), "updated_at"])
    head_person = _person_for_edit(head_person.pk)
    household_updated_fields = _sync_household_head_snapshot_from_person(
        household=household,
        head_person=head_person,
    )
    if household_updated_fields:
        household.save(update_fields=[*dict.fromkeys(household_updated_fields), "updated_at"])
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=head_person,
        before_data=before_data,
        after_data=_serialize_person_record(head_person),
        editor_label=editor_label,
        change_note=change_note,
    )


def _replace_virtual_household_head(
    *,
    household: Household,
    successor_mode: str,
    successor_person_id: str,
    manual_head_name: str,
    manual_head_name_kana: str,
    editor_label: str,
) -> RecordEditLog:
    from .service_schedule_lifecycle import (
        _refresh_manual_service_schedule_household_snapshots,
        _refresh_offering_payment_household_snapshots,
    )

    virtual_head = _resolved_household_head_person(household)
    if not _is_virtual_household_head_person(virtual_head):
        raise ValueError("現在の戸主は仮戸主ではありません。")
    previous_household_name = household.snapshot_head_name() or virtual_head.name or ""
    mode = (successor_mode or "").strip()
    if mode == "current" and successor_person_id:
        successor = get_object_or_404(
            Person.objects.filter(
                batch=household.batch,
                household=household,
                deleted_at__isnull=True,
                family_category=FAMILY_CATEGORY_CURRENT,
            ).exclude(pk=virtual_head.pk),
            pk=successor_person_id,
        )
        change_note = f"仮戸主を現在帳から実戸主へ置換: {successor.name}"
    elif mode == "manual" and manual_head_name:
        successor = _create_manual_successor_head_person(
            household=household,
            manual_head_name=manual_head_name,
            manual_head_name_kana=manual_head_name_kana,
        )
        change_note = f"仮戸主を手入力で実戸主へ置換: {successor.name}"
    else:
        raise ValueError("実戸主の設定方法が不正です。")

    before_household = _serialize_household_record(household)
    before_virtual_head = _serialize_person_record(virtual_head)
    household_updates = _sync_household_head_snapshot_from_person(
        household=household,
        head_person=successor,
    )
    household.save(update_fields=[*dict.fromkeys(household_updates), "updated_at"])
    _refresh_manual_service_schedule_household_snapshots(
        household=household,
        previous_household_name=previous_household_name,
        editor_label=editor_label,
        change_note=change_note,
    )
    _refresh_offering_payment_household_snapshots(
        household=household,
        previous_household_name=previous_household_name,
    )

    virtual_head.mark_deleted(
        editor_label=editor_label,
        note=f"実戸主設定により退役: {successor.name}",
    )
    virtual_head.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
    virtual_head = _person_for_edit(virtual_head.pk)
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=virtual_head,
        before_data=before_virtual_head,
        after_data=_serialize_person_record(virtual_head),
        editor_label=editor_label,
        change_note=f"仮戸主を退役: {successor.name}",
    )

    household = Household.objects.get(pk=household.pk)
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD,
        record=household,
        before_data=before_household,
        after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note=change_note,
    )


def move_household_head_person(
    *,
    household: Household,
    target_category: str,
    editor_label: str,
) -> HouseholdHeadMoveOutcome:
    normalized_target = (
        FAMILY_CATEGORY_MEMORIAL if target_category == FAMILY_CATEGORY_MEMORIAL else FAMILY_CATEGORY_CURRENT
    )
    target_label = "過去帳" if normalized_target == FAMILY_CATEGORY_MEMORIAL else "現在帳"
    with transaction.atomic():
        person, before_data, created = _prepare_household_head_person_move(household)
        _apply_household_contact_defaults_to_person(person, household)
        person.family_category = normalized_target
        person.is_deceased = normalized_target == FAMILY_CATEGORY_MEMORIAL
        if normalized_target == FAMILY_CATEGORY_CURRENT:
            person.relationship_label = "本人"
        elif person.relationship_label.strip() == "":
            person.relationship_label = "戸主"
        person.save()
        household_updates = _sync_household_head_snapshot_from_person(
            household=household,
            head_person=person,
        )
        if household_updates:
            household.save(update_fields=[*household_updates, "updated_at"])
        if normalized_target == FAMILY_CATEGORY_CURRENT:
            person.clear_memorial_fields()
            person.save()
            person.sync_legacy_deceased_profile()
        person = _person_for_edit(person.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=person,
            before_data=before_data,
            after_data=_serialize_person_record(person),
            editor_label=editor_label,
            change_note=(
                f"戸主ブラウザで戸主を{target_label}に移動"
                + ("（新規 person 作成）" if created else "")
            ),
        )
    return HouseholdHeadMoveOutcome(
        person=person,
        log_entry=log_entry,
        success_message=record_action_message_text(
            log_entry,
            (
                f"戸主 {_household_display_head_name(household)} を {target_label} に移動しました。"
                + (" 家族レコードを新規作成しています。" if created else "")
            ),
        ),
        target_label=target_label,
        created_person=created,
    )


def _household_head_successor_choices(
    household: Household,
    *,
    exclude_person_ids: set[int] | None = None,
) -> list[tuple[str, str]]:
    excluded = exclude_person_ids or set()
    choices: list[tuple[str, str]] = []
    current_members = (
        household.persons.filter(
            batch=household.batch,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
        )
        .exclude(pk__in=excluded)
        .order_by("kana", "name", "person_uid")
    )
    for person in current_members:
        label = person.name or person.person_uid
        if person.relationship_label:
            label = f"{label} / {person.relationship_label}"
        choices.append((str(person.pk), label))
    return choices


def _apply_household_head_transition_successor(
    *,
    household: Household,
    successor_mode: str,
    successor_person_id: str,
    manual_head_name: str,
    manual_head_name_kana: str,
    editor_label: str,
):
    mode = successor_mode or HouseholdHeadTransitionForm.SUCCESSOR_MODE_KEEP

    before_data = _serialize_household_record(household)
    update_fields: list[str] = []

    if mode == HouseholdHeadTransitionForm.SUCCESSOR_MODE_KEEP:
        successor = household_head_runtime.create_virtual_household_head_person(household)
        update_fields.extend(
            _sync_household_head_snapshot_from_person(
                household=household,
                head_person=successor,
            )
        )
        change_note = f"戸主ブラウザで仮戸主を設定: {successor.name}"
    elif mode == HouseholdHeadTransitionForm.SUCCESSOR_MODE_CURRENT and successor_person_id:
        successor = get_object_or_404(
            Person.objects.filter(
                batch=household.batch,
                household=household,
                deleted_at__isnull=True,
                family_category=FAMILY_CATEGORY_CURRENT,
            ),
            pk=successor_person_id,
        )
        update_fields.extend(
            _sync_household_head_snapshot_from_person(
                household=household,
                head_person=successor,
            )
        )
        change_note = f"戸主ブラウザで次の戸主を現在帳から設定: {successor.name}"
    elif mode == HouseholdHeadTransitionForm.SUCCESSOR_MODE_MANUAL and manual_head_name:
        successor = _create_manual_successor_head_person(
            household=household,
            manual_head_name=manual_head_name,
            manual_head_name_kana=manual_head_name_kana,
        )
        update_fields.extend(
            _sync_household_head_snapshot_from_person(
                household=household,
                head_person=successor,
            )
        )
        change_note = f"戸主ブラウザで次の戸主を手入力で設定: {successor.name}"
    else:
        return None

    update_fields.append("updated_at")
    household.save(update_fields=list(dict.fromkeys(update_fields)))
    household = Household.objects.get(pk=household.pk)
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD,
        record=household,
        before_data=before_data,
        after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note=change_note,
    )


def _prepare_household_head_person_move(household: Household) -> tuple[Person, dict, bool]:
    explicit_head_person = _resolved_household_head_person(household)
    if explicit_head_person is not None:
        if explicit_head_person.person_uid.startswith("head-"):
            explicit_head_person = _normalize_generated_head_person_id(explicit_head_person)
        return explicit_head_person, _serialize_person_record(explicit_head_person), False
    matched_people = _matching_household_head_people(household)
    if len(matched_people) > 1:
        raise ValueError("同名の戸主候補が複数あるため、自動移動できません。家族レコードを手動で確認してください。")
    if matched_people:
        person = matched_people[0]
        if person.person_uid.startswith("head-"):
            person = _normalize_generated_head_person_id(person)
        return person, _serialize_person_record(person), False
    person = _create_household_head_person(household)
    return person, {}, True


def _create_household_head_person(household: Household) -> Person:
    person = household_head_runtime.create_manual_household_head_person_from_snapshot(household)
    if person is None:
        raise ValueError("戸主 snapshot が空のため、manual_household_head を作成できません。")
    household.head_person = person
    household.save(update_fields=["head_person", "updated_at"])
    return person


def _create_manual_successor_head_person(
    *,
    household: Household,
    manual_head_name: str,
    manual_head_name_kana: str,
) -> Person:
    legacy_person_id = _next_household_head_person_id(household)
    normalized_kana = normalize_kana_storage(manual_head_name_kana)
    raw_person_record = {
        "家族ID": legacy_person_id,
        "台帳ID": household.household_uid,
        "氏名": manual_head_name,
        "ﾌﾘｶﾞﾅ": manual_head_name_kana,
        "〒": household.postal_code,
        "住所1": household.address_line1,
        "住所2": household.address_line2,
        "住所3": household.address_line3,
        "電話": household.phone,
        "携帯": household.mobile,
        "Email": household.email,
        "続柄": "",
        "家族区分": FAMILY_CATEGORY_CURRENT,
    }
    return Person.objects.create(
        batch=household.batch,
        household=household,
        legacy_source_id=household.legacy_source_id,
        source_mdb_file=_current_household_source_mdb_file(household),
        source_export_batch=household.source_export_batch,
        source_table="manual_household_head",
        source_row_number=household.source_row_number,
        legacy_pk_text=legacy_person_id,
        person_uid=legacy_person_id,
        legacy_household_id=household.household_uid,
        name=manual_head_name,
        kana=normalized_kana,
        relationship_label="",
        family_category=FAMILY_CATEGORY_CURRENT,
        gender="",
        birth_date_raw="",
        birth_date=None,
        birth_date_parse_error="",
        person_note="",
        is_deceased=False,
        raw_record=raw_person_record,
    )


def _next_household_head_person_id(household: Household) -> str:
    from .household_editing_core import _next_generated_person_id

    return _next_generated_person_id(household.batch)


__all__ = [
    "HouseholdHeadMoveOutcome",
    "_apply_household_head_transition_successor",
    "_create_household_head_person",
    "_create_manual_successor_head_person",
    "_current_household_source_mdb_file",
    "_household_head_successor_choices",
    "_is_virtual_household_head_person",
    "_next_household_head_person_id",
    "_prepare_household_head_person_move",
    "_replace_virtual_household_head",
    "_sync_household_head_person_identity_from_form",
    "_sync_household_head_snapshot_from_person",
    "move_household_head_person",
]
