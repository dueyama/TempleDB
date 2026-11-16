"""Data-only tenant policy defaults shared by the façade and owner modules."""

from __future__ import annotations

DECEASED_FIELD_LABEL_DEFAULTS = {
    "person.kaimyo": "法名",
    "person.kaimyo_kana": "法名かな",
    "person.zokumyo": "俗名",
}
IDENTIFIER_LABEL_DEFAULTS = {
    "id.person": "個人ID",
    "id.household": "台帳ID",
    "id.service_event": "法要ID",
}
ROLE_LABEL_DEFAULTS = {
    "role.district_officer": "地区役員",
    "role.monto_sodai": "門徒総代",
    "role.monto_sodai_formal": "門徒総代",
    "role.responsible_officer": "責任役員",
}
PRINT_HEADING_LABEL_DEFAULTS = {
    "document.memorial_sheet": "年忌表",
    "document.memorial_notice": "翌年回忌案内",
    "document.service_schedule_print": "法要情報印刷",
}
ROLE_DOCUMENT_LABEL_DEFAULTS = {
    "document.district_officer_roster": "地区役員一覧",
    "document.monto_sodai_roster": "門徒総代一覧",
    "document.responsible_officer_roster": "責任役員一覧",
    "document.district_officer_postal_labels": "地区役員宛 郵送ラベル",
    "document.district_officer_delivery_labels": "地区役員 配り物ラベル",
    "document.monto_sodai_postal_labels": "門徒総代宛 郵送ラベル",
}
ROLE_NAVIGATION_LABEL_DEFAULTS = {
    "nav.district_officer_postal": "地区役員郵送",
    "nav.district_officer_delivery": "地区役員配り物",
}
MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS = {
    "memorial_notice.label.death_date": "命日",
    "memorial_notice.label.memorial_service": "回忌",
    "memorial_notice.label.other_note": "その他",
}
MARKER_LABEL_DEFAULTS = {
    "marker.memorial_notice": "年回案内",
}
LABEL_DEFAULTS = {
    **DECEASED_FIELD_LABEL_DEFAULTS,
    **IDENTIFIER_LABEL_DEFAULTS,
    **ROLE_LABEL_DEFAULTS,
    **PRINT_HEADING_LABEL_DEFAULTS,
    **ROLE_DOCUMENT_LABEL_DEFAULTS,
    **ROLE_NAVIGATION_LABEL_DEFAULTS,
    **MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS,
    **MARKER_LABEL_DEFAULTS,
}

MAP_LINK_DEFAULTS = {
    "address_query_replacements": [
        {"match": "荒人", "replace": ""},
    ]
}

MEMORIAL_NOTICE_DEFAULT_KEYS = (
    "intro_text",
    "outro_text",
    "signature_text",
)

RELATIONSHIP_LABEL_DEFAULTS = [
    {"label": "祖父", "seq": 1},
    {"label": "祖母", "seq": 2},
    {"label": "父", "seq": 3},
    {"label": "母", "seq": 4},
    {"label": "夫", "seq": 5},
    {"label": "妻", "seq": 6},
    {"label": "兄", "seq": 7},
    {"label": "姉", "seq": 8},
    {"label": "弟", "seq": 9},
    {"label": "妹", "seq": 10},
    {"label": "長男", "seq": 11},
    {"label": "長女", "seq": 12},
    {"label": "次男", "seq": 13},
    {"label": "次女", "seq": 14},
    {"label": "三男", "seq": 15},
    {"label": "三女", "seq": 16},
    {"label": "叔父", "seq": 17},
    {"label": "叔母", "seq": 18},
    {"label": "孫", "seq": 19},
    {"label": "養父", "seq": 20},
    {"label": "養母", "seq": 21},
    {"label": "養子", "seq": 22},
]

SERVICE_SCHEDULE_CATEGORY_DEFAULTS = [
    {"code": "memorial", "label": "年忌", "seq": 1},
    {"code": "chuin", "label": "中陰", "seq": 2},
    {"code": "hatsubon", "label": "初盆", "seq": 3},
    {"code": "funeral", "label": "葬儀", "seq": 4},
    {"code": "bon", "label": "盆", "seq": 5},
    {"code": "otokoshi", "label": "お取越し", "seq": 6},
    {"code": "visit", "label": "訪問", "seq": 7},
    {"code": "other", "label": "その他", "seq": 8},
]

__all__ = [
    "DECEASED_FIELD_LABEL_DEFAULTS",
    "IDENTIFIER_LABEL_DEFAULTS",
    "LABEL_DEFAULTS",
    "MAP_LINK_DEFAULTS",
    "MARKER_LABEL_DEFAULTS",
    "MEMORIAL_NOTICE_DEFAULT_KEYS",
    "MEMORIAL_NOTICE_TABLE_LABEL_DEFAULTS",
    "PRINT_HEADING_LABEL_DEFAULTS",
    "RELATIONSHIP_LABEL_DEFAULTS",
    "ROLE_DOCUMENT_LABEL_DEFAULTS",
    "ROLE_LABEL_DEFAULTS",
    "ROLE_NAVIGATION_LABEL_DEFAULTS",
    "SERVICE_SCHEDULE_CATEGORY_DEFAULTS",
]
