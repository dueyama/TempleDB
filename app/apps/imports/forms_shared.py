from __future__ import annotations

from datetime import time

from .models import OfferingPayment, Person

NULLABLE_BOOL_CHOICES = (
    ("", "未設定"),
    ("true", "はい"),
    ("false", "いいえ"),
)
GENDER_CHOICES = (
    ("未決定", "未決定"),
    ("男", "男"),
    ("女", "女"),
    ("不明", "不明"),
)
HALF_HOUR_TIME_CHOICES = [("", "---------")] + [
    (f"{hour:02d}:{minute:02d}", f"{hour:02d}:{minute:02d}")
    for hour in range(24)
    for minute in (0, 30)
]


PAYMENT_CATEGORY_CHOICES = [
    (OfferingPayment.Category.OFFERING, OfferingPayment.Category.OFFERING.label),
    (OfferingPayment.Category.EITAIKYO, OfferingPayment.Category.EITAIKYO.label),
    (OfferingPayment.Category.OZENRYO, OfferingPayment.Category.OZENRYO.label),
    (OfferingPayment.Category.KURUMADAI, OfferingPayment.Category.KURUMADAI.label),
    (OfferingPayment.Category.HANADAI, OfferingPayment.Category.HANADAI.label),
    (OfferingPayment.Category.NOKOTSUDAN, OfferingPayment.Category.NOKOTSUDAN.label),
    (OfferingPayment.Category.OTHER, OfferingPayment.Category.OTHER.label),
]


def _coerce_nullable_bool(value: str | None) -> bool | None:
    if value in {None, ""}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _coerce_optional_time(value: str | None) -> time | None:
    if value in {None, ""}:
        return None
    hour_text, _sep, minute_text = str(value).partition(":")
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def _bool_to_choice(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def _bool_to_legacy(value: bool | None) -> str:
    if value is True:
        return "1"
    if value is False:
        return "0"
    return ""


def _person_is_deceased_initial(person: Person) -> bool:
    if not person.has_memorial_details():
        return bool(person.is_deceased)
    return any(
        (
            person.death_date,
            person.age_at_death is not None,
            person.deceased_note,
            person.hatsubon_flag is True,
        )
    )
