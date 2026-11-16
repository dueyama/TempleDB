from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.imports import canonical_population, household_head_runtime, source_runtime
from apps.imports.models import FAMILY_CATEGORY_MEMORIAL, Household


class Command(BaseCommand):
    help = "Assign a virtual household head (仮戸主 #P{n}) to selected runtime households."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Legacy source id. Defaults to the current resolved runtime source.",
        )
        parser.add_argument(
            "--household-id",
            action="append",
            dest="household_ids",
            required=True,
            help="Legacy household id to update. Pass multiple times to update multiple households.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the virtual-head assignment. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options) -> None:
        del args
        requested_source_id = (options.get("source_id") or "").strip()
        source_id = source_runtime.operational_source_id(requested_source_id or None)
        batch = canonical_population.canonical_provenance_import_batch(source_id=source_id)
        if batch is None:
            raise CommandError(f"No canonical provenance batch found for source: {source_id}")

        household_ids = self._parse_household_ids(options.get("household_ids") or [])
        households = list(
            Household.objects.select_related("head_person")
            .filter(
                household_uid__in=household_ids,
                deleted_at__isnull=True,
            )
            .order_by("household_uid")
        )
        found_ids = {household.household_uid for household in households}
        missing_ids = [household_id for household_id in household_ids if household_id not in found_ids]
        if missing_ids:
            raise CommandError(f"Household not found in canonical ledger: {', '.join(missing_ids)}")

        summaries = [self._build_summary(household) for household in households]
        result = {
            "mode": "execute" if options.get("execute") else "dry-run",
            "source_id": source_id,
            "batch_id": batch.id,
            "prepared_snapshot_id": batch.prepared_snapshot_id,
            "households": summaries,
        }

        if options.get("execute"):
            ineligible = [
                summary["legacy_household_id"]
                for summary in summaries
                if not summary["eligible_for_virtual_head"]
            ]
            if ineligible:
                raise CommandError(
                    "Cannot assign virtual head to households with a current living head: "
                    + ", ".join(ineligible)
                )

            with transaction.atomic():
                for household in households:
                    existing_virtual = self._existing_virtual_head_name(household)
                    virtual_head = household_head_runtime.create_virtual_household_head_person(household)
                    update_fields = household_head_runtime.sync_household_head_snapshot_from_person(
                        household=household,
                        head_person=virtual_head,
                    )
                    update_fields.append("updated_at")
                    household.save(update_fields=list(dict.fromkeys(update_fields)))
                    summary = next(
                        item for item in summaries if item["legacy_household_id"] == household.household_uid
                    )
                    summary["assigned_virtual_head"] = virtual_head.name
                    summary["created_new_virtual_head"] = existing_virtual is None

            result["assigned_household_count"] = len(households)
            result["created_virtual_head_count"] = sum(
                1 for item in summaries if item.get("created_new_virtual_head")
            )
        else:
            result["assigned_household_count"] = 0
            result["created_virtual_head_count"] = 0

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _parse_household_ids(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            household_id = (value or "").strip()
            if household_id and household_id not in normalized:
                normalized.append(household_id)
        if not normalized:
            raise CommandError("At least one --household-id is required.")
        return normalized

    def _build_summary(self, household: Household) -> dict:
        head_person = household.head_person
        return {
            "legacy_household_id": household.household_uid,
            "head_person_id": head_person.person_uid if head_person is not None else "",
            "head_person_name": head_person.name if head_person is not None else "",
            "head_person_source_table": head_person.source_table if head_person is not None else "",
            "head_person_family_category": head_person.family_category if head_person is not None else "",
            "head_person_is_deceased": bool(head_person.is_deceased) if head_person is not None else False,
            "existing_virtual_head": self._existing_virtual_head_name(household),
            "eligible_for_virtual_head": self._is_eligible_for_virtual_head(household),
        }

    def _existing_virtual_head_name(self, household: Household) -> str | None:
        existing_virtual_head = (
            household.persons.filter(
                batch=household.batch,
                deleted_at__isnull=True,
                source_table=household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE,
            )
            .order_by("id")
            .first()
        )
        return existing_virtual_head.name if existing_virtual_head is not None else None

    def _is_eligible_for_virtual_head(self, household: Household) -> bool:
        head_person = household.head_person
        if head_person is None:
            return True
        if head_person.source_table == household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE:
            return True
        return bool(head_person.is_deceased or head_person.family_category == FAMILY_CATEGORY_MEMORIAL)
