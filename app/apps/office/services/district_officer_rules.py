"""Read-only eligibility and in-transaction restoration rules for district roles."""
from __future__ import annotations

from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    HouseholdProfile,
    Person,
)


def district_profile_for_person(source_id: str, person: Person) -> HouseholdProfile | None:
    return (
        HouseholdProfile.objects.select_related("district")
        .filter(source__source_id=source_id, household_uid=person.household.household_uid)
        .first()
    )


def person_can_be_district_officer(source_id: str, person: Person) -> bool:
    if person.deleted_at is not None or person.family_category != FAMILY_CATEGORY_CURRENT:
        return False
    profile = district_profile_for_person(source_id, person)
    return bool(
        profile is not None
        and profile.delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
        and profile.district_id is not None
    )


def reconcile_restored_district_officer(person: Person) -> str:
    """Adjust the unsaved restored person; the caller owns save and audit atomically.

    A current incumbent is never displaced by restoring an old person. The
    caller holds the Household lock shared with delivery edits before refreshing
    the Person/profile. The district lock is shared with explicit appointments.
    Other role flags are independent and remain unchanged.
    """
    if not person.is_district_officer:
        return ""
    source_id = person.batch.source.source_id
    profile = district_profile_for_person(source_id, person)
    if (
        person.family_category != FAMILY_CATEGORY_CURRENT
        or person.household.deleted_at is not None
        or profile is None
        or profile.delivery_method != HOUSEHOLD_DELIVERY_DISTRICT
        or profile.district_id is None
    ):
        person.is_district_officer = False
        return "現在は地区役員の対象外のため、人物のみ復元し、地区役員を解除しました。"

    District.objects.select_for_update().get(pk=profile.district_id)
    household_uids = HouseholdProfile.objects.filter(
        source_id=profile.source_id,
        district_id=profile.district_id,
        delivery_method=HOUSEHOLD_DELIVERY_DISTRICT,
    ).values_list("household_uid", flat=True)
    incumbent = (
        Person.objects.filter(
            household__household_uid__in=household_uids,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_district_officer=True,
        )
        .exclude(pk=person.pk)
        .order_by("person_uid", "pk")
        .first()
    )
    if incumbent is None:
        return ""
    person.is_district_officer = False
    return (
        f"{profile.district.name}には現在の地区役員（{incumbent.name or incumbent.person_uid}）"
        "がいるため、人物のみ復元し、旧地区役員を解除しました。"
    )
