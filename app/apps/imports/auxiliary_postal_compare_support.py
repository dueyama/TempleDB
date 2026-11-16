from __future__ import annotations

import csv
from pathlib import Path

from apps.core.services.contact_normalization import (
    normalize_contact_text,
    normalize_phone_digits,
    normalize_postal_code_digits,
)

from .auxiliary_input_support import (
    _normalize_auxiliary_household_name,
    _normalize_auxiliary_postal_code,
)
from .models import (
    Household,
    ImportBatch,
)
from .postal_recipient_rows import build_postal_recipient_db_rows
from .runtime_shared import _clean_value, _int_sort, _sort_text

POSTAL_SKIP_CLASSIFICATIONS: set[str] = set()
POSTAL_COMPARE_FIELDS = [
    ("recipient_name", "氏名"),
    ("postal_code", "郵便番号"),
    ("address_line1", "住所1"),
    ("address_line2", "住所2"),
    ("phone", "電話"),
]


def _postal_compare_normalized_text(value: str | None) -> str:
    return normalize_contact_text(value)


def _postal_compare_normalized_postal_code(value: str | None) -> str:
    return normalize_postal_code_digits(value)


def _postal_compare_normalized_phone(value: str | None) -> str:
    return normalize_phone_digits(value)


def _postal_auxiliary_signature(
    *,
    head_name: str | None,
    postal_code: str | None,
    address_line1: str | None,
    address_line2: str | None,
    phone: str | None,
) -> tuple[str, str, str, str, str]:
    return (
        _normalize_auxiliary_household_name(head_name),
        _postal_compare_normalized_postal_code(postal_code),
        _postal_compare_normalized_text(address_line1),
        _postal_compare_normalized_text(address_line2),
        _postal_compare_normalized_phone(phone),
    )


def _postal_auxiliary_signature_from_entry(entry: dict) -> tuple[str, str, str, str, str]:
    return _postal_auxiliary_signature(
        head_name=entry.get("head_name"),
        postal_code=entry.get("postal_code"),
        address_line1=entry.get("address_line1"),
        address_line2=entry.get("address_line2"),
        phone=entry.get("phone"),
    )


def _postal_auxiliary_signature_from_household(household: Household) -> tuple[str, str, str, str, str]:
    return _postal_auxiliary_signature(
        head_name=household.display_head_name(),
        postal_code=household.postal_code,
        address_line1=household.address_line1,
        address_line2=household.address_line2,
        phone=household.phone,
    )


def _postal_compare_name_key(row: dict) -> str:
    return _normalize_auxiliary_household_name(row.get("recipient_name"))


def _postal_compare_exact_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        _postal_compare_name_key(row),
        _postal_compare_normalized_postal_code(row.get("postal_code")),
        _postal_compare_normalized_text(row.get("address_line1")),
        _postal_compare_normalized_text(row.get("address_line2")),
        _postal_compare_normalized_phone(row.get("phone")),
    )


def _postal_compare_field_differences(db_row: dict, csv_row: dict) -> list[dict]:
    differences: list[dict] = []
    for field_name, label in POSTAL_COMPARE_FIELDS:
        if field_name == "postal_code":
            is_same = _postal_compare_normalized_postal_code(
                db_row.get(field_name)
            ) == _postal_compare_normalized_postal_code(csv_row.get(field_name))
        elif field_name == "phone":
            is_same = _postal_compare_normalized_phone(
                db_row.get(field_name)
            ) == _postal_compare_normalized_phone(csv_row.get(field_name))
        elif field_name == "recipient_name":
            is_same = _normalize_auxiliary_household_name(
                db_row.get(field_name)
            ) == _normalize_auxiliary_household_name(csv_row.get(field_name))
        else:
            is_same = _postal_compare_normalized_text(
                db_row.get(field_name)
            ) == _postal_compare_normalized_text(csv_row.get(field_name))
        if is_same:
            continue
        differences.append(
            {
                "label": label,
                "db_value": _clean_value(db_row.get(field_name)) or "-",
                "csv_value": _clean_value(csv_row.get(field_name)) or "-",
            }
        )
    return differences


