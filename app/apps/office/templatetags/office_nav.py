from __future__ import annotations

from django import template
from django.urls import reverse

from apps.core.services import tenant_policy

register = template.Library()


PAGE_DEFINITIONS = {
    "home": {
        "section": "home",
        "label": "寺務ホーム",
        "url_name": "office:home",
    },
    "household_browser": {
        "section": "households",
        "label": "戸主ブラウザ",
        "url_name": "office:household_browser",
    },
    "person_search": {
        "section": "households",
        "label": "人検索",
        "url_name": "office:person_search",
    },
    "universal_search": {
        "section": "households",
        "label": "万能検索",
        "url_name": "office:universal_search",
    },
    "special_searches": {
        "section": "households",
        "label": "特殊検索",
        "url_name": "office:special_searches",
    },
    "data_quality": {
        "section": "households",
        "label": "データ問題点",
        "url_name": "office:data_quality",
    },
    "service_ledger": {
        "section": "memorials",
        "label": "法要台帳",
        "url_name": "office:service_ledger",
    },
    "memorial_notices": {
        "section": "memorials",
        "label": "翌年回忌案内",
        "url_name": "office:memorial_notices",
    },
    "memorial_distribution": {
        "section": "distribution",
        "label": "年回表配布準備",
        "url_name": "office:memorial_distribution",
    },
    "settings_home": {
        "section": "settings",
        "label": "設定",
        "url_name": "office:settings_home",
    },
    "data_imports": {
        "section": "settings",
        "label": "取込・照合",
        "url_name": "office:data_imports",
    },
    "user_management": {
        "section": "settings",
        "label": "ユーザー管理",
        "url_name": "office:user_management",
        "requires_superuser": True,
    },
    "backup_settings": {
        "section": "settings",
        "label": "バックアップ",
        "url_name": "office:backup_settings",
        "requires_superuser": True,
    },
    "google_calendar_settings": {
        "section": "settings",
        "label": "Google カレンダー",
        "url_name": "office:google_calendar_settings",
        "requires_superuser": True,
    },
    "data_import_console": {
        "section": "settings",
        "label": "外部データ取込",
        "url_name": "imports:console",
    },
    "accounting": {
        "section": "accounting",
        "label": "通常会計",
        "url_name": "office:accounting",
    },
    "nokotsudan_accounting": {
        "section": "accounting",
        "label": "納骨壇会計",
        "url_name": "office:nokotsudan_accounting",
    },
    "annual_membership_fees": {
        "section": "accounting",
        "label": "護持会費",
        "url_name": "office:annual_membership_fees",
    },
    "districts": {
        "section": "settings",
        "label": "地区定義",
        "url_name": "office:districts",
    },
    "household_districts": {
        "section": "distribution",
        "label": "戸主地区・送付区分",
        "url_name": "office:household_districts",
    },
    "hand_delivery_review": {
        "section": "distribution",
        "label": "手配り照合",
        "url_name": "office:hand_delivery_review",
    },
    "postal_review": {
        "section": "distribution",
        "label": "郵送照合",
        "url_name": "office:postal_review",
    },
    "postal_compare": {
        "section": "distribution",
        "label": "郵送比較",
        "url_name": "office:postal_compare",
    },
    "postal_labels": {
        "section": "distribution",
        "label": "郵送ラベル",
        "url_name": "office:postal_labels",
    },
    "district_officer_postal_labels": {
        "section": "distribution",
        "label": "地区役員郵送",
        "url_name": "office:district_officer_postal_labels",
    },
    "district_officer_delivery_labels": {
        "section": "distribution",
        "label": "地区役員配り物",
        "url_name": "office:district_officer_delivery_labels",
    },
    "district_member_sheets": {
        "section": "distribution",
        "label": "地区メンバー一覧",
        "url_name": "office:district_member_sheets",
    },
    "district_officer_roster": {
        "section": "distribution",
        "label": "地区役員一覧",
        "url_name": "office:district_officer_roster",
    },
    "responsible_officer_roster": {
        "section": "distribution",
        "label": "責任役員一覧",
        "url_name": "office:responsible_officer_roster",
    },
    "monto_sodai_roster": {
        "section": "distribution",
        "label": "総代一覧",
        "url_name": "office:monto_sodai_roster",
    },
    "monto_sodai_postal_labels": {
        "section": "distribution",
        "label": "総代宛 郵送ラベル",
        "url_name": "office:monto_sodai_postal_labels",
    },
    "data_science": {
        "section": "home",
        "label": "統計・分析",
        "url_name": "office:data_science",
    },
}

