from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from django.utils import timezone

from apps.core.services import memorial_dates
from apps.core.services import temple_identity as temple_identity_services
from apps.imports import canonical_population
from apps.imports.forms import AnnualMembershipFeeEntryForm, AnnualMembershipFeeSettingForm
from apps.imports.ledger_categories import normalize_ledger_category_code
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_LABELS,
    HOUSEHOLD_DELIVERY_NONE,
    HOUSEHOLD_DELIVERY_POSTAL,
    LEDGER_CATEGORY_WOMENS_ASSOCIATION,
    AnnualMembershipFeePayment,
    AnnualMembershipFeePostalScan,
    AnnualMembershipFeeSetting,
    Household,
    HouseholdProfile,
    ImportBatch,
    LegacySource,
)
from apps.office.services.household_editing_core import (
    _household_display_head_name,
    _household_display_head_name_kana,
)
from apps.office.web_support import (
    _annual_membership_fee_check_sheets_url,
    _annual_membership_fee_postal_scans_url,
    _annual_membership_fee_receipts_url,
    _annual_membership_fees_url,
)

ANNUAL_MEMBERSHIP_FEE_RECEIPTS_PER_PAGE = 4
ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON = "送付しない設定のため請求対象外です。"
ANNUAL_MEMBERSHIP_FEE_PAYMENT_STATUS_LABELS = {
    "billable": "請求対象",
    "paid": "納付済み",
    "unpaid": "未納",
}
ANNUAL_MEMBERSHIP_FEE_POSTAL_KANA_GROUPS = (
    ("a", "あ", "あ行"),
    ("ka", "か", "か行"),
    ("sa", "さ", "さ行"),
    ("ta", "た", "た行"),
    ("na", "な", "な行"),
    ("ha", "は", "は行"),
    ("ma", "ま", "ま行"),
    ("ya", "や", "や行"),
    ("ra", "ら", "ら行"),
    ("wa", "わ", "わ行"),
    ("digit", "0-9", "数字"),
    ("other", "他", "その他"),
)


def normalize_annual_membership_fee_payment_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in ANNUAL_MEMBERSHIP_FEE_PAYMENT_STATUS_LABELS:
        return normalized
    return ""


def _annual_membership_fee_check_sheet_column_count(member_count: int) -> int:
    if member_count <= 70:
        return 2
    if member_count <= 110:
        return 3
    if member_count <= 155:
        return 4
    return 5


def _annual_membership_fee_check_sheet_density(member_count: int) -> str:
    if member_count <= 110:
        return "normal"
    if member_count <= 210:
        return "compact"
    return "tight"


def _chunk_annual_membership_fee_receipts(receipts: list[dict]) -> list[list[dict | None]]:
    pages: list[list[dict | None]] = []
    for index in range(0, len(receipts), ANNUAL_MEMBERSHIP_FEE_RECEIPTS_PER_PAGE):
        page = list(receipts[index : index + ANNUAL_MEMBERSHIP_FEE_RECEIPTS_PER_PAGE])
        if len(page) < ANNUAL_MEMBERSHIP_FEE_RECEIPTS_PER_PAGE:
            page.extend([None] * (ANNUAL_MEMBERSHIP_FEE_RECEIPTS_PER_PAGE - len(page)))
        pages.append(page)
    return pages


def _annual_membership_fee_receipt_temple_name(identity_name: str) -> str:
    normalized_parts = [part for part in re.split(r"[\s\u3000]+", (identity_name or "").strip()) if part]
    if not normalized_parts:
        return "寺院名"
    return normalized_parts[-1]


def _normalize_household_ledger_category(ledger_category: str | None) -> str:
    return normalize_ledger_category_code(ledger_category)


