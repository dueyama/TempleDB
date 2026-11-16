from __future__ import annotations

from . import (
    household_head_audit_runtime,
    household_head_creation_runtime,
    household_head_sync_runtime,
)
from .models import Household, ImportBatch, Person

VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE = "virtual_household_head"
VIRTUAL_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL = "仮戸主"
VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX = "仮戸主 #P"
VIRTUAL_HOUSEHOLD_HEAD_KANA = "かりこしゅ"


def _current_household_source_mdb_file(household: Household) -> str:
    return household_head_creation_runtime._current_household_source_mdb_file(household)


def person_authority_audit(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
) -> dict:
    return household_head_audit_runtime.person_authority_audit(
        source_id,
        batch=batch,
    )


def sync_household_head_snapshot_from_person(
    *,
    household: Household,
    head_person: Person,
) -> list[str]:
    return household_head_sync_runtime.sync_household_head_snapshot_from_person(
        household=household,
        head_person=head_person,
    )


def create_manual_household_head_person_from_snapshot(household: Household) -> Person | None:
    return household_head_creation_runtime.create_manual_household_head_person_from_snapshot(
        household
    )


def create_virtual_household_head_person(household: Household) -> Person:
    return household_head_creation_runtime.create_virtual_household_head_person(household)


def sync_household_head_authority(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
    dry_run: bool = False,
) -> dict:
    return household_head_sync_runtime.sync_household_head_authority(
        source_id,
        batch=batch,
        dry_run=dry_run,
    )


def _next_virtual_household_head_number(batch: ImportBatch) -> int:
    return household_head_creation_runtime._next_virtual_household_head_number(batch)
