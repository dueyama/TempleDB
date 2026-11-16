from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.services.kana import normalize_kana_storage
from apps.imports import canonical_population, household_head_runtime, source_runtime
from apps.imports.models import Household, Person


class Command(BaseCommand):
    help = "Apply kana suggestions to runtime persons with an auto-generated flag."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Legacy source id. Defaults to the current resolved runtime source.",
        )
        parser.add_argument(
            "--mapping-file",
            required=True,
            help="JSON file containing a list of kana suggestion objects.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the suggestions. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options) -> None:
        del args
        requested_source_id = (options.get("source_id") or "").strip()
        source_id = source_runtime.operational_source_id(requested_source_id or None)
        batch = canonical_population.canonical_provenance_import_batch(source_id=source_id)
        if batch is None:
            raise CommandError(f"No canonical provenance batch found for source: {source_id}")

        mapping_path = Path(options["mapping_file"]).expanduser()
        if not mapping_path.exists():
            raise CommandError(f"Mapping file not found: {mapping_path}")

        entries = self._load_entries(mapping_path)
        result = {
            "mode": "execute" if options.get("execute") else "dry-run",
            "source_id": source_id,
            "batch_id": batch.id,
            "prepared_snapshot_id": batch.prepared_snapshot_id,
            "mapping_file": str(mapping_path),
            "row_count": len(entries),
            "updated_count": 0,
            "rows": [],
        }

        with transaction.atomic():
            for entry in entries:
                person = self._resolve_person(entry)
                before_kana = person.kana or ""
                before_auto = bool(person.kana_is_auto_generated)
                normalized_kana = normalize_kana_storage((entry.get("kana") or "").strip())
                next_auto = bool(entry.get("kana_is_auto_generated", True))
                update_fields: list[str] = []
                raw_record = dict(person.raw_record or {})
                if person.kana != normalized_kana:
                    person.kana = normalized_kana
                    update_fields.append("kana")
                if person.kana_is_auto_generated != next_auto:
                    person.kana_is_auto_generated = next_auto
                    update_fields.append("kana_is_auto_generated")
                if raw_record.get("ﾌﾘｶﾞﾅ") != normalized_kana:
                    raw_record["ﾌﾘｶﾞﾅ"] = normalized_kana
                    person.raw_record = raw_record
                    update_fields.append("raw_record")

                household_synced = False
                if options.get("execute") and update_fields:
                    person.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])
                    if person.household_id and person.household.head_person_id == person.pk:
                        household = Household.objects.select_related("head_person").get(pk=person.household_id)
                        household_updates = household_head_runtime.sync_household_head_snapshot_from_person(
                            household=household,
                            head_person=person,
                        )
                        if household_updates:
                            household.save(update_fields=[*dict.fromkeys(household_updates), "updated_at"])
                            household_synced = True
                    result["updated_count"] += 1

                result["rows"].append(
                    {
                        "legacy_person_id": person.person_uid,
                        "legacy_household_id": person.household.household_uid,
                        "name": person.name,
                        "before_kana": before_kana,
                        "after_kana": normalized_kana,
                        "before_kana_is_auto_generated": before_auto,
                        "after_kana_is_auto_generated": next_auto,
                        "household_synced": household_synced,
                    }
                )

            if not options.get("execute"):
                transaction.set_rollback(True)

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _load_entries(self, mapping_path: Path) -> list[dict]:
        try:
            payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON mapping file: {exc}") from exc
        if not isinstance(payload, list):
            raise CommandError("Mapping file must contain a JSON array.")
        entries: list[dict] = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise CommandError(f"Mapping row {index} must be an object.")
            legacy_person_id = (item.get("legacy_person_id") or "").strip()
            kana = (item.get("kana") or "").strip()
            if not legacy_person_id:
                raise CommandError(f"Mapping row {index} is missing legacy_person_id.")
            if not kana:
                raise CommandError(f"Mapping row {index} is missing kana.")
            entries.append(
                {
                    "legacy_person_id": legacy_person_id,
                    "legacy_household_id": (item.get("legacy_household_id") or "").strip(),
                    "kana": kana,
                    "kana_is_auto_generated": bool(item.get("kana_is_auto_generated", True)),
                }
            )
        return entries

    def _resolve_person(self, entry: dict) -> Person:
        queryset = Person.objects.select_related("household").filter(
            person_uid=entry["legacy_person_id"],
            deleted_at__isnull=True,
        )
        household_id = entry.get("legacy_household_id") or ""
        if household_id:
            queryset = queryset.filter(household__household_uid=household_id)
        matches = list(queryset.order_by("household__household_uid", "id"))
        if not matches:
            raise CommandError(
                "Person not found in canonical ledger: "
                f"{entry['legacy_person_id']}"
                + (f" (household {household_id})" if household_id else "")
            )
        if len(matches) > 1:
            raise CommandError(
                "Multiple persons matched; specify legacy_household_id for "
                f"{entry['legacy_person_id']}"
            )
        return matches[0]
