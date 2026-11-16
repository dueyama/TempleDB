"""Replace a household head from a reviewed delivery or postal roster row.

The person, delivery profile, audit records, and review resolution are one save.
Roster-specific person creation and district authority remain with their owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db import transaction

from apps.imports.household_head_snapshot import sync_household_head_snapshot_from_person
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_POSTAL,
    HandDeliveryReviewResolution,
    Household,
    HouseholdProfile,
    LegacySource,
    Person,
    PostalReviewResolution,
    RecordEditLog,
)

from .auxiliary_hand_delivery_households import _replace_household_head_from_hand_delivery_entry
from .auxiliary_postal_households import _replace_household_head_from_postal_entry
from .district_authority import (
    clear_district_officer_flag_for_person,
    clear_district_officer_flags_for_household,
)
from .district_ops import (
    _assign_district_officer_to_person,
    _ensure_district_from_hand_delivery_entry,
)
from .household_editing_core import (
    _apply_household_contact_defaults_to_person,
    _resolved_household_head_person,
)
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_household_record, _serialize_person_record

ReviewKind = Literal["hand_delivery", "postal"]


@dataclass(frozen=True)
class HeadReplacementResult:
    replacement_person: Person
    person_log: RecordEditLog | None
    old_head_log: RecordEditLog | None
    household_log: RecordEditLog | None


def _retire_previous_head(
    *, source_id: str, person: Person | None, replacement: Person,
    keep_current: bool, roster_label: str, editor_label: str,
) -> RecordEditLog | None:
    if (
        person is None
        or person.pk == replacement.pk
        or person.family_category != FAMILY_CATEGORY_CURRENT
    ):
        return None
    if not keep_current:
        clear_district_officer_flag_for_person(
            source_id, person, editor_label=editor_label,
            change_note=f"{roster_label}の戸主差し替えに伴う旧戸主の地区役員解除",
        )
    # The role removal has its own preceding audit entry.
    before = _serialize_person_record(person)
    if keep_current:
        note = f"{roster_label}の戸主差し替えで旧戸主を現在帳へ残す"
        person.relationship_label = ""
        person.save(update_fields=["relationship_label", "updated_at"])
    else:
        note = f"{roster_label}の戸主差し替えで旧戸主 current person を退避"
        person.mark_deleted(editor_label=editor_label, note=note)
        person.save(update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"])
    return _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON, record=person,
        before_data=before, after_data=_serialize_person_record(person),
        editor_label=editor_label, change_note=note,
    )


def _save_head_and_contacts(household: Household, replacement: Person, entry: dict) -> None:
    updates = sync_household_head_snapshot_from_person(
        household=household, head_person=replacement,
    )
    raw = dict(household.raw_record or {})
    contacts = {"postal_code": "〒", "address_line1": "住所1", "address_line2": "住所2", "phone": "電話"}
    for field, raw_key in contacts.items():
        setattr(household, field, entry[field])
        raw[raw_key] = entry[field]
    household.raw_record = raw
    household.save(update_fields=[*updates, *contacts, "raw_record", "updated_at"])
    _apply_household_contact_defaults_to_person(replacement, household)
    replacement.save(update_fields=["name", "kana", "family_category", "is_deceased", "raw_record", "updated_at"])


def _save_delivery_profile(
    *, source: LegacySource, household: Household, replacement: Person,
    entry: dict, folder_name: str, review_kind: ReviewKind, editor_label: str,
) -> None:
    if review_kind == "hand_delivery":
        district = _ensure_district_from_hand_delivery_entry(
            entry, source_id=source.source_id, editor_label=editor_label,
            change_note=f"手配り名簿 {folder_name} の戸主差替に伴う地区情報",
        )
        previous_profile = HouseholdProfile.objects.filter(
            source=source, household_uid=household.household_uid,
        ).first()
        if previous_profile is not None and (
            previous_profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
            or previous_profile.district_id != district.pk
        ):
            clear_district_officer_flags_for_household(
                source.source_id, household, editor_label=editor_label,
                change_note="手配り名簿の戸主差し替えに伴う地区変更",
            )
            replacement.refresh_from_db()
        delivery_method = HOUSEHOLD_DELIVERY_DISTRICT
    else:
        clear_district_officer_flags_for_household(
            source.source_id, household, editor_label=editor_label,
            change_note="郵送名簿の戸主差し替えに伴う地区役員解除",
        )
        district = None
        delivery_method = HOUSEHOLD_DELIVERY_POSTAL
    HouseholdProfile.objects.update_or_create(
        source=source, household_uid=household.household_uid,
        defaults={
            "delivery_method": delivery_method,
            "district": district,
            "household_name_snapshot": household.display_head_name(),
            "household_name_kana_snapshot": household.display_head_name_kana(),
        },
    )
    if review_kind == "hand_delivery" and entry.get("is_officer"):
        _assign_district_officer_to_person(
            district, replacement, editor_label=editor_label,
            change_note="手配り名簿の戸主差し替えに伴う地区役員設定",
        )


@transaction.atomic
def replace_review_household_head(
    *, source: LegacySource, household: Household, entry: dict,
    folder_name: str, row_number: int, review_kind: ReviewKind,
    editor_label: str, keep_old_head_current: bool = False,
) -> HeadReplacementResult:
    if review_kind == "hand_delivery":
        roster_label = "手配り名簿"
        replace_person = _replace_household_head_from_hand_delivery_entry
        resolution_model = HandDeliveryReviewResolution
    elif review_kind == "postal":
        roster_label = "郵送名簿"
        replace_person = _replace_household_head_from_postal_entry
        resolution_model = PostalReviewResolution
    else:
        raise ValueError(f"Unknown head replacement review kind: {review_kind}")

    before_household = _serialize_household_record(household)
    old_head = _resolved_household_head_person(household)
    replacement, before_person, created = replace_person(household=household, entry=entry)
    old_head_log = _retire_previous_head(
        source_id=source.source_id, person=old_head, replacement=replacement,
        keep_current=keep_old_head_current, roster_label=roster_label, editor_label=editor_label,
    )
    _save_head_and_contacts(household, replacement, entry)
    created_note = "（新規 person 作成）" if created else ""
    keep_note = "（旧戸主は現在帳へ残す）" if keep_old_head_current else ""
    person_log = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON, record=replacement,
        before_data=before_person, after_data=_serialize_person_record(replacement),
        editor_label=editor_label,
        change_note=f"{roster_label} {entry['head_name']} を戸主 person として設定{created_note}",
    )
    _save_delivery_profile(
        source=source, household=household, replacement=replacement, entry=entry,
        folder_name=folder_name, review_kind=review_kind, editor_label=editor_label,
    )
    household_log = _create_record_edit_log(
        record_type=RecordEditLog.RecordType.HOUSEHOLD, record=household,
        before_data=before_household, after_data=_serialize_household_record(household),
        editor_label=editor_label,
        change_note=f"{roster_label} {entry['head_name']} を戸主へ差し替え{keep_note}{created_note}",
    )
    resolution_model.objects.update_or_create(
        source=source, folder_name=folder_name, row_number=row_number,
        defaults={
            "resolution_kind": resolution_model.ResolutionKind.REPLACE_HEAD,
            "selected_household_uid": household.household_uid,
            "entry_head_name": entry["head_name"],
            "target_household_name_snapshot": household.display_head_name(),
            "editor_label": editor_label,
            "note": f"台帳ID {household.household_uid} の戸主を {replacement.name} に差し替え{keep_note}",
        },
    )
    return HeadReplacementResult(replacement, person_log, old_head_log, household_log)
