from __future__ import annotations

from apps.core.services.role_badges import role_badges_for_person

from . import browser_dataset_display, household_profile_runtime, runtime_shared
from .ledger_categories import ledger_category_label
from .model_households import safe_display_head_name, safe_display_head_name_kana
from .models import Household, HouseholdProfile, Person

_same_name_household_delivery_label = browser_dataset_display._same_name_household_delivery_label
_same_name_household_yuen_label = browser_dataset_display._same_name_household_yuen_label


def _household_row_from_model(
    household: Household,
    profile: HouseholdProfile | None = None,
) -> dict[str, object]:
    raw_record = runtime_shared._clean_row_record(household.raw_record)
    row = dict(raw_record)
    head_person = household.head_person if household.head_person_id else None
    row["__head_person_legacy_person_id"] = head_person.person_uid if head_person is not None else ""
    row["__head_person_role_badges"] = (
        role_badges_for_person(head_person) if head_person is not None else []
    )
    row["__household_profile_general_notice_opt_out"] = (
        ""
        if profile is None or profile.general_notice_opt_out is None
        else ("true" if profile.general_notice_opt_out else "false")
    )
    row["__household_profile_memorial_notice_opt_out"] = (
        ""
        if profile is None or profile.memorial_notice_opt_out is None
        else ("true" if profile.memorial_notice_opt_out else "false")
    )
    row["__household_profile_delivery_label"] = _same_name_household_delivery_label(
        profile.delivery_method if profile is not None else "",
        profile.district.name if profile is not None and profile.district_id else "",
    )
    row["__household_yuen_label"] = _same_name_household_yuen_label(
        household.source_table,
        household.snapshot_head_name(),
    )
    row["台帳ID"] = household.household_uid
    row["氏名"] = safe_display_head_name(household)
    row["ﾌﾘｶﾞﾅ"] = safe_display_head_name_kana(household)
    row["〒"] = household.postal_code
    row["住所1"] = household.address_line1
    row["住所2"] = household.address_line2
    row["住所3"] = household.address_line3
    row["電話"] = household.phone
    row["ＦＡＸ"] = household.fax
    row["携帯"] = household.mobile
    row["Email"] = household.email
    row["世話人ID"] = household.steward_legacy_id
    row["台帳区分"] = ledger_category_label(household.ledger_category)
    row["案内要否"] = household_profile_runtime._household_general_notice_display_value(
        profile_value=profile.general_notice_opt_out if profile is not None else None
    )
    row["年回要否"] = household_profile_runtime._household_memorial_notice_display_value(
        profile_value=profile.memorial_notice_opt_out if profile is not None else None,
        raw_value=None,
    )
    row["備考"] = household.notes
    if head_person is not None:
        row["かな補完"] = "自動" if head_person.kana_is_auto_generated else ""
        row["性別"] = head_person.gender or row.get("性別", "")
        row["生年月日"] = (
            head_person.birth_date.isoformat()
            if head_person.birth_date is not None
            else head_person.birth_date_raw or row.get("生年月日", "")
        )
        row["続柄"] = head_person.relationship_label or ""
    row["__raw_record"] = raw_record
    return row


def _person_row_from_model(person: Person) -> dict[str, str]:
    raw_record = runtime_shared._clean_row_record(person.raw_record)
    row = dict(raw_record)
    row["家族ID"] = person.person_uid
    row["台帳ID"] = person.household.household_uid
    row["氏名"] = person.name
    row["ﾌﾘｶﾞﾅ"] = person.kana
    row["続柄"] = person.relationship_label
    row["家族区分"] = person.family_category
    row["性別"] = person.gender
    row["生年月日"] = person.birth_date_raw or (person.birth_date.isoformat() if person.birth_date else "")
    row["個人備考"] = person.person_note
    row["かな補完"] = "自動" if person.kana_is_auto_generated else ""
    row["__kana_is_auto_generated"] = "true" if person.kana_is_auto_generated else ""
    if person.has_memorial_details():
        row["命日"] = person.death_date_raw or (person.death_date.isoformat() if person.death_date else "")
        row["戒名"] = person.kaimyo
        row["享年"] = person.age_at_death_raw or (str(person.age_at_death) if person.age_at_death is not None else "")
        row["享年単位"] = person.age_unit
        row["初盆"] = household_profile_runtime._legacy_bool_value(
            person.hatsubon_flag,
            person.legacy_hatsubon_flag,
        )
        row["年回案内不要"] = household_profile_runtime._legacy_bool_value(person.memorial_notice_opt_out)
        row["故人備考"] = person.deceased_note
    row["__raw_record"] = raw_record
    return row