def _normalize_annual_membership_fee_kana(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    converted: list[str] = []
    for char in normalized:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            converted.append(chr(code - 0x60))
        elif char in {" ", "　", "-", "ｰ", "－", "―"}:
            continue
        else:
            converted.append(char.lower())
    return "".join(converted)


def _annual_membership_fee_postal_group_key(*, kana: str | None, name: str | None) -> str:
    normalized = _normalize_annual_membership_fee_kana(kana) or _normalize_annual_membership_fee_kana(name)
    if not normalized:
        return "other"
    first = normalized[0]
    if first.isdigit():
        return "digit"
    if first in {"ぁ", "あ", "ぃ", "い", "ぅ", "う", "ぇ", "え", "ぉ", "お", "ゔ"}:
        return "a"
    if first in {"か", "が", "き", "ぎ", "く", "ぐ", "け", "げ", "こ", "ご"}:
        return "ka"
    if first in {"さ", "ざ", "し", "じ", "す", "ず", "せ", "ぜ", "そ", "ぞ"}:
        return "sa"
    if first in {"た", "だ", "ち", "ぢ", "っ", "つ", "づ", "て", "で", "と", "ど"}:
        return "ta"
    if first in {"な", "に", "ぬ", "ね", "の"}:
        return "na"
    if first in {"は", "ば", "ぱ", "ひ", "び", "ぴ", "ふ", "ぶ", "ぷ", "へ", "べ", "ぺ", "ほ", "ぼ", "ぽ"}:
        return "ha"
    if first in {"ま", "み", "む", "め", "も"}:
        return "ma"
    if first in {"や", "ゃ", "ゆ", "ゅ", "よ", "ょ"}:
        return "ya"
    if first in {"ら", "り", "る", "れ", "ろ"}:
        return "ra"
    if first in {"わ", "ゎ", "を", "ん"}:
        return "wa"
    return "other"


def _build_annual_membership_fee_postal_groups(rows: list[dict]) -> list[dict]:
    groups_by_key = {
        key: {
            "key": key,
            "label": label,
            "description": description,
            "anchor_id": f"dues-postal-group-{key}",
            "rows": [],
        }
        for key, label, description in ANNUAL_MEMBERSHIP_FEE_POSTAL_KANA_GROUPS
    }
    for row in rows:
        group_key = _annual_membership_fee_postal_group_key(
            kana=row.get("head_name_kana"),
            name=row.get("head_name"),
        )
        groups_by_key.setdefault(
            group_key,
            {
                "key": group_key,
                "label": group_key,
                "description": group_key,
                "anchor_id": f"dues-postal-group-{group_key}",
                "rows": [],
            },
        )["rows"].append(row)
    return [
        groups_by_key[key]
        for key, _label, _description in ANNUAL_MEMBERSHIP_FEE_POSTAL_KANA_GROUPS
        if groups_by_key[key]["rows"]
    ]


def _build_annual_membership_fee_postal_scan_candidate_map(
    *,
    source_record: LegacySource,
    year: int,
) -> dict[str, list[dict]]:
    candidate_map: dict[str, list[dict]] = {}
    scans = AnnualMembershipFeePostalScan.objects.filter(
        source=source_record,
        year=year,
        payment__isnull=True,
    ).exclude(status=AnnualMembershipFeePostalScan.Status.CHECKED)
    from apps.office.services import annual_membership_fee_postal_scans as postal_scan_services

    for scan in scans:
        if scan.page_count > 1 and scan.page_number == 1:
            continue
        candidates = list((scan.candidate_payload or {}).get("candidates") or [])
        if not candidates:
            continue
        receipt_details = postal_scan_services.postal_scan_receipt_details_for_display(scan)
        top_candidate = candidates[0]
        score = int(top_candidate.get("score") or 0)
        household_id = str(top_candidate.get("legacy_household_id") or "").strip()
        if not household_id or score < 90:
            continue
        candidate_map.setdefault(household_id, []).append(
            {
                "id": scan.id,
                "original_filename": scan.original_filename,
                "page_number": scan.page_number,
                "page_count": scan.page_count,
                "statement_date": scan.statement_date,
                "score": score,
                "match_reasons": list(top_candidate.get("match_reasons") or []),
                "has_crop": bool(scan.crop_storage_key),
                "candidate_query": (scan.candidate_payload or {}).get("query", ""),
                "receipt_details": receipt_details,
            }
        )
    for candidates in candidate_map.values():
        candidates.sort(key=lambda item: (-item["score"], item["original_filename"], item["id"]))
    return candidate_map


def _annual_membership_fee_exclusion_reason(
    *,
    household: Household,
    profile: HouseholdProfile | None,
) -> str:
    if _normalize_household_ledger_category(household.ledger_category) == LEDGER_CATEGORY_WOMENS_ASSOCIATION:
        return "婦人会は護持会費の請求対象外です。"
    if profile is None:
        return "送付区分が未設定のため請求対象外です。"
    delivery_method = (profile.delivery_method or "").strip()
    if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT:
        if profile.district_id:
            return ""
        return "地区所属ですが地区が未設定のため請求対象外です。"
    if delivery_method == HOUSEHOLD_DELIVERY_POSTAL:
        return ""
    if delivery_method == HOUSEHOLD_DELIVERY_NONE:
        return ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON
    return "送付区分が未設定のため請求対象外です。"


def _build_annual_membership_fee_hand_delivery_rows(
    *,
    batch: ImportBatch,
    source_record: LegacySource,
    year: int,
) -> list[dict]:
    del batch
    canonical_population.canonical_provenance_import_batch(
        source_id=source_record.source_id,
    )
    households = list(
        Household.objects.filter(deleted_at__isnull=True).select_related("head_person")
    )
    household_ids = [household.household_uid for household in households]
    profile_map = {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.select_related("district").filter(
            source=source_record,
            household_uid__in=household_ids,
        )
    }
    setting = (
        AnnualMembershipFeeSetting.objects.filter(source=source_record, year=year).first()
        or AnnualMembershipFeeSetting(source=source_record, year=year)
    )
    default_amount = setting.default_amount or Decimal("0")
    payment_map = {
        payment.household_uid: payment
        for payment in AnnualMembershipFeePayment.objects.filter(
            source=source_record,
            year=year,
            household_uid__in=household_ids,
        )
    }
    rows: list[dict] = []
    for household in households:
        profile = profile_map.get(household.household_uid)
        payment = payment_map.get(household.household_uid)
        exclusion_reason = _annual_membership_fee_exclusion_reason(household=household, profile=profile)
        if exclusion_reason:
            continue
        delivery_method = profile.delivery_method if profile is not None else ""
        if delivery_method != HOUSEHOLD_DELIVERY_DISTRICT:
            continue
        district_name = (payment.district_name_snapshot or "").strip() if payment is not None else ""
        district_sort_order = 9999
        district_id = None
        if profile is not None and profile.district_id:
            district_id = profile.district_id
            district_sort_order = profile.district.sort_order
            if not district_name and profile.district is not None:
                district_name = profile.district.name
        if not district_name:
            district_name = "地区未設定"
        head_name = (payment.household_name_snapshot or "").strip() if payment is not None else ""
        if not head_name:
            head_name = _household_display_head_name(household)
        head_name = head_name or household.household_uid
        head_name_kana = _household_display_head_name_kana(household)
        amount = payment.amount if payment is not None else default_amount
        amount_text = str(amount or Decimal("0"))
        rows.append(
            {
                "household_id": household.household_uid,
                "head_name": head_name,
                "head_name_kana": head_name_kana,
                "district_id": district_id,
                "district_name": district_name,
                "district_sort_order": district_sort_order,
                "amount_text": amount_text,
                "is_paid": payment is not None,
            }
        )
    rows.sort(
        key=lambda row: (
            row["district_sort_order"],
            row["district_name"],
            (row["head_name_kana"] or "").lower(),
            row["head_name"].lower(),
            row["household_id"],
        )
    )
    return rows


def _build_annual_membership_fee_receipt_context(
    *,
    source_id: str,
    batch: ImportBatch,
    source_record: LegacySource,
    year: int,
) -> dict:
    temple_identity = temple_identity_services.current_temple_identity()
    temple_name = _annual_membership_fee_receipt_temple_name(temple_identity.get("name", ""))
    temple_membership_label = f"{temple_name}護持会"
    receipt_rows = []
    for row in _build_annual_membership_fee_hand_delivery_rows(
        batch=batch,
        source_record=source_record,
        year=year,
    ):
        receipt_rows.append(
            {
                **row,
                "amount_zenkaku": memorial_dates._to_zenkaku_digits(row["amount_text"]),
                "subject_line": (
                    f"但し、{memorial_dates._to_wareki_year_numeric(year)}年度"
                    f"{temple_membership_label}費として"
                ),
                "receipt_date_line": f"{memorial_dates._to_wareki_year_numeric(year)}年　5月　　　日",
                "temple_membership_label": temple_membership_label,
            }
        )
    receipt_pages = _chunk_annual_membership_fee_receipts(receipt_rows)
    return {
        "selected_source_id": source_id,
        "year": year,
        "available": bool(receipt_rows),
        "receipt_rows": receipt_rows,
        "receipt_pages": receipt_pages,
        "receipt_count": len(receipt_rows),
        "page_count": len(receipt_pages),
        "fees_url": _annual_membership_fees_url(year=year),
        "current_url": _annual_membership_fee_receipts_url(year=year),
    }


def _build_annual_membership_fee_check_sheet_context(
    *,
    source_id: str,
    batch: ImportBatch,
    source_record: LegacySource,
    year: int,
) -> dict:
    rows = _build_annual_membership_fee_hand_delivery_rows(
        batch=batch,
        source_record=source_record,
        year=year,
    )
    district_groups_by_key: dict[tuple[int, str, int | None], dict] = {}
    for row in rows:
        key = (row["district_sort_order"], row["district_name"], row["district_id"])
        group = district_groups_by_key.setdefault(
            key,
            {
                "district_id": row["district_id"],
                "name": row["district_name"],
                "sort_order": row["district_sort_order"],
                "rows": [],
            },
        )
        group["rows"].append(row)
    district_groups = sorted(
        district_groups_by_key.values(),
        key=lambda group: (group["sort_order"], group["name"]),
    )
    for group in district_groups:
        member_count = len(group["rows"])
        group["member_count"] = member_count
        group["column_count"] = _annual_membership_fee_check_sheet_column_count(member_count)
        group["density"] = _annual_membership_fee_check_sheet_density(member_count)
    return {
        "selected_source_id": source_id,
        "year": year,
        "available": bool(district_groups),
        "district_groups": district_groups,
        "district_count": len(district_groups),
        "member_count": len(rows),
        "column_count": _annual_membership_fee_check_sheet_column_count(len(rows)),
        "density": _annual_membership_fee_check_sheet_density(len(rows)),
        "fees_url": _annual_membership_fees_url(year=year),
        "current_url": _annual_membership_fee_check_sheets_url(year=year),
    }


def _build_annual_membership_fee_context(
    *,
    source_id: str,
    batch: ImportBatch,
    source_record: LegacySource,
    year: int,
    setting_form: AnnualMembershipFeeSettingForm,
    row_form_overrides: dict[str, AnnualMembershipFeeEntryForm] | None = None,
    payment_status: str = "",
) -> dict:
    row_form_overrides = row_form_overrides or {}
    payment_status = normalize_annual_membership_fee_payment_status(payment_status)
    del batch
    canonical_population.canonical_provenance_import_batch(
        source_id=source_record.source_id,
    )
    households = list(
        Household.objects.filter(deleted_at__isnull=True).select_related("head_person")
    )
    households.sort(
        key=lambda row: (
            (_household_display_head_name_kana(row) or "").lower(),
            (_household_display_head_name(row) or "").lower(),
            row.legacy_household_id,
        )
    )
    household_ids = [household.household_uid for household in households]
    profile_map = {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.select_related("district").filter(
            source=source_record,
            household_uid__in=household_ids,
        )
    }
    payment_map = {
        payment.household_uid: payment
        for payment in AnnualMembershipFeePayment.objects.filter(
            source=source_record,
            year=year,
            household_uid__in=household_ids,
        )
    }
    postal_scan_candidate_map = _build_annual_membership_fee_postal_scan_candidate_map(
        source_record=source_record,
        year=year,
    )
    district_groups: dict[str, dict] = {}
    postal_rows: list[dict] = []
    other_rows: list[dict] = []
    paid_count = 0
    total_amount = Decimal("0")
    total_households = 0
    default_amount = getattr(setting_form.instance, "default_amount", Decimal("0")) or Decimal("0")

    for household in households:
        household_id = household.household_uid
        profile = profile_map.get(household_id)
        payment = payment_map.get(household_id)
        exclusion_reason = _annual_membership_fee_exclusion_reason(household=household, profile=profile)
        is_billable = not exclusion_reason
        if payment is not None and is_billable:
            paid_count += 1
            total_amount += payment.amount or Decimal("0")
        if is_billable:
            total_households += 1
        if payment_status == "billable" and not is_billable:
            continue
        if payment_status == "paid" and not (is_billable and payment is not None):
            continue
        if payment_status == "unpaid" and not (is_billable and payment is None):
            continue
        postal_scan_candidates = postal_scan_candidate_map.get(household_id, [])
        postal_received_on = (
            postal_scan_candidates[0].get("statement_date") if postal_scan_candidates else None
        )
        initial = {
            "paid": payment is not None,
            "received_on": payment.received_on
            if payment is not None
            else postal_received_on or timezone.localdate(),
            "is_exception": payment.is_exception if payment is not None else False,
            "amount_override": (
                payment.amount if payment is not None and payment.is_exception else ""
            ),
            "note": payment.note if payment is not None else "",
        }
        form = row_form_overrides.get(household_id) or AnnualMembershipFeeEntryForm(
            prefix=f"row-{household_id}",
            initial=initial,
        )
        row = {
            "household_id": household_id,
            "head_name": _household_display_head_name(household),
            "head_name_kana": _household_display_head_name_kana(household),
            "postal_code": household.postal_code,
            "address": " ".join(
                [part for part in [household.address_line1, household.address_line2, household.address_line3] if part]
            ),
            "phone": household.phone or household.mobile,
            "delivery_method": profile.delivery_method if profile is not None else "",
            "delivery_label": HOUSEHOLD_DELIVERY_LABELS.get(
                profile.delivery_method if profile is not None else "",
                "未設定",
            ),
            "district_name": profile.district.name if profile is not None and profile.district_id else "",
            "district_sort_order": profile.district.sort_order if profile is not None and profile.district_id else 9999,
            "default_amount": default_amount,
            "saved_amount": payment.amount if payment is not None else None,
            "saved_received_on": payment.received_on if payment is not None else None,
            "form": form,
            "is_paid": payment is not None,
            "is_exception": payment.is_exception if payment is not None else False,
            "is_billable": is_billable,
            "billing_note": exclusion_reason,
            "postal_scan_candidates": postal_scan_candidates,
        }
        delivery_method = profile.delivery_method if profile is not None else ""
        if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT and profile is not None and profile.district_id:
            bucket = district_groups.setdefault(
                profile.district.name,
                {
                    "name": profile.district.name,
                    "sort_order": profile.district.sort_order,
                    "anchor_id": f"dues-district-{profile.district_id}",
                    "rows": [],
                },
            )
            bucket["rows"].append(row)
        elif delivery_method == HOUSEHOLD_DELIVERY_POSTAL:
            postal_rows.append(row)
        else:
            other_rows.append(row)

    district_group_list = sorted(
        district_groups.values(),
        key=lambda item: (item["sort_order"], item["name"]),
    )
    postal_groups = _build_annual_membership_fee_postal_groups(postal_rows)
    unpaid_count = max(total_households - paid_count, 0)
    filtered_household_count = {
        "billable": total_households,
        "paid": paid_count,
        "unpaid": unpaid_count,
    }.get(payment_status, total_households)
    return {
        "selected_source_id": source_id,
        "year": year,
        "available_years": [year - 1, year, year + 1],
        "setting_form": setting_form,
        "default_amount": default_amount,
        "district_groups": district_group_list,
        "district_jump_links": [
            {
                "label": f"{group['sort_order']}. {group['name']}",
                "anchor_id": group["anchor_id"],
            }
            for group in district_group_list
        ],
        "postal_rows": postal_rows,
        "postal_groups": postal_groups,
        "postal_jump_links": [
            {
                "label": group["label"],
                "description": group["description"],
                "anchor_id": group["anchor_id"],
            }
            for group in postal_groups
        ],
        "other_rows": other_rows,
        "paid_count": paid_count,
        "payment_status": payment_status,
        "payment_status_label": ANNUAL_MEMBERSHIP_FEE_PAYMENT_STATUS_LABELS.get(
            payment_status,
            "",
        ),
        "filtered_household_count": filtered_household_count,
        "all_fees_url": _annual_membership_fees_url(year=year),
        "billable_fees_url": _annual_membership_fees_url(
            year=year,
            payment_status="billable",
        ),
        "paid_fees_url": _annual_membership_fees_url(year=year, payment_status="paid"),
        "unpaid_fees_url": _annual_membership_fees_url(year=year, payment_status="unpaid"),
        "hand_delivery_check_sheet_url": _annual_membership_fee_check_sheets_url(
            year=year,
            mode="print",
        ),
        "hand_delivery_check_sheet_review_url": _annual_membership_fee_check_sheets_url(
            year=year,
            mode="review",
        ),
        "hand_delivery_receipt_url": _annual_membership_fee_receipts_url(year=year),
        "postal_scan_review_url": _annual_membership_fee_postal_scans_url(year=year),
        "unpaid_count": unpaid_count,
        "total_amount": total_amount,
        "total_households": total_households,
        "current_url": _annual_membership_fees_url(
            year=year,
            payment_status=payment_status,
        ),
    }


__all__ = [
    "_annual_membership_fee_receipt_temple_name",
    "_build_annual_membership_fee_check_sheet_context",
    "_build_annual_membership_fee_context",
    "_build_annual_membership_fee_receipt_context",
    "normalize_annual_membership_fee_payment_status",
]