SECTION_ORDER = {
    "home": [
        "home",
        "data_science",
    ],
    "households": [
        "household_browser",
        "person_search",
        "universal_search",
        "special_searches",
        "data_quality",
    ],
    "memorials": [
        "service_ledger",
        "memorial_notices",
    ],
    "settings": [
        "settings_home",
        "data_imports",
        "user_management",
        "backup_settings",
        "google_calendar_settings",
        "districts",
        "data_import_console",
    ],
    "accounting": [
        "accounting",
        "nokotsudan_accounting",
        "annual_membership_fees",
    ],
    "distribution": [
        "memorial_distribution",
        "household_districts",
        "hand_delivery_review",
        "postal_review",
        "postal_compare",
        "postal_labels",
        "district_officer_postal_labels",
        "district_officer_delivery_labels",
        "district_member_sheets",
        "district_officer_roster",
        "responsible_officer_roster",
        "monto_sodai_roster",
        "monto_sodai_postal_labels",
    ],
}

SECTION_GROUPS = {
    "home": [
        {
            "heading": "寺務ホーム",
            "pages": [
                "home",
                "data_science",
            ],
        },
    ],
    "households": [
        {
            "heading": "戸主ブラウザ",
            "pages": [
                "household_browser",
            ],
        },
        {
            "heading": "検索",
            "pages": [
                "person_search",
                "universal_search",
                "special_searches",
            ],
        },
        {
            "heading": "点検",
            "pages": [
                "data_quality",
            ],
        },
    ],
    "settings": [
        {
            "heading": "基本設定",
            "pages": [
                "settings_home",
                "user_management",
                "backup_settings",
                "google_calendar_settings",
                "districts",
            ],
        },
        {
            "heading": "取込・照合",
            "pages": [
                "data_imports",
                "data_import_console",
            ],
        },
    ],
    "accounting": [
        {
            "heading": "会計",
            "pages": [
                "accounting",
                "nokotsudan_accounting",
                "annual_membership_fees",
            ],
        },
    ],
    "distribution": [
        {
            "heading": "配布設定",
            "pages": [
                "household_districts",
            ],
        },
        {
            "heading": "名簿照合",
            "pages": [
                "hand_delivery_review",
                "postal_review",
                "postal_compare",
            ],
        },
        {
            "heading": "ラベル・印刷",
            "pages": [
                "memorial_distribution",
                "postal_labels",
                "district_officer_postal_labels",
                "district_officer_delivery_labels",
                "district_member_sheets",
                "monto_sodai_postal_labels",
            ],
        },
        {
            "heading": "役職名簿",
            "pages": [
                "district_officer_roster",
                "responsible_officer_roster",
                "monto_sodai_roster",
            ],
        },
    ],
}

PRIMARY_NAV_DEFINITIONS = (
    {
        "key": "home",
        "section": "home",
        "label": "寺務ホーム",
        "url_name": "office:home",
    },
    {
        "key": "household_browser",
        "section": "households",
        "label": "戸主・家族",
        "url_name": "office:household_browser",
    },
    {
        "key": "service_ledger",
        "section": "memorials",
        "label": "法要・回忌",
        "url_name": "office:service_ledger",
    },
    {
        "key": "accounting",
        "section": "accounting",
        "label": "会計",
        "url_name": "office:accounting",
    },
    {
        "key": "distribution",
        "section": "distribution",
        "label": "配布・名簿",
        "url_name": "office:print_hub",
    },
    {
        "key": "settings_home",
        "section": "settings",
        "label": "設定",
        "url_name": "office:settings_home",
    },
)

