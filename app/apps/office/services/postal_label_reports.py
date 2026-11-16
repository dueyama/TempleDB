from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from django.db.utils import OperationalError, ProgrammingError

from apps.core.services import tenant_policy
from apps.core.services.contact_normalization import normalize_postal_code_digits
from apps.core.services.postal_label_markers import postal_marker_text
from apps.imports import canonical_population, memorial_notice_runtime
from apps.imports.ledger_categories import normalize_ledger_category_code
from apps.imports.models import LEDGER_CATEGORY_WOMENS_ASSOCIATION, District
from apps.imports.postal_recipient_rows import build_postal_recipient_db_rows
from apps.imports.runtime_shared import _clean_value

from .district_authority import district_officer_people_by_district
from .label_paging import _postal_label_pages
from .postal_recipient_order import postal_recipient_print_sort_key


def _postal_marker_text(
    *,
    is_womens_association: bool,
    include_memorial_notice_marker: bool,
    has_memorial_notice_target: bool,
    memorial_notice_marker_label: str,
) -> str:
    return postal_marker_text(
        is_womens_association=is_womens_association,
        include_memorial_notice_marker=include_memorial_notice_marker,
        has_memorial_notice_target=has_memorial_notice_target,
        memorial_notice_marker_label=memorial_notice_marker_label,
    )


def build_postal_label_context(
    source_id: str,
    *,
    include_memorial_notice_marker: bool = False,
    household_uids: Iterable[str] | None = None,
) -> dict:
    selected_household_uids = tuple(
        dict.fromkeys(
            cleaned
            for value in household_uids or ()
            if (cleaned := _clean_value(value))
        )
    )
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if canonical_batch is None:
        return {
            "available": False,
            "error_message": "印刷対象の現行台帳がありません。",
            "label_rows": [],
            "label_pages": [],
            "total_count": 0,
            "page_count": 0,
            "slots_per_page": 12,
            "include_memorial_notice_marker": include_memorial_notice_marker,
            "memorial_notice_marker_count": 0,
            "memorial_notice_marker_warning": "",
            "memorial_notice_target_year": date.today().year + 1,
            "spot_selection_active": bool(selected_household_uids),
            "selected_household_uids": selected_household_uids,
            "requested_household_count": len(selected_household_uids),
            "missing_household_count": len(selected_household_uids),
        }

    memorial_notice_target_year = date.today().year + 1
    memorial_notice_target_household_ids: set[str] = set()
    memorial_notice_marker_warning = ""
    memorial_notice_marker_label = tenant_policy.marker_labels()["memorial_notice"]
    if include_memorial_notice_marker:
        memorial_notice_target_household_ids = (
            memorial_notice_runtime._household_ids_with_memorial_notice_targets(
                source_id,
                year=memorial_notice_target_year,
            )
        )

    db_rows = build_postal_recipient_db_rows(
        source_id,
        canonical_batch,
        canonical_scope=True,
        household_uids=selected_household_uids or None,
    )
    label_rows: list[dict] = []
    for row in sorted(db_rows, key=postal_recipient_print_sort_key):
        household_id = _clean_value(row.get("household_id"))
        recipient_name = _clean_value(row.get("recipient_name")) or _clean_value(
            row.get("household_name")
        )
        postal_code = normalize_postal_code_digits(row.get("postal_code"))
        is_womens_association = (
            normalize_ledger_category_code(row.get("ledger_category"))
            == LEDGER_CATEGORY_WOMENS_ASSOCIATION
        )
        postal_code_display = ""
        if len(postal_code) == 7:
            postal_code_display = f"〒{postal_code[:3]}-{postal_code[3:]}"
        elif _clean_value(row.get("postal_code")):
            postal_code_display = f"〒{_clean_value(row.get('postal_code'))}"
        address_lines = [
            line
            for line in [
                _clean_value(row.get("address_line1")),
                _clean_value(row.get("address_line2")),
            ]
            if line
        ]
        label_rows.append(
            {
                "household_id": household_id,
                "household_name": _clean_value(row.get("household_name")),
                "recipient_name": recipient_name,
                "recipient_role_label": _clean_value(row.get("recipient_role_label")) or "戸主宛",
                "recipient_kana": _clean_value(row.get("recipient_kana")),
                "postal_code_display": postal_code_display,
                "address_lines": address_lines,
                "addressee": f"{recipient_name} 様" if recipient_name else "",
                "is_womens_association": is_womens_association,
                "has_memorial_notice_target": household_id in memorial_notice_target_household_ids,
                "marker_position": "bottom_right",
                "marker_text": _postal_marker_text(
                    is_womens_association=is_womens_association,
                    include_memorial_notice_marker=include_memorial_notice_marker,
                    has_memorial_notice_target=household_id in memorial_notice_target_household_ids,
                    memorial_notice_marker_label=memorial_notice_marker_label,
                ),
            }
        )

    label_pages = _postal_label_pages(label_rows, per_page=12)
    matched_household_uids = {
        _clean_value(row.get("household_id"))
        for row in label_rows
        if _clean_value(row.get("household_id"))
    }
    return {
        "available": True,
        "error_message": "",
        "label_rows": label_rows,
        "label_pages": label_pages,
        "total_count": len(label_rows),
        "page_count": len(label_pages),
        "slots_per_page": 12,
        "include_memorial_notice_marker": include_memorial_notice_marker,
        "memorial_notice_marker_count": sum(
            1 for row in label_rows if row.get("has_memorial_notice_target")
        ),
        "memorial_notice_marker_warning": memorial_notice_marker_warning,
        "memorial_notice_target_year": memorial_notice_target_year,
        "spot_selection_active": bool(selected_household_uids),
        "selected_household_uids": selected_household_uids,
        "requested_household_count": len(selected_household_uids),
        "missing_household_count": len(
            set(selected_household_uids) - matched_household_uids
        ),
    }


