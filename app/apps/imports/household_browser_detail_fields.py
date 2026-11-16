from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode

from apps.core.services import tenant_policy as tenant_policy_services

from . import household_profile_runtime, runtime_shared
from .district_authority import district_officer_people_by_district
from .models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    HOUSEHOLD_DELIVERY_POSTAL,
)

_ADDRESS_FIELD_LABELS = {"〒", "住所1", "住所2", "住所3"}
_PHONE_FIELD_LABELS = {"電話", "携帯"}


def _household_browser_map_query_address(value: str | None) -> str:
    address_text = runtime_shared._clean_value(value)
    if not address_text:
        return ""
    for old, new in tenant_policy_services.map_link_address_query_replacements():
        address_text = address_text.replace(old, new)
    return address_text


def _household_browser_address_link_url(postal_code: str | None, address_lines: list[str | None]) -> str:
    address_text = "".join(
        line for line in (runtime_shared._clean_value(value) for value in address_lines) if line
    )
    normalized_address_text = _household_browser_map_query_address(address_text)
    if normalized_address_text:
        return f"https://maps.apple.com/?{urlencode({'q': normalized_address_text})}"

    cleaned_postal_code = runtime_shared._clean_value(postal_code)
    if not cleaned_postal_code:
        return ""
    return f"https://maps.apple.com/?{urlencode({'q': cleaned_postal_code})}"


