from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population
from .auxiliary_postal_support import _postal_compare_normalized_text
from .model_households import safe_display_head_name
from .models import Household
from .runtime_shared import _clean_value, _int_sort, _sort_text


def _runtime_module():
    from . import data_quality_runtime

    return data_quality_runtime


def _address_line2_duplicate_candidates(source_id: str) -> list[dict]:
    try:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
        households = list(
            Household.objects.filter(
                deleted_at__isnull=True,
            ).order_by("household_uid")
        )
    except (OperationalError, ProgrammingError):
        return []

    candidates: list[dict] = []
    for household in households:
        overlap_text = _duplicated_address_line2_suffix(
            household.address_line1,
            household.address_line2,
        )
        if not overlap_text:
            continue
        candidates.append(
            {
                "household_id": household.household_uid,
                "household_name": safe_display_head_name(household),
                "address_line1": _clean_value(household.address_line1),
                "address_line2": _clean_value(household.address_line2),
                "overlap_text": overlap_text,
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            _sort_text(item.get("household_name")),
            _int_sort(item.get("household_id")),
        ),
    )


def _duplicated_address_line2_suffix(address_line1: str | None, address_line2: str | None) -> str:
    normalized_line1 = _postal_compare_normalized_text(address_line1)
    normalized_line2 = _postal_compare_normalized_text(address_line2)
    cleaned_line2 = _clean_value(address_line2)
    if not normalized_line1 or not normalized_line2 or not cleaned_line2:
        return ""
    if len(normalized_line2) < 3:
        return ""
    if "方" in cleaned_line2:
        return ""
    if not any(char.isdigit() for char in normalized_line2):
        return ""
    if normalized_line1.endswith(normalized_line2):
        return cleaned_line2
    return ""