APP_QUICKLINK_ACTIVE_VIEW_NAMES = {
    "home": {"office:home", "office:data_science"},
    "household_browser": {
        "office:household_browser",
        "office:person_search",
        "office:universal_search",
        "office:special_searches",
        "office:memo_tag_catalog",
        "office:data_quality",
        "office:edit_household",
        "office:print_household_information",
        "office:create_household_current_person",
        "office:create_household_memorial_person",
        "office:edit_person",
        "office:person_memorial_transition",
        "office:household_head_transition",
        "office:replace_virtual_head",
        "office:move_household_head_to_current",
        "office:move_household_head_to_memorial",
        "office:memorial_sheet",
    },
    "service_ledger": {
        "office:service_ledger",
        "office:create_service_schedule",
        "office:edit_service_schedule",
        "office:print_service_schedule",
        "office:cancel_memorial_candidate",
        "office:memorial_notices",
    },
    "accounting": {
        "office:accounting",
        "office:nokotsudan_accounting",
        "office:annual_membership_fees",
        "office:annual_membership_fee_receipts",
        "office:annual_membership_fee_check_sheets",
        "office:annual_membership_fee_postal_scans",
        "office:annual_membership_fee_postal_scan_file",
    },
    "distribution": {
        "office:print_hub",
        "office:household_districts",
        "office:import_hand_delivery_districts",
        "office:import_postal_assignments",
        "office:hand_delivery_review",
        "office:replace_hand_delivery_household_head",
        "office:create_hand_delivery_review_household",
        "office:rollback_created_hand_delivery_review_household",
        "office:postal_review",
        "office:replace_postal_household_head",
        "office:assign_postal_override",
        "office:create_postal_review_household",
        "office:rollback_created_postal_review_household",
        "office:postal_compare",
        "office:postal_labels",
        "office:district_officer_postal_labels",
        "office:district_officer_delivery_labels",
        "office:district_member_sheets",
        "office:district_member_sheets_print",
        "office:memorial_distribution",
        "office:memorial_distribution_print",
        "office:district_officer_roster",
        "office:monto_sodai_roster",
        "office:monto_sodai_postal_labels",
        "office:responsible_officer_roster",
        "office:remove_person_role",
    },
    "settings_home": {
        "office:settings_home",
        "office:data_imports",
        "office:backup_settings",
        "office:backup_migration_guide",
        "office:run_backup_now",
        "office:verify_backup_now",
        "office:google_calendar_settings",
        "office:google_calendar_bulk_sync_status",
        "office:districts",
        "office:user_management",
        "imports:console",
        "imports:register_source",
        "imports:set_default_source",
        "imports:run_action",
    },
    "record_history": {"office:record_history"},
}

MOBILE_TITLE_BY_VIEW_NAME = {
    "imports:console": "外部データ取込",
    "office:home": "寺務ホーム",
    "office:record_history": "変更・削除履歴",
    "office:memorial_notices": "翌年回忌案内",
    "office:memorial_sheet": "年忌表",
    "office:print_service_schedule": "法要情報印刷",
    "office:print_hub": "配布・名簿",
    "office:annual_membership_fee_receipts": "護持会費領収書",
    "office:annual_membership_fee_check_sheets": "護持会費チェックシート",
    "office:annual_membership_fee_postal_scans": "郵便振込PDF照合",
    "office:annual_membership_fee_postal_scan_file": "郵便振込PDF",
    "office:district_member_sheets_print": "地区メンバー一覧印刷",
    "office:memorial_distribution_print": "年回表まとめ印刷",
}
MOBILE_TITLE_BY_VIEW_NAME.update(
    {
        definition["url_name"]: definition["label"]
        for definition in PAGE_DEFINITIONS.values()
    }
)
APP_QUICKLINK_LABELS = {
    definition["key"]: definition["label"]
    for definition in PRIMARY_NAV_DEFINITIONS
}
PAGE_KEYS_BY_URL_NAME = {
    definition["url_name"]: key
    for key, definition in PAGE_DEFINITIONS.items()
}


