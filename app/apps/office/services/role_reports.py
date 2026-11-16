from __future__ import annotations

from django.db.models import Count
from django.db.utils import OperationalError, ProgrammingError

from apps.imports import canonical_population
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    Household,
    HouseholdProfile,
    Person,
)
from apps.imports.runtime_shared import _clean_value

from .district_authority import (
    district_officer_people_by_district,
    district_officer_people_for_batch,
)
from .label_paging import _postal_label_pages
from .role_report_rows import _build_person_role_roster_rows


def build_district_officer_roster_context(source_id: str) -> dict:
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if canonical_batch is None:
        return {
            "available": False,
            "error_message": "一覧対象の現行台帳がありません。",
            "rows": [],
            "total_count": 0,
        }

    people = [
        person
        for person, _profile in district_officer_people_for_batch(
            source_id,
        )
    ]
    rows = _build_person_role_roster_rows(source_id, people)
    return {
        "available": True,
        "error_message": "",
        "rows": rows,
        "total_count": len(rows),
    }


def build_responsible_officer_roster_context(source_id: str) -> dict:
    canonical_batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    if canonical_batch is None:
        return {
            "available": False,
            "error_message": "一覧対象の現行台帳がありません。",
            "rows": [],
            "total_count": 0,
        }

    people = list(
        Person.objects.select_related("household")
        .filter(
            deleted_at__isnull=True,
            is_responsible_officer=True,
        )
        .order_by(
            "household__head_person__kana",
            "household__head_person__name",
            "kana",
            "name",
            "person_uid",
        )
    )
    rows = _build_person_role_roster_rows(source_id, people)
    return {
        "available": True,
        "error_message": "",
        "rows": rows,
        "total_count": len(rows),
    }


def build_district_officer_delivery_label_context(source_id: str) -> dict:
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
        household_ids = list(
            Household.objects.filter(
                deleted_at__isnull=True,
            ).values_list("household_uid", flat=True)
        )
        district_profiles = list(
            HouseholdProfile.objects.select_related("district").filter(
                source__source_id=source_id,
                household_uid__in=household_ids,
                delivery_method=HOUSEHOLD_DELIVERY_DISTRICT,
                district_id__isnull=False,
            )
        )
        officers_by_district = district_officer_people_by_district(source_id)
        current_person_counts = {
            row["household__household_uid"]: row["count"]
            for row in Person.objects.filter(
                deleted_at__isnull=True,
                family_category=FAMILY_CATEGORY_CURRENT,
                household__household_uid__in=household_ids,
            )
            .values("household__household_uid")
            .annotate(count=Count("id"))
        }
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

    household_ids_by_district: dict[int, list[str]] = {}
    for profile in district_profiles:
        household_ids_by_district.setdefault(profile.district_id, []).append(
            profile.household_uid
        )

    label_rows: list[dict] = []
    skipped_rows: list[dict] = []
    for district in districts:
        district_household_ids = household_ids_by_district.get(district.id, [])
        household_count = len(district_household_ids)
        person_count = sum(
            current_person_counts.get(household_id, 0) for household_id in district_household_ids
        )
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
        officer_household = officer_person.household
        officer_name = (officer_person.name or "").strip() or (
            officer_household.display_head_name() if officer_household is not None else ""
        )
        if household_count <= 0:
            skipped_rows.append(
                {
                    "district_name": district.name,
                    "officer_name": officer_name,
                    "reason": "地区所属の配り物対象がありません",
                }
            )
            continue

        label_rows.append(
            {
                "district_name": district.name,
                "district_short_name": _clean_value(district.short_name) or district.name,
                "officer_name": officer_name,
                "delivery_count": household_count,
                "person_count": person_count,
                "household_count": household_count,
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
