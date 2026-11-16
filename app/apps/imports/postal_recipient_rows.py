from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Q

from . import canonical_population
from .models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_POSTAL,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)
from .runtime_shared import _clean_value, _int_sort, _normalize_same_name_text, _sort_text


def build_postal_recipient_db_rows(
    source_id: str,
    latest_batch: ImportBatch,
    *,
    canonical_scope: bool = False,
    household_uids: Iterable[str] | None = None,
) -> list[dict]:
    if canonical_scope:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
    selected_household_uids = tuple(
        dict.fromkeys(
            cleaned
            for value in household_uids or ()
            if (cleaned := _clean_value(value))
        )
    )
    profile_queryset = HouseholdProfile.objects.select_related("district").filter(
        source__source_id=source_id
    )
    if selected_household_uids:
        profile_queryset = profile_queryset.filter(
            household_uid__in=selected_household_uids,
        )
    else:
        profile_queryset = profile_queryset.filter(
            Q(delivery_method=HOUSEHOLD_DELIVERY_POSTAL)
            | Q(
                delivery_method=HOUSEHOLD_DELIVERY_DISTRICT,
                district__is_active=False,
            )
        )
    profiles = list(
        profile_queryset.order_by("household_uid", "id")
    )
    household_queryset = Household.objects.select_related("head_person").filter(
        deleted_at__isnull=True,
    )
    if not canonical_scope:
        household_queryset = household_queryset.filter(batch=latest_batch)
    households = {household.household_uid: household for household in household_queryset}
    household_ids = list(households.keys())
    person_queryset = Person.objects.select_related("household").filter(
        deleted_at__isnull=True,
        household__household_uid__in=household_ids,
    )
    if not canonical_scope:
        person_queryset = person_queryset.filter(batch=latest_batch)
    people = {
        (person.household.household_uid, person.person_uid): person
        for person in person_queryset
    }

    rows: list[dict] = []
    for profile in profiles:
        household = households.get(profile.household_uid)
        if household is None:
            continue
        head_name = household.display_head_name()
        mailing_person = None
        if profile.mailing_person_uid:
            mailing_person = people.get(
                (profile.household_uid, profile.mailing_person_uid)
            )
        recipient_name = (
            _clean_value(mailing_person.name if mailing_person is not None else "")
            or _clean_value(profile.mailing_name)
            or head_name
        )
        recipient_kana = _clean_value(
            mailing_person.kana if mailing_person is not None else ""
        ) or _clean_value(household.display_head_name_kana())
        rows.append(
            {
                "entry_id": f"db:{household.household_uid}",
                "household_id": household.household_uid,
                "household_name": head_name,
                "ledger_category": household.ledger_category,
                "recipient_name": recipient_name,
                "recipient_kana": recipient_kana,
                "recipient_role_label": (
                    "別郵送先"
                    if _normalize_same_name_text(recipient_name)
                    != _normalize_same_name_text(head_name)
                    else "戸主宛"
                ),
                "postal_code": _clean_value(profile.mailing_postal_code)
                or _clean_value(household.postal_code),
                "address_line1": _clean_value(profile.mailing_address_line1)
                or _clean_value(household.address_line1),
                "address_line2": _clean_value(profile.mailing_address_line2)
                or _clean_value(household.address_line2),
                "phone": _clean_value(profile.mailing_phone) or _clean_value(household.phone),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            _sort_text(item.get("recipient_name")),
            _sort_text(item.get("household_name")),
            _int_sort(item.get("household_id")),
        ),
    )


__all__ = ["build_postal_recipient_db_rows"]