def _resolved_page_label(page_key: str) -> str:
    definition = PAGE_DEFINITIONS[page_key]
    role_document_labels = tenant_policy.role_document_labels()
    role_navigation_labels = tenant_policy.role_navigation_labels()
    return {
        "district_officer_postal_labels": role_navigation_labels.get(
            "district_officer_postal",
            definition["label"],
        ),
        "district_officer_delivery_labels": role_navigation_labels.get(
            "district_officer_delivery",
            definition["label"],
        ),
        "district_officer_roster": role_document_labels.get(
            "district_officer_roster",
            definition["label"],
        ),
        "responsible_officer_roster": role_document_labels.get(
            "responsible_officer_roster",
            definition["label"],
        ),
        "monto_sodai_roster": role_document_labels.get(
            "monto_sodai_roster",
            definition["label"],
        ),
        "monto_sodai_postal_labels": role_document_labels.get(
            "monto_sodai_postal_labels",
            definition["label"],
        ),
        "memorial_notices": tenant_policy.print_heading_labels().get(
            "memorial_notice",
            definition["label"],
        ),
    }.get(page_key, definition["label"])


def _resolved_group_heading(heading: str) -> str:
    if heading == "地区役員":
        return tenant_policy.role_labels()["district_officer"]
    return heading


def _build_page_url(page_key: str) -> str:
    definition = PAGE_DEFINITIONS[page_key]
    return reverse(definition["url_name"])


def _current_quicklink_key(context) -> str:
    request = context.get("request")
    resolver_match = getattr(request, "resolver_match", None)
    view_name = getattr(resolver_match, "view_name", "") or ""
    if not view_name:
        return ""

    for quicklink_key, view_names in APP_QUICKLINK_ACTIVE_VIEW_NAMES.items():
        if view_name in view_names:
            return quicklink_key
    return ""


def _current_view_name(context) -> str:
    request = context.get("request")
    resolver_match = getattr(request, "resolver_match", None)
    return getattr(resolver_match, "view_name", "") or ""


@register.simple_tag(takes_context=True)
def build_office_subnav(
    context,
    page_key: str,
):
    definition = PAGE_DEFINITIONS.get(page_key)
    if definition is None:
        return []

    request = context.get("request")
    is_superuser = bool(getattr(getattr(request, "user", None), "is_superuser", False))

    section = definition["section"]
    grouped_page_order = SECTION_GROUPS.get(section)
    if grouped_page_order is None:
        grouped_page_order = [{"heading": "", "pages": SECTION_ORDER.get(section, [])}]

    groups = []
    total_links = 0
    for group_definition in grouped_page_order:
        links = []
        for candidate_key in group_definition["pages"]:
            candidate = PAGE_DEFINITIONS[candidate_key]
            if candidate.get("requires_superuser") and not is_superuser:
                continue
            links.append(
                {
                    "label": _resolved_page_label(candidate_key),
                    "url": _build_page_url(candidate_key),
                    "is_current": candidate_key == page_key,
                }
            )
        if not links:
            continue
        total_links += len(links)
        groups.append(
            {
                "heading": _resolved_group_heading(group_definition["heading"]),
                "links": links,
            }
        )

    if total_links <= 1:
        return []
    return groups


@register.simple_tag(takes_context=True)
def build_app_quicklinks(context):
    active_key = _current_quicklink_key(context)
    return [
        {
            "key": definition["key"],
            "label": definition["label"],
            "url": reverse(definition["url_name"]),
            "is_current": definition["key"] == active_key,
        }
        for definition in PRIMARY_NAV_DEFINITIONS
    ]


@register.simple_tag
def build_office_global_nav(current_section: str):
    return [
        {
            "label": definition["label"],
            "url": reverse(definition["url_name"]),
            "is_current": definition["section"] == current_section,
        }
        for definition in PRIMARY_NAV_DEFINITIONS
    ]


@register.simple_tag(takes_context=True)
def current_mobile_page_title(context) -> str:
    context_title = context.get("title")
    if isinstance(context_title, str) and context_title.strip():
        return context_title.strip()

    view_name = _current_view_name(context)
    if view_name in {
        "imports:console",
        "office:home",
        "office:record_history",
        "office:memorial_sheet",
        "office:print_service_schedule",
    }:
        return MOBILE_TITLE_BY_VIEW_NAME[view_name]

    page_key = PAGE_KEYS_BY_URL_NAME.get(view_name)
    if page_key is not None:
        return _resolved_page_label(page_key)

    active_key = _current_quicklink_key(context)
    if active_key in APP_QUICKLINK_LABELS:
        return APP_QUICKLINK_LABELS[active_key]

    return "TempleDB"
