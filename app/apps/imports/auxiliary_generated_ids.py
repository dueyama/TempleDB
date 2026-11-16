from __future__ import annotations

from .models import Household, ImportBatch, Person


def _next_generated_household_id(batch: ImportBatch) -> str:
    max_numeric = 0
    for value in Household.objects.filter(batch=batch).values_list("household_uid", flat=True):
        if str(value).isdigit():
            max_numeric = max(max_numeric, int(str(value)))
    return str(max_numeric + 1)


def _next_generated_household_row_number(batch: ImportBatch) -> int:
    max_row_number = 0
    for value in Household.objects.filter(batch=batch).values_list("source_row_number", flat=True):
        if isinstance(value, int):
            max_row_number = max(max_row_number, value)
    return max_row_number + 1


def _next_generated_person_id(batch: ImportBatch) -> str:
    max_numeric = 0
    for value in Person.objects.filter(batch=batch).values_list("person_uid", flat=True):
        if str(value).isdigit():
            max_numeric = max(max_numeric, int(str(value)))
    return str(max_numeric + 1)
