from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .kana import normalize_kana_for_match, normalize_kana_storage

if TYPE_CHECKING:
    from .models import Household, HouseholdProfile, Person


def resolve_household_for_profile(profile: HouseholdProfile) -> Household | None:
    if not profile.household_uid:
        return None
    try:
        from . import canonical_population

        canonical_population.canonical_provenance_import_batch(
            source_id=profile.source.source_id,
        )
        household_model = profile._meta.apps.get_model("imports", "Household")
        return (
            household_model.objects.filter(
                household_uid=profile.household_uid,
                deleted_at__isnull=True,
            )
            .select_related("head_person")
            .first()
        )
    except canonical_population.CanonicalPopulationConflict:
        raise
    except Exception:
        return None


def household_name_snapshot(profile: HouseholdProfile) -> str:
    household = resolve_household_for_profile(profile)
    if household is not None:
        return household.display_head_name()
    return getattr(profile, "_household_name_snapshot_override", "") or profile.household_uid


def set_household_name_snapshot(profile: HouseholdProfile, value: str | None) -> None:
    profile._household_name_snapshot_override = (value or "").strip()


def household_name_kana_snapshot(profile: HouseholdProfile) -> str:
    household = resolve_household_for_profile(profile)
    if household is not None:
        return household.display_head_name_kana()
    return getattr(profile, "_household_name_kana_snapshot_override", "")


def set_household_name_kana_snapshot(profile: HouseholdProfile, value: str | None) -> None:
    profile._household_name_kana_snapshot_override = normalize_kana_storage(value or "")


def normalize_head_name_identity(value: str | None) -> str:
    return "".join(str(value or "").strip().replace(" ", "").replace("\u3000", "").split())


def normalize_head_kana_identity(value: str | None) -> str:
    return normalize_kana_for_match(value)


def snapshot_head_name(household: Household) -> str:
    raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
    if hasattr(household, "_head_name_override"):
        return str(household._head_name_override or "").strip()
    return str(raw_record.get("氏名") or "").strip()


def snapshot_head_name_kana(household: Household) -> str:
    raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
    if hasattr(household, "_head_name_kana_override"):
        return str(household._head_name_kana_override or "").strip()
    return str(raw_record.get("ﾌﾘｶﾞﾅ") or "").strip()


def resolved_head_name(household: Household) -> str:
    head_person = require_head_person(household)
    return (head_person.name or "").strip() or household.household_uid


def resolved_head_name_kana(household: Household) -> str:
    head_person = require_head_person(household)
    return (head_person.kana or "").strip()


def resolve_head_person(household: Household) -> Person | None:
    if household.head_person_id:
        head_person = getattr(household, "head_person", None)
        if head_person is not None and head_person.deleted_at is None:
            return head_person
    head_name = normalize_head_name_identity(snapshot_head_name(household))
    if not head_name:
        return None
    head_kana = normalize_head_kana_identity(snapshot_head_name_kana(household))
    candidates = list(
        household.persons.filter(deleted_at__isnull=True).order_by("person_uid", "id")
    )
    exact_name_matches = [
        person for person in candidates if normalize_head_name_identity(person.name) == head_name
    ]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1 and head_kana:
        kana_matches = [
            person
            for person in exact_name_matches
            if normalize_head_kana_identity(person.kana) == head_kana
        ]
        if len(kana_matches) == 1:
            return kana_matches[0]
    return None


def require_head_person(household: Household) -> Person:
    head_person = resolve_head_person(household)
    if head_person is not None:
        return head_person
    error_cls = _household_head_resolution_error_cls(household)
    raise error_cls(
        "Household head_person is unresolved "
        f"(legacy_household_id={household.household_uid}, "
        f"snapshot_head_name={snapshot_head_name(household)!r}, "
        f"snapshot_head_name_kana={snapshot_head_name_kana(household)!r})"
    )


def _household_head_resolution_error_cls(household: Household):
    models_module = import_module(household.__class__.__module__)
    return models_module.HouseholdHeadResolutionError


def display_head_name(household: Household) -> str:
    return resolved_head_name(household)


def display_head_name_kana(household: Household) -> str:
    return resolved_head_name_kana(household)


def safe_display_head_name(household: Household | None) -> str:
    if household is None:
        return ""
    error_cls = _household_head_resolution_error_cls(household)
    try:
        return display_head_name(household)
    except error_cls:
        return snapshot_head_name(household) or household.household_uid or ""


def bulk_safe_display_head_name(
    household: Household,
    active_people: list[Person],
) -> str:
    head_person = household.head_person if household.head_person_id else None
    if head_person is not None and head_person.deleted_at is None:
        return (head_person.name or "").strip() or household.household_uid

    snapshot_name = snapshot_head_name(household)
    normalized_name = normalize_head_name_identity(snapshot_name)
    if normalized_name:
        exact_name_matches = [
            person
            for person in active_people
            if normalize_head_name_identity(person.name) == normalized_name
        ]
        if len(exact_name_matches) == 1:
            return (exact_name_matches[0].name or "").strip() or household.household_uid
        if len(exact_name_matches) > 1:
            normalized_kana = normalize_head_kana_identity(
                snapshot_head_name_kana(household)
            )
            if normalized_kana:
                kana_matches = [
                    person
                    for person in exact_name_matches
                    if normalize_head_kana_identity(person.kana) == normalized_kana
                ]
                if len(kana_matches) == 1:
                    return (kana_matches[0].name or "").strip() or household.household_uid
    return snapshot_name or household.household_uid


def safe_display_head_name_kana(household: Household | None) -> str:
    if household is None:
        return ""
    error_cls = _household_head_resolution_error_cls(household)
    try:
        return display_head_name_kana(household)
    except error_cls:
        return snapshot_head_name_kana(household) or ""


def household_save(household: Household, *args: Any, **kwargs: Any):
    update_fields = kwargs.get("update_fields")
    has_head_override = hasattr(household, "_head_name_override")
    has_head_kana_override = hasattr(household, "_head_name_kana_override")
    raw_record = dict(household.raw_record) if isinstance(household.raw_record, dict) else {}
    if has_head_override:
        raw_record["氏名"] = household._head_name_override
    if has_head_kana_override:
        raw_record["ﾌﾘｶﾞﾅ"] = household._head_name_kana_override
    household.raw_record = raw_record
    if update_fields is not None:
        normalized_update_fields = list(dict.fromkeys(update_fields))
        translated_update_fields: list[str] = []
        for field_name in normalized_update_fields:
            if field_name in {"head_name", "head_name_kana"}:
                field_name = "raw_record"
            translated_update_fields.append(field_name)
        if (has_head_override or has_head_kana_override) and "raw_record" not in translated_update_fields:
            translated_update_fields.append("raw_record")
        kwargs["update_fields"] = list(dict.fromkeys(translated_update_fields))
    result = super(household.__class__, household).save(*args, **kwargs)
    if hasattr(household, "_head_name_override"):
        delattr(household, "_head_name_override")
    if hasattr(household, "_head_name_kana_override"):
        delattr(household, "_head_name_kana_override")
    return result


def household_refresh_from_db(
    household: Household,
    *,
    using: str | None = None,
    fields: list[str] | tuple[str, ...] | None = None,
    from_queryset: Any = None,
):
    if hasattr(household, "_head_name_override"):
        delattr(household, "_head_name_override")
    if hasattr(household, "_head_name_kana_override"):
        delattr(household, "_head_name_kana_override")
    return super(household.__class__, household).refresh_from_db(
        using=using,
        fields=fields,
        from_queryset=from_queryset,
    )