def _household_browser_phone_link_url(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", runtime_shared._clean_value(value))
    digits = re.sub(r"[^0-9]", "", normalized)
    if not digits:
        return ""
    return f"tel:{digits}"


def _household_browser_household_fields(
    source_id: str,
    household_id: str,
    base_fields: list[dict],
    head_person_fields: list[dict],
) -> list[dict]:
    profile = household_profile_runtime._household_profile_for_display(source_id, household_id)
    delivery_method = profile.delivery_method if profile is not None else ""
    delivery_label = HOUSEHOLD_DELIVERY_LABELS.get(delivery_method, "") or "未設定"
    district_label = profile.district.name if profile is not None and profile.district_id else "地区未設定"
    officer_label = "地区役員未設定"
    if profile is not None and profile.district_id and delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
        officers = district_officer_people_by_district(source_id).get(profile.district_id, [])
        if len(officers) == 1:
            officer_person, _officer_profile = officers[0]
            officer_label = (
                (officer_person.name or officer_person.person_uid).strip()
                or officer_person.person_uid
            )
        elif len(officers) > 1:
            officer_label = "地区役員複数"
    if delivery_method == HOUSEHOLD_DELIVERY_POSTAL:
        district_label = ""
        officer_label = ""

    head_fields_by_label = {
        field.get("label"): field.get("value")
        for field in head_person_fields
        if field.get("label") in {"ﾌﾘｶﾞﾅ", "性別", "生年月日", "続柄"} and field.get("value")
    }
    household_fields_by_label = {
        field.get("label"): field.get("value")
        for field in base_fields
        if field.get("label")
        not in {"氏名", "ﾌﾘｶﾞﾅ", "電話", "携帯", "Email", "備考", "世話人", "世話人ID", "地区ID"}
        and field.get("value")
    }
    memorial_notice_label = household_profile_runtime._household_memorial_notice_display_value(
        profile_value=profile.memorial_notice_opt_out if profile is not None else None,
        raw_value=None,
    )
    general_notice_label = household_profile_runtime._household_general_notice_display_value(
        profile_value=profile.general_notice_opt_out if profile is not None else None,
    )
    combined_fields = {
        "台帳ID": household_fields_by_label.get("台帳ID", ""),
        "ﾌﾘｶﾞﾅ": head_fields_by_label.get("ﾌﾘｶﾞﾅ", household_fields_by_label.get("ﾌﾘｶﾞﾅ", "")),
        "性別": head_fields_by_label.get("性別", "") or "未決定",
        "生年月日": head_fields_by_label.get("生年月日", ""),
        "続柄": head_fields_by_label.get("続柄", ""),
        "送付区分": delivery_label,
        "地区": district_label,
        "地区役員": officer_label,
        "台帳区分": household_fields_by_label.get("台帳区分", ""),
        "〒": household_fields_by_label.get("〒", ""),
        "住所1": household_fields_by_label.get("住所1", ""),
        "住所2": household_fields_by_label.get("住所2", ""),
        "住所3": household_fields_by_label.get("住所3", ""),
        "電話": next(
            (field.get("value") for field in base_fields if field.get("label") == "電話" and field.get("value")),
            "",
        ),
        "ＦＡＸ": household_fields_by_label.get("ＦＡＸ", ""),
        "携帯": next(
            (field.get("value") for field in base_fields if field.get("label") == "携帯" and field.get("value")),
            "",
        ),
        "Email": next(
            (field.get("value") for field in base_fields if field.get("label") == "Email" and field.get("value")),
            "",
        ),
        "屋号": household_fields_by_label.get("屋号", ""),
        "案内要否": general_notice_label,
        "年回要否": memorial_notice_label,
        "月忌要否": household_fields_by_label.get("月忌要否", ""),
        "備考": next(
            (field.get("value") for field in base_fields if field.get("label") == "備考" and field.get("value")),
            "",
        ),
        "新規登録日": household_fields_by_label.get("新規登録日", ""),
    }
    address_link_url = _household_browser_address_link_url(
        household_fields_by_label.get("〒", ""),
        [
            household_fields_by_label.get("住所1", ""),
            household_fields_by_label.get("住所2", ""),
            household_fields_by_label.get("住所3", ""),
        ],
    )
    fields: list[dict] = []
    for label, value in combined_fields.items():
        if not value:
            continue
        item = {"label": label, "value": value}
        if label in _ADDRESS_FIELD_LABELS and address_link_url:
            item["href"] = address_link_url
            item["kind"] = "address"
        elif label in _PHONE_FIELD_LABELS:
            phone_link_url = _household_browser_phone_link_url(value)
            if phone_link_url:
                item["href"] = phone_link_url
                item["kind"] = "phone"
        fields.append(item)
    return fields


def _household_browser_postal_delivery_summary(
    source_id: str,
    household_id: str,
    base_fields: list[dict],
    head_person_fields: list[dict],
    current_members: list[dict],
) -> dict | None:
    profile = household_profile_runtime._household_profile_for_display(source_id, household_id)
    if profile is None or profile.delivery_method != HOUSEHOLD_DELIVERY_POSTAL:
        return None

    base_fields_by_label = {
        field.get("label"): field.get("value")
        for field in base_fields
        if field.get("label") and field.get("value")
    }
    head_name = next(
        (
            field.get("value")
            for field in head_person_fields
            if field.get("label") == "氏名" and field.get("value")
        ),
        "",
    ) or base_fields_by_label.get("氏名", "")
    current_members_by_person_id = {
        runtime_shared._clean_value(member.get("person_id")): member
        for member in current_members
        if runtime_shared._clean_value(member.get("person_id"))
    }
    mailing_person = current_members_by_person_id.get(
        runtime_shared._clean_value(profile.mailing_person_uid)
    )
    recipient_name = (
        runtime_shared._clean_value(mailing_person.get("name")) if mailing_person is not None else ""
    ) or runtime_shared._clean_value(profile.mailing_name) or head_name
    is_head_recipient = (
        runtime_shared._normalize_same_name_text(recipient_name)
        == runtime_shared._normalize_same_name_text(head_name)
    )
    postal_code = runtime_shared._clean_value(profile.mailing_postal_code) or runtime_shared._clean_value(
        base_fields_by_label.get("〒")
    )
    address_lines = [
        line
        for line in [
            runtime_shared._clean_value(profile.mailing_address_line1),
            runtime_shared._clean_value(profile.mailing_address_line2),
        ]
        if line
    ]
    if not address_lines:
        address_lines = [
            line
            for line in [
                runtime_shared._clean_value(base_fields_by_label.get("住所1")),
                runtime_shared._clean_value(base_fields_by_label.get("住所2")),
                runtime_shared._clean_value(base_fields_by_label.get("住所3")),
            ]
            if line
        ]
    phone = runtime_shared._clean_value(profile.mailing_phone) or runtime_shared._clean_value(
        base_fields_by_label.get("電話")
    )
    attention_note = ""
    if recipient_name and not is_head_recipient:
        attention_note = f"戸主ではなく {recipient_name} 様宛に送付します。"
    address_link_url = _household_browser_address_link_url(postal_code, address_lines)
    phone_link_url = _household_browser_phone_link_url(phone)
    return {
        "addressee": f"{recipient_name or head_name} 様",
        "recipient_name": recipient_name or head_name,
        "postal_code": postal_code,
        "address_lines": address_lines,
        "phone": phone,
        "address_link_url": address_link_url,
        "phone_link_url": phone_link_url,
        "is_head_recipient": is_head_recipient,
        "recipient_role_label": "戸主宛" if is_head_recipient else "戸主以外に送付",
        "attention_note": attention_note,
    }


__all__ = [
    "_household_browser_household_fields",
    "_household_browser_postal_delivery_summary",
]
