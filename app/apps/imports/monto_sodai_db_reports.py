from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from apps.core.services.contact_normalization import normalize_postal_code_digits
from apps.core.services.label_paging import postal_label_pages

from . import canonical_population
from .models import ImportBatch, Person
from .role_roster_rows import build_person_role_roster_rows
from .runtime_shared import _clean_value


def build_monto_sodai_roster_context_for_batch(
    source_id: str,
    latest_batch: ImportBatch | None,
) -> dict:
    if latest_batch is None:
        return {
            "available": False,
            "error_message": "一覧対象の現行台帳がありません。",
            "rows": [],
            "total_count": 0,
        }
    del latest_batch
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
            is_monto_sodai=True,
        )
        .order_by(
            "household__head_person__kana",
            "household__head_person__name",
            "kana",
            "name",
            "person_uid",
        )
    )
    rows = build_person_role_roster_rows(source_id, people)
    return {
        "available": True,
        "error_message": "",
        "rows": rows,
        "total_count": len(rows),
    }


def build_monto_sodai_postal_label_context_for_batch(
    source_id: str,
    latest_batch: ImportBatch | None,
    *,
    include_role_title: bool = True,
) -> dict:
    if latest_batch is None:
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
    del latest_batch
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
        people = list(
            Person.objects.select_related("household")
            .filter(
                deleted_at__isnull=True,
                is_monto_sodai=True,
            )
            .order_by("kana", "name", "household__household_uid", "person_uid")
        )
        roster_rows = build_person_role_roster_rows(source_id, people)
    except (OperationalError, ProgrammingError):
        return {
            "available": False,
            "error_message": "総代ラベルのデータ取得に失敗しました。",
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
    for row in roster_rows:
        person_name = _clean_value(row.get("person_name"))
        postal_code = normalize_postal_code_digits(row.get("postal_code"))
        postal_code_display = ""
        if len(postal_code) == 7:
            postal_code_display = f"〒{postal_code[:3]}-{postal_code[3:]}"
        elif _clean_value(row.get("postal_code")):
            postal_code_display = f"〒{_clean_value(row.get('postal_code'))}"
        address_lines = [line for line in row.get("address_lines", []) if _clean_value(line)]
        if not postal_code_display and not address_lines:
            skipped_rows.append(
                {
                    "person_name": person_name,
                    "household_name": _clean_value(row.get("household_name")),
                    "reason": "郵送先住所が不足しています",
                }
            )
            continue
        label_rows.append(
            {
                "person_name": person_name,
                "household_name": _clean_value(row.get("household_name")),
                "postal_code_display": postal_code_display,
                "address_lines": address_lines,
                "addressee": f"{person_name} 様" if person_name else "",
                "marker_text": "総代" if include_role_title else "",
            }
        )

    label_pages = postal_label_pages(label_rows, per_page=12)
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


__all__ = [
    "build_monto_sodai_postal_label_context_for_batch",
    "build_monto_sodai_roster_context_for_batch",
]