def _pair_postal_compare_rows_by_key(
    *,
    db_rows: list[dict],
    csv_rows: list[dict],
    key_func,
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    db_by_key: dict[tuple, list[dict]] = {}
    csv_by_key: dict[tuple, list[dict]] = {}
    for row in db_rows:
        db_by_key.setdefault(key_func(row), []).append(row)
    for row in csv_rows:
        csv_by_key.setdefault(key_func(row), []).append(row)

    matched_pairs: list[tuple[dict, dict]] = []
    matched_db_ids: set[str] = set()
    matched_csv_ids: set[str] = set()
    for key in sorted(set(db_by_key.keys()) & set(csv_by_key.keys())):
        db_candidates = sorted(
            db_by_key[key],
            key=lambda item: (_sort_text(item.get("recipient_name")), _int_sort(item.get("household_id"))),
        )
        csv_candidates = sorted(
            csv_by_key[key],
            key=lambda item: (item.get("row_number", 0), _sort_text(item.get("recipient_name"))),
        )
        for db_row, csv_row in zip(db_candidates, csv_candidates, strict=False):
            matched_pairs.append((db_row, csv_row))
            matched_db_ids.add(db_row["entry_id"])
            matched_csv_ids.add(csv_row["entry_id"])

    remaining_db_rows = [row for row in db_rows if row["entry_id"] not in matched_db_ids]
    remaining_csv_rows = [row for row in csv_rows if row["entry_id"] not in matched_csv_ids]
    return matched_pairs, remaining_db_rows, remaining_csv_rows


def _compare_postal_compare_rows(
    *,
    db_rows: list[dict],
    csv_rows: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    exact_pairs, remaining_db_rows, remaining_csv_rows = _pair_postal_compare_rows_by_key(
        db_rows=db_rows,
        csv_rows=csv_rows,
        key_func=_postal_compare_exact_key,
    )
    exact_matches = [
        {"db_row": db_row, "csv_row": csv_row}
        for db_row, csv_row in sorted(
            exact_pairs,
            key=lambda item: (item[1].get("row_number", 0), _sort_text(item[0].get("recipient_name"))),
        )
    ]

    mismatch_pairs: list[tuple[dict, dict]] = []
    db_by_name: dict[str, list[dict]] = {}
    csv_by_name: dict[str, list[dict]] = {}
    for row in remaining_db_rows:
        db_by_name.setdefault(_postal_compare_name_key(row), []).append(row)
    for row in remaining_csv_rows:
        csv_by_name.setdefault(_postal_compare_name_key(row), []).append(row)

    matched_db_ids: set[str] = set()
    matched_csv_ids: set[str] = set()
    for name_key in sorted(set(db_by_name.keys()) & set(csv_by_name.keys())):
        if not name_key:
            continue
        db_candidates = db_by_name.get(name_key, [])
        csv_candidates = csv_by_name.get(name_key, [])
        if len(db_candidates) != 1 or len(csv_candidates) != 1:
            continue
        db_row = db_candidates[0]
        csv_row = csv_candidates[0]
        mismatch_pairs.append((db_row, csv_row))
        matched_db_ids.add(db_row["entry_id"])
        matched_csv_ids.add(csv_row["entry_id"])

    field_mismatches = [
        {
            "db_row": db_row,
            "csv_row": csv_row,
            "field_differences": _postal_compare_field_differences(db_row, csv_row),
        }
        for db_row, csv_row in sorted(
            mismatch_pairs,
            key=lambda item: (item[1].get("row_number", 0), _sort_text(item[0].get("recipient_name"))),
        )
    ]
    csv_only = sorted(
        [row for row in remaining_csv_rows if row["entry_id"] not in matched_csv_ids],
        key=lambda item: (item.get("row_number", 0), _sort_text(item.get("recipient_name"))),
    )
    db_only = sorted(
        [row for row in remaining_db_rows if row["entry_id"] not in matched_db_ids],
        key=lambda item: (_sort_text(item.get("recipient_name")), _int_sort(item.get("household_id"))),
    )
    return exact_matches, field_mismatches, csv_only, db_only


def _build_postal_compare_csv_rows(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader, start=1):
            if row_index == 1:
                continue
            raw_head_name = _clean_value(row[0] if len(row) > 0 else "")
            normalized_head_name = _normalize_auxiliary_household_name(raw_head_name)
            classification = _clean_value(row[4] if len(row) > 4 else "")
            if not normalized_head_name:
                continue
            if normalized_head_name == _normalize_auxiliary_household_name("サンプル寺院"):
                continue
            if classification in POSTAL_SKIP_CLASSIFICATIONS:
                continue
            rows.append(
                {
                    "entry_id": f"csv:{row_index}",
                    "row_number": row_index,
                    "recipient_name": raw_head_name,
                    "postal_code": _normalize_auxiliary_postal_code(row[1] if len(row) > 1 else ""),
                    "address_line1": _clean_value(row[2] if len(row) > 2 else ""),
                    "address_line2": _clean_value(row[3] if len(row) > 3 else ""),
                    "phone": _clean_value(row[5] if len(row) > 5 else ""),
                    "note": _clean_value(row[13] if len(row) > 13 else ""),
                    "classification": classification,
                }
            )
    return rows


def _build_postal_compare_db_rows(
    source_id: str,
    latest_batch: ImportBatch,
    *,
    canonical_scope: bool = False,
) -> list[dict]:
    return build_postal_recipient_db_rows(
        source_id,
        latest_batch,
        canonical_scope=canonical_scope,
    )