def build_district_officer_postal_label_context(source_id: str) -> dict:
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if canonical_batch is None:
        return {
            "available": False,
            "error_message": "印刷対象の現行台帳がありません。",
            "label_rows": [],
            "label_pages": [],
            "skipped_rows": [],
            "skipped_count": 0,
            "total_count": 0,
            "page_count": 0,
            "slots_per_page": 12,
        }

    try:
        districts = list(District.objects.filter(is_active=True).order_by("sort_order", "name"))
        officers_by_district = district_officer_people_by_district(source_id)
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "error_message": "地区役員ラベルのデータ取得に失敗しました。",
            "label_rows": [],
            "label_pages": [],
            "skipped_rows": [],
            "skipped_count": 0,
            "total_count": 0,
            "page_count": 0,
            "slots_per_page": 12,
        }

    label_rows: list[dict] = []
    skipped_rows: list[dict] = []
    for district in districts:
        officer_entries = officers_by_district.get(district.id, [])
        if not officer_entries:
            skipped_rows.append(
                {
                    "district_name": district.name,
                    "officer_name": "",
                    "reason": "地区役員未設定",
                }
            )
            continue
        if len(officer_entries) > 1:
            skipped_rows.append(
                {
                    "district_name": district.name,
                    "officer_name": " / ".join(
                        (person.name or person.person_uid).strip() or person.person_uid
                        for person, _profile in officer_entries
                    ),
                    "reason": "地区役員が複数います",
                }
            )
            continue
        officer_person, _profile = officer_entries[0]
        household = officer_person.household
        if household is None:
            skipped_rows.append(
                {
                    "district_name": district.name,
                    "officer_name": (
                        officer_person.name or officer_person.person_uid
                    ).strip(),
                    "reason": "地区役員 household が見つかりません",
                }
            )
            continue
        officer_name = (
            officer_person.name or household.display_head_name()
        ).strip() or household.display_head_name()

        postal_code = normalize_postal_code_digits(household.postal_code)
        postal_code_display = ""
        if len(postal_code) == 7:
            postal_code_display = f"〒{postal_code[:3]}-{postal_code[3:]}"
        elif _clean_value(household.postal_code):
            postal_code_display = f"〒{_clean_value(household.postal_code)}"
        address_lines = [
            line
            for line in [
                _clean_value(household.address_line1),
                _clean_value(household.address_line2),
            ]
            if line
        ]
        if not postal_code_display and not address_lines:
            skipped_rows.append(
                {
                    "district_name": district.name,
                    "officer_name": officer_name,
                    "reason": "郵送先住所が不足しています",
                }
            )
            continue

        label_rows.append(
            {
                "district_name": district.name,
                "district_short_name": _clean_value(district.short_name) or district.name,
                "officer_name": officer_name,
                "postal_code_display": postal_code_display,
                "address_lines": address_lines,
                "addressee": f"{officer_name} 様",
                "marker_text": _clean_value(district.short_name) or district.name,
            }
        )

    label_pages = _postal_label_pages(label_rows, per_page=12)
    return {
        "available": True,
        "error_message": "",
        "label_rows": label_rows,
        "label_pages": label_pages,
        "skipped_rows": skipped_rows,
        "skipped_count": len(skipped_rows),
        "total_count": len(label_rows),
        "page_count": len(label_pages),
        "slots_per_page": 12,
    }
