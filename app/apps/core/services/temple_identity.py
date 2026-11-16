from __future__ import annotations

from apps.core.models import (
    DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE,
    DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT,
    TempleIdentitySetting,
)

TEMPLE_SIGNATURE_PLACEHOLDERS = {
    "sect": "宗派名",
    "name": "寺院名",
    "postal_code": "郵便番号",
    "address": "住所",
    "phone": "電話番号",
    "chief_priest_name": "住職名",
}

TEMPLE_DISPLAY_PLACEHOLDERS = {
    "sect": "宗派名",
    "name": "寺院名",
    "postal_code": "郵便番号",
    "address": "住所",
    "phone": "電話番号",
    "chief_priest_name": "住職名",
}


def get_or_create_temple_identity_setting() -> TempleIdentitySetting:
    setting, _created = TempleIdentitySetting.objects.get_or_create(singleton_key=1)
    return setting


def normalize_service_schedule_sutra_cycle(raw_value: str | None) -> list[str]:
    items = [line.strip() for line in (raw_value or "").splitlines() if line.strip()]
    if items:
        return items
    return list(DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE)


def default_service_schedule_sutra_cycle_text() -> str:
    return DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT


def service_schedule_sutra_cycle(setting: TempleIdentitySetting | None = None) -> list[str]:
    resolved_setting = setting or get_or_create_temple_identity_setting()
    return normalize_service_schedule_sutra_cycle(resolved_setting.service_schedule_sutra_cycle)


def current_temple_identity() -> dict[str, str]:
    setting = get_or_create_temple_identity_setting()
    return {
        "sect": (setting.temple_sect or "").strip() or TEMPLE_DISPLAY_PLACEHOLDERS["sect"],
        "name": (setting.temple_name or "").strip() or TEMPLE_DISPLAY_PLACEHOLDERS["name"],
        "postal_code": (
            (setting.temple_postal_code or "").strip() or TEMPLE_DISPLAY_PLACEHOLDERS["postal_code"]
        ),
        "address": (setting.temple_address or "").strip() or TEMPLE_DISPLAY_PLACEHOLDERS["address"],
        "phone": (setting.temple_phone or "").strip() or TEMPLE_DISPLAY_PLACEHOLDERS["phone"],
        "chief_priest_name": (
            (setting.chief_priest_name or "").strip()
            or TEMPLE_DISPLAY_PLACEHOLDERS["chief_priest_name"]
        ),
    }


def memorial_notice_identity_tokens(setting: TempleIdentitySetting | None = None) -> dict[str, str]:
    resolved_setting = setting or get_or_create_temple_identity_setting()
    sect = (resolved_setting.temple_sect or "").strip() or TEMPLE_SIGNATURE_PLACEHOLDERS["sect"]
    name = (resolved_setting.temple_name or "").strip() or TEMPLE_SIGNATURE_PLACEHOLDERS["name"]
    postal_code = (
        (resolved_setting.temple_postal_code or "").strip()
        or TEMPLE_SIGNATURE_PLACEHOLDERS["postal_code"]
    )
    address = (resolved_setting.temple_address or "").strip() or TEMPLE_SIGNATURE_PLACEHOLDERS["address"]
    phone = (resolved_setting.temple_phone or "").strip() or TEMPLE_SIGNATURE_PLACEHOLDERS["phone"]
    chief_priest_name = (
        (resolved_setting.chief_priest_name or "").strip()
        or TEMPLE_SIGNATURE_PLACEHOLDERS["chief_priest_name"]
    )
    return {
        "{{TEMPLE_SECT}}": sect,
        "{{TEMPLE_NAME}}": name,
        "{{TEMPLE_POSTAL_CODE}}": postal_code,
        "{{TEMPLE_ADDRESS}}": address,
        "{{TEMPLE_PHONE}}": phone,
        "{{TEMPLE_CHIEF_PRIEST_NAME}}": chief_priest_name,
    }
