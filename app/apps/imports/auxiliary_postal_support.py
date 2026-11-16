from __future__ import annotations

from . import (
    auxiliary_postal_compare_support,
    auxiliary_postal_import_support,
    auxiliary_postal_label_paging,
    ledger_categories,
)

POSTAL_SKIP_CLASSIFICATIONS = auxiliary_postal_compare_support.POSTAL_SKIP_CLASSIFICATIONS
POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION = (
    auxiliary_postal_import_support.POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION
)
POSTAL_COMPARE_FIELDS = auxiliary_postal_compare_support.POSTAL_COMPARE_FIELDS


def _normalize_ledger_category_code(value: str | None) -> str:
    return ledger_categories.normalize_ledger_category_code(value)


def _ledger_category_label(value: str | None) -> str:
    return ledger_categories.ledger_category_label(value)


def _postal_imported_ledger_category(classification: str | None) -> str:
    return auxiliary_postal_import_support._postal_imported_ledger_category(classification)


def _is_postal_imported_category(classification: str | None) -> bool:
    return auxiliary_postal_import_support._is_postal_imported_category(classification)


def _postal_compare_normalized_text(value: str | None) -> str:
    return auxiliary_postal_compare_support._postal_compare_normalized_text(value)


def _postal_compare_normalized_postal_code(value: str | None) -> str:
    return auxiliary_postal_compare_support._postal_compare_normalized_postal_code(value)


def _postal_compare_normalized_phone(value: str | None) -> str:
    return auxiliary_postal_compare_support._postal_compare_normalized_phone(value)


def _postal_auxiliary_signature(
    *,
    head_name: str | None,
    postal_code: str | None,
    address_line1: str | None,
    address_line2: str | None,
    phone: str | None,
) -> tuple[str, str, str, str, str]:
    return auxiliary_postal_compare_support._postal_auxiliary_signature(
        head_name=head_name,
        postal_code=postal_code,
        address_line1=address_line1,
        address_line2=address_line2,
        phone=phone,
    )


def _postal_auxiliary_signature_from_entry(entry: dict) -> tuple[str, str, str, str, str]:
    return auxiliary_postal_compare_support._postal_auxiliary_signature_from_entry(entry)


def _postal_auxiliary_signature_from_household(household) -> tuple[str, str, str, str, str]:
    return auxiliary_postal_compare_support._postal_auxiliary_signature_from_household(household)


def _create_postal_import_household(
    *,
    batch,
    source_record,
    entry: dict,
):
    return auxiliary_postal_import_support._create_postal_import_household(
        batch=batch,
        source_record=source_record,
        entry=entry,
    )


def _ensure_postal_import_household_category(household, classification: str | None) -> bool:
    return auxiliary_postal_import_support._ensure_postal_import_household_category(
        household,
        classification,
    )


def _postal_label_pages(label_rows: list[dict], *, per_page: int) -> list[list[dict | None]]:
    return auxiliary_postal_label_paging._postal_label_pages(label_rows, per_page=per_page)


def _postal_compare_name_key(row: dict) -> str:
    return auxiliary_postal_compare_support._postal_compare_name_key(row)


def _postal_compare_exact_key(row: dict) -> tuple[str, str, str, str, str]:
    return auxiliary_postal_compare_support._postal_compare_exact_key(row)


def _postal_compare_field_differences(db_row: dict, csv_row: dict) -> list[dict]:
    return auxiliary_postal_compare_support._postal_compare_field_differences(db_row, csv_row)


def _pair_postal_compare_rows_by_key(
    *,
    db_rows: list[dict],
    csv_rows: list[dict],
    key_func,
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    return auxiliary_postal_compare_support._pair_postal_compare_rows_by_key(
        db_rows=db_rows,
        csv_rows=csv_rows,
        key_func=key_func,
    )


def _compare_postal_compare_rows(
    *,
    db_rows: list[dict],
    csv_rows: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    return auxiliary_postal_compare_support._compare_postal_compare_rows(
        db_rows=db_rows,
        csv_rows=csv_rows,
    )


def _build_postal_compare_csv_rows(csv_path) -> list[dict]:
    return auxiliary_postal_compare_support._build_postal_compare_csv_rows(csv_path)


def _build_postal_compare_db_rows(source_id: str, latest_batch) -> list[dict]:
    return auxiliary_postal_compare_support._build_postal_compare_db_rows(source_id, latest_batch)


__all__ = [
    "POSTAL_SKIP_CLASSIFICATIONS",
    "POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION",
    "POSTAL_COMPARE_FIELDS",
    "_normalize_ledger_category_code",
    "_ledger_category_label",
    "_postal_imported_ledger_category",
    "_is_postal_imported_category",
    "_postal_compare_normalized_text",
    "_postal_compare_normalized_postal_code",
    "_postal_compare_normalized_phone",
    "_postal_auxiliary_signature",
    "_postal_auxiliary_signature_from_entry",
    "_postal_auxiliary_signature_from_household",
    "_create_postal_import_household",
    "_ensure_postal_import_household_category",
    "_postal_label_pages",
    "_postal_compare_name_key",
    "_postal_compare_exact_key",
    "_postal_compare_field_differences",
    "_pair_postal_compare_rows_by_key",
    "_compare_postal_compare_rows",
    "_build_postal_compare_csv_rows",
    "_build_postal_compare_db_rows",
]
