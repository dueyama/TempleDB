from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.imports import canonical_population, source_runtime, synthetic_household_runtime
from apps.imports.models import Household


class Command(BaseCommand):
    help = "Replace the head person of extinct households with a synthetic extinct-household head."

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
            help="Apply the extinct-household head assignment. Without this flag the command runs in dry-run mode.",
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
        result: dict[str, object] = {
            "mode": "execute" if options.get("execute") else "dry-run",
            "source_id": source_id,
            "batch_id": batch.id,
            "prepared_snapshot_id": batch.prepared_snapshot_id,
            "requested_household_ids": household_ids,
            "households": summaries,
            "eligible_household_count": sum(1 for summary in summaries if summary["eligible"]),
            "ineligible_household_count": sum(1 for summary in summaries if not summary["eligible"]),
            "created_extinct_head_count": 0,
            "reused_extinct_head_count": 0,
            "updated_household_count": 0,
        }

        if options.get("execute"):
            ineligible_ids = [
                summary["legacy_household_id"] for summary in summaries if not bool(summary["eligible"])
            ]
            if ineligible_ids:
                raise CommandError(
                    "Cannot mark households extinct while living current residents remain: "
                    + ", ".join(ineligible_ids)
                )

            with transaction.atomic():
                for household in households:
                    identity = synthetic_household_runtime.resolve_extinct_household_identity(household)
                    for virtual_head in synthetic_household_runtime.active_virtual_household_heads(household):
                        virtual_head.mark_deleted(
                            editor_label="system",
                            note="絶家 synthetic head へ置換",
                        )
                        virtual_head.save(
                            update_fields=["deleted_at", "deleted_by", "deletion_note", "updated_at"]
                        )

                    _head, created = synthetic_household_runtime.get_or_create_extinct_household_head(
                        household=household,
                        identity=identity,
                    )
                    if created:
                        result["created_extinct_head_count"] = int(result["created_extinct_head_count"]) + 1
                    else:
                        result["reused_extinct_head_count"] = int(result["reused_extinct_head_count"]) + 1

                    previous_notes = household.notes or ""
                    synthetic_household_runtime.append_household_note(
                        household,
                        synthetic_household_runtime.EXTINCT_HOUSEHOLD_NOTE,
                    )
                    if household.notes != previous_notes:
                        household.save(update_fields=["notes", "updated_at"])
                    result["updated_household_count"] = int(result["updated_household_count"]) + 1

        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    def _parse_household_ids(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            household_id = (value or "").strip()
            if household_id and household_id not in normalized:
                normalized.append(household_id)
        if not normalized:
            raise CommandError("At least one --household-id is required.")
        return normalized

    def _build_summary(self, household: Household) -> dict[str, object]:
        identity = synthetic_household_runtime.resolve_extinct_household_identity(household)
        living_people = synthetic_household_runtime.active_real_current_people(household)
        eligible = not living_people
        return {
            "legacy_household_id": household.household_uid,
            "eligible": eligible,
            "reason": (
                ""
                if eligible
                else "living current residents remain: "
                + ", ".join(
                    f"{person.person_uid}:{person.name or person.person_uid}" for person in living_people
                )
            ),
            "base_head_name": identity.base_name,
            "base_head_kana": identity.base_kana,
            "new_head_name": identity.display_name,
            "new_head_kana": identity.display_kana,
        }
