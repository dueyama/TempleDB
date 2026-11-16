from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import DeceasedProfile, Person


def person_has_memorial_details(person: Person) -> bool:
    return any(
        (
            person.death_date,
            person.death_date_raw,
            person.kaimyo,
            person.kaimyo_kana,
            person.age_at_death_raw,
            person.age_at_death is not None,
            person.deceased_note,
            person.hatsubon_flag is True,
            person.memorial_notice_opt_out is True,
            bool(person.memorial_payload),
        )
    )


def clear_person_memorial_fields(person: Person) -> None:
    person.death_date_raw = ""
    person.death_date = None
    person.death_date_parse_error = ""
    person.kaimyo = ""
    person.kaimyo_kana = ""
    person.age_at_death_raw = ""
    person.age_at_death = None
    person.age_unit = ""
    person.legacy_hatsubon_flag = ""
    person.hatsubon_flag = None
    person.memorial_notice_opt_out = None
    person.deceased_note = ""
    person.memorial_payload = {}


def sync_person_legacy_deceased_profile(person: Person) -> None:
    profile = getattr(person, "deceased_profile", None)
    has_profile_data = person.is_deceased or person_has_memorial_details(person)
    if not has_profile_data:
        if profile is not None:
            profile.delete()
        return
    if profile is None:
        profile_model = person._meta.apps.get_model("imports", "DeceasedProfile")
        profile = profile_model(person=person)
    profile.death_date_raw = person.death_date_raw
    profile.death_date = person.death_date
    profile.death_date_parse_error = person.death_date_parse_error
    profile.kaimyo = person.kaimyo
    profile.kaimyo_kana = person.kaimyo_kana
    profile.age_at_death_raw = person.age_at_death_raw
    profile.age_at_death = person.age_at_death
    profile.age_unit = person.age_unit
    profile.legacy_hatsubon_flag = person.legacy_hatsubon_flag
    profile.hatsubon_flag = person.hatsubon_flag
    profile.memorial_notice_opt_out = person.memorial_notice_opt_out
    profile.deceased_note = person.deceased_note
    profile.memorial_payload = person.memorial_payload or {}
    profile.save()


def save_deceased_profile(profile: DeceasedProfile, *args: Any, **kwargs: Any):
    result = super(profile.__class__, profile).save(*args, **kwargs)
    person_model = profile._meta.apps.get_model("imports", "Person")
    person_model.objects.filter(pk=profile.person_id).update(
        death_date_raw=profile.death_date_raw,
        death_date=profile.death_date,
        death_date_parse_error=profile.death_date_parse_error,
        kaimyo=profile.kaimyo,
        kaimyo_kana=profile.kaimyo_kana,
        age_at_death_raw=profile.age_at_death_raw,
        age_at_death=profile.age_at_death,
        age_unit=profile.age_unit,
        legacy_hatsubon_flag=profile.legacy_hatsubon_flag,
        hatsubon_flag=profile.hatsubon_flag,
        memorial_notice_opt_out=profile.memorial_notice_opt_out,
        deceased_note=profile.deceased_note,
        memorial_payload=profile.memorial_payload or {},
    )
    if hasattr(profile, "person") and profile.person is not None:
        profile.person.death_date_raw = profile.death_date_raw
        profile.person.death_date = profile.death_date
        profile.person.death_date_parse_error = profile.death_date_parse_error
        profile.person.kaimyo = profile.kaimyo
        profile.person.kaimyo_kana = profile.kaimyo_kana
        profile.person.age_at_death_raw = profile.age_at_death_raw
        profile.person.age_at_death = profile.age_at_death
        profile.person.age_unit = profile.age_unit
        profile.person.legacy_hatsubon_flag = profile.legacy_hatsubon_flag
        profile.person.hatsubon_flag = profile.hatsubon_flag
        profile.person.memorial_notice_opt_out = profile.memorial_notice_opt_out
        profile.person.deceased_note = profile.deceased_note
        profile.person.memorial_payload = profile.memorial_payload or {}
    return result


def delete_deceased_profile(profile: DeceasedProfile, *args: Any, **kwargs: Any):
    person_model = profile._meta.apps.get_model("imports", "Person")
    person_model.objects.filter(pk=profile.person_id).update(
        death_date_raw="",
        death_date=None,
        death_date_parse_error="",
        kaimyo="",
        kaimyo_kana="",
        age_at_death_raw="",
        age_at_death=None,
        age_unit="",
        legacy_hatsubon_flag="",
        hatsubon_flag=None,
        memorial_notice_opt_out=None,
        deceased_note="",
        memorial_payload={},
    )
    if hasattr(profile, "person") and profile.person is not None:
        clear_person_memorial_fields(profile.person)
    return super(profile.__class__, profile).delete(*args, **kwargs)
