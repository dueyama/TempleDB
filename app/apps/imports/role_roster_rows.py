from __future__ import annotations

from apps.core.services.role_badges import role_badges_for_person

from .models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    HouseholdProfile,
    Person,
)
from .runtime_shared import _clean_value


def build_person_role_roster_rows(source_id: str, people: list[Person]) -> list[dict]:
    household_ids = [
        person.household.household_uid
        for person in people
        if _clean_value(person.household.household_uid)
    ]
    profile_map = {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.select_related("district").filter(
            source__source_id=source_id,
            household_uid__in=household_ids,
        )
    }
    rows: list[dict] = []
    for person in people:
        household = person.household
        profile = profile_map.get(person.household.household_uid)
        address_lines = []
        if household is not None:
            address_lines = [
                line
                for line in [
                    _clean_value(household.address_line1),
                    _clean_value(household.address_line2),
                    _clean_value(household.address_line3),
                ]
                if line
            ]
        rows.append(
            {
                "person_pk": person.pk,
                "person_name": _clean_value(person.name) or person.person_uid,
                "person_id": person.person_uid,
                "household_id": person.household.household_uid,
                "household_name": household.display_head_name() if household is not None else "",
                "postal_code": _clean_value(household.postal_code if household is not None else ""),
                "address_lines": address_lines,
                "phone": _clean_value(household.phone if household is not None else ""),
                "delivery_method": HOUSEHOLD_DELIVERY_LABELS.get(
                    _clean_value(profile.delivery_method if profile is not None else ""),
                    "未設定",
                ),
                "home_district_name": profile.district.name if profile is not None and profile.district_id else "",
                "home_district_is_inactive": bool(
                    profile is not None
                    and profile.district_id
                    and not profile.district.is_active
                ),
                "assigned_district_names": (
                    [profile.district.name]
                    if (
                        person.is_district_officer
                        and profile is not None
                        and profile.delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
                        and profile.district_id
                    )
                    else []
                ),
                "role_badges": role_badges_for_person(person),
            }
        )
    return rows


__all__ = ["build_person_role_roster_rows"]
