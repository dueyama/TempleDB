from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.imports.forms import GENDER_CHOICES
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_CHOICES,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    Household,
    HouseholdProfile,
    RecordEditLog,
)

from . import district_authority
from .household_editing_core import (
    _matching_household_head_people,
    _person_for_edit,
    _resolved_household_head_person,
)


def _household_profile_initial_values(source_id: str, household_id: str) -> tuple[str, str, bool, bool]:
    profile = (
        HouseholdProfile.objects.select_related("district")
        .filter(source__source_id=source_id, household_uid=household_id)
        .first()
    )
    if profile is None:
        return "", "", False, False
    return (
        profile.delivery_method or "",
        str(profile.district_id) if profile.district_id else "",
        bool(profile.general_notice_opt_out),
        bool(profile.memorial_notice_opt_out),
    )


def _resolved_household_general_notice_opt_out(
    *,
    source_id: str,
    household,
) -> bool:
    profile = (
        HouseholdProfile.objects.filter(
            source__source_id=source_id,
            household_uid=household.household_uid,
        ).first()
    )
    return bool(profile.general_notice_opt_out) if profile is not None else False


def _resolved_household_memorial_notice_opt_out(
    *,
    source_id: str,
    household,
) -> bool:
    profile = (
        HouseholdProfile.objects.filter(
            source__source_id=source_id,
            household_uid=household.household_uid,
        ).first()
    )
    return bool(profile.memorial_notice_opt_out) if profile is not None else False


def _household_profile_has_state(profile: HouseholdProfile) -> bool:
    return bool(
        profile.delivery_method
        or profile.district_id
        or profile.mailing_person_uid
        or profile.mailing_name
        or profile.mailing_postal_code
        or profile.mailing_address_line1
        or profile.mailing_address_line2
        or profile.mailing_phone
        or profile.general_notice_opt_out is not None
        or profile.memorial_notice_opt_out is not None
    )


def _household_head_person_candidates(household) -> list:
    try:
        return _matching_household_head_people(household)
    except ValueError:
        return []


def _resolved_household_head_gender(household) -> str:
    head_person = _resolved_household_head_person(household)
    if head_person is not None:
        return (head_person.gender or "").strip()
    return ""


@transaction.atomic
def _apply_household_delivery_profile_from_form(
    *,
    source_record,
    household,
    delivery_method: str,
    district_id: str,
    general_notice_opt_out: bool | None,
    memorial_notice_opt_out: bool | None,
    editor_label: str = "",
    change_note: str = "",
) -> None:
    # Serialize delivery changes with Person restoration before reading profile/roles.
    household = Household.objects.select_for_update(of=("self",)).get(pk=household.pk)
    profile = HouseholdProfile.objects.filter(
        source=source_record,
        household_uid=household.household_uid,
    ).first()
    previous_delivery_method = profile.delivery_method if profile is not None else ""
    previous_district_id = profile.district_id if profile is not None else None
    if profile is None:
        profile = HouseholdProfile(
            source=source_record,
            household_uid=household.household_uid,
        )
    district = None
    if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
        district = get_object_or_404(District, pk=district_id)
    new_district_id = district.id if district is not None else None
    if (
        delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
        or previous_delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
        or previous_district_id != new_district_id
    ):
        district_authority.clear_district_officer_flags_for_household(
            source_record.source_id, household,
            editor_label=editor_label,
            change_note=change_note or "戸主の送付区分・地区変更に伴う地区役員解除",
        )
    profile.delivery_method = delivery_method
    profile.district = district
    profile.general_notice_opt_out = (
        bool(general_notice_opt_out) if general_notice_opt_out is not None else None
    )
    profile.memorial_notice_opt_out = (
        bool(memorial_notice_opt_out) if memorial_notice_opt_out is not None else None
    )
    if _household_profile_has_state(profile):
        profile.save()
    elif profile.pk:
        profile.delete()


def _apply_household_head_gender_from_form(
    *,
    household,
    head_gender: str,
    editor_label: str,
    change_note: str,
) -> None:
    from .record_history_mutations import _create_record_edit_log
    from .record_history_snapshot import _serialize_person_record

    normalized_gender = head_gender if head_gender in {choice[0] for choice in GENDER_CHOICES} else "未決定"
    person = _resolved_household_head_person(household)
    if person is None:
        return
    before_data = _serialize_person_record(person)
    person.gender = normalized_gender
    person.save(update_fields=["gender", "updated_at"])
    person = _person_for_edit(person.pk)
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=person,
        before_data=before_data,
        after_data=_serialize_person_record(person),
        editor_label=editor_label,
        change_note=change_note,
    )


def _attach_household_browser_edit_context(context: dict) -> None:
    detail = context.get("detail")
    if not detail:
        return
    selected_source_id = context.get("selected_source_id", "")
    data_backend = context.get("data_backend")
    if data_backend != "db":
        return
    household_id = detail.get("summary", {}).get("household_id", "")
    profile = (
        HouseholdProfile.objects.select_related("district")
        .filter(source__source_id=selected_source_id, household_uid=household_id)
        .first()
    )
    delivery_method = profile.delivery_method if profile is not None else ""
    district_id = str(profile.district_id) if profile is not None and profile.district_id else ""
    detail["district_assignment"] = {
        "delivery_method": delivery_method,
        "district_id": district_id,
    }
    detail["delivery_choices"] = [
        {"value": value, "label": label, "selected": value == delivery_method}
        for value, label in HOUSEHOLD_DELIVERY_CHOICES
    ]
    detail["district_choices"] = [
        {"value": "", "label": "地区を選択", "selected": district_id == ""}
    ] + [
        {"value": str(district.pk), "label": district.name, "selected": str(district.pk) == district_id}
        for district in District.objects.order_by("sort_order", "name")
    ]
    detail["current_members"] = [
        _attach_person_gender_state(member) for member in detail.get("current_members", [])
    ]
    detail["memorial_members"] = [
        _attach_person_gender_state(member) for member in detail.get("memorial_members", [])
    ]


def _attach_person_gender_state(member: dict) -> dict:
    gender_value = _member_gender_value(member)
    return {
        **member,
        "gender_value": gender_value,
        "gender_label": gender_value or "未決定",
    }


def _member_gender_value(member: dict) -> str:
    for field in member.get("display_fields", []):
        if field.get("label") == "性別":
            cleaned = (field.get("value") or "").strip()
            return cleaned or "未決定"
    raw_gender = str(member.get("gender") or "").strip()
    return raw_gender or "未決定"
