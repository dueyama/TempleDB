from __future__ import annotations

from apps.core.services import tenant_policy
from apps.imports.models import OfferingPayment

HISTORY_FIELD_LABELS = {
    "head_name": "戸主名",
    "head_name_kana": "戸主フリガナ",
    "head_gender": "戸主の性別",
    "postal_code": "郵便番号",
    "address_line1": "住所1",
    "address_line2": "住所2",
    "address_line3": "住所3",
    "phone": "電話",
    "fax": "FAX",
    "mobile": "携帯",
    "email": "Email",
    "ledger_category": "台帳区分",
    "notes": "備考",
    "name": "氏名",
    "kana": "フリガナ",
    "relationship_label": "続柄",
    "family_category": "家族区分",
    "gender": "性別",
    "is_district_officer": "地区役員",
    "is_responsible_officer": "責任役員",
    "is_monto_sodai": "門徒総代",
    "birth_date": "生年月日",
    "birth_date_raw": "生年月日入力",
    "person_note": "個人備考",
    "is_deceased": "故人フラグ",
    "deceased_profile.death_date": "命日",
    "deceased_profile.death_date_raw": "命日入力",
    "deceased_profile.age_at_death": "享年",
    "deceased_profile.age_unit": "享年単位",
    "deceased_profile.hatsubon_flag": "初盆",
    "deceased_profile.memorial_notice_opt_out": "年回案内不要",
    "deceased_profile.deceased_note": "故人備考",
    "category": "カテゴリ",
    "event_scope": "予定区分",
    "service_event_scope": "関連予定の区分",
    "household_id": "関連する家",
    "person_id": "関連する家族",
    "service_label": "予定名",
    "subject_name": "対象者",
    "link_group_key": "法要リンク",
    "target_date": "基準日",
    "scheduled_date": "予定日",
    "scheduled_time": "予定時刻",
    "completed_on": "実施日",
    "location": "場所",
    "status": "状態",
    "external_calendar_ref": "カレンダー参照",
    "received_on": "入金日",
    "amount": "金額",
    "payment_category": "区分",
    "payment_method": "受領方法",
    "received_by": "受領者",
    "payer_name": "納入者名",
    "deleted_at": "削除日時",
    "deleted_by": "削除者",
    "deletion_note": "削除メモ",
    "household_profile.delivery_method": "送付区分",
    "household_profile.general_notice_opt_out": "案内要否",
    "household_profile.memorial_notice_opt_out": "年回要否",
    "household_profile.district_name": "地区",
    "household_profile.mailing_person_legacy_person_id": "別郵送先 person",
    "household_profile.mailing_name": "別郵送先氏名",
    "household_profile.mailing_postal_code": "別郵送先郵便番号",
    "household_profile.mailing_address_line1": "別郵送先住所1",
    "household_profile.mailing_address_line2": "別郵送先住所2",
    "household_profile.mailing_phone": "別郵送先電話",
    "year": "年度",
    "default_amount": "既定額",
    "is_exception": "例外金額",
    "note": "メモ",
    "district_name": "地区名",
    "district_name_snapshot": "当時の地区名",
    "household_name_snapshot": "当時の戸主名",
    "delivery_method_snapshot": "当時の送付区分",
    "short_name": "略称",
    "sort_order": "表示順",
    "is_active": "有効",
    "manual_note": "手書きメモ",
    "last_printed_member_snapshot": "印刷時の地区メンバー",
    "last_printed_prepared_snapshot_id": "印刷時のデータ識別子",
    "last_printed_at": "印刷記録日時",
    "source_id": "台帳識別子",
    "household_uid": "台帳ID",
    "district_id": "地区ID",
    "district_short_name": "地区略称",
    "district_sort_order": "地区表示順",
    "district_is_active": "地区の有効状態",
    "district_notes": "地区備考",
}


def _history_field_labels() -> dict[str, str]:
    labels = dict(HISTORY_FIELD_LABELS)
    deceased_labels = tenant_policy.deceased_field_labels()
    role_labels = tenant_policy.role_labels()
    labels["is_district_officer"] = role_labels["district_officer"]
    labels["is_responsible_officer"] = role_labels["responsible_officer"]
    labels["is_monto_sodai"] = role_labels["monto_sodai_formal"]
    labels["deceased_profile.kaimyo"] = deceased_labels["kaimyo"]
    labels["deceased_profile.kaimyo_kana"] = deceased_labels["kaimyo_kana"]
    return labels


def _payment_category_label(value: str) -> str:
    return dict(OfferingPayment.Category.choices).get(value, value)


def _payment_method_label(value: str) -> str:
    return dict(OfferingPayment.Method.choices).get(value, value)
