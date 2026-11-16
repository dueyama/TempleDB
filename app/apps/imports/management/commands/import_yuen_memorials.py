from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.imports import canonical_population, source_runtime, synthetic_household_runtime


class Command(BaseCommand):
    help = "Import detached memorial rows into decade-bucket synthetic yuen households."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            required=True,
            help="CSV file compatible with utb002_memorial_without_household_* exports.",
        )
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Legacy source id. Defaults to the current resolved runtime source.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the import. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options) -> None:
        del args
        csv_path = Path((options.get("csv_path") or "").strip())
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        requested_source_id = (options.get("source_id") or "").strip()
        source_id = source_runtime.operational_source_id(requested_source_id or None)
        batch = canonical_population.canonical_provenance_import_batch(source_id=source_id)
        if batch is None:
            raise CommandError(f"No canonical provenance batch found for source: {source_id}")

        input_rows = self._read_rows(csv_path)
        classification_counts: Counter[str] = Counter()
        ineligible_rows: Counter[str] = Counter()
        bucket_counts: Counter[str] = Counter()
        import_rows: list[dict[str, str]] = []
        unknown_death_year_count = 0

        for raw_row in input_rows:
            row = synthetic_household_runtime.ensure_yuen_input_row(
                raw_row,
                csv_path=str(csv_path),
                snapshot_id=batch.prepared_snapshot_id,
            )
            classification = synthetic_household_runtime.yuen_input_classification(row)
            classification_counts[classification] += 1
            if classification != "standalone_no_db_match":
                ineligible_rows[classification] += 1
                continue
            bucket_label = synthetic_household_runtime.yuen_bucket_label_for_row(row)
            if bucket_label == synthetic_household_runtime.YUEN_UNKNOWN_BUCKET_LABEL:
                unknown_death_year_count += 1
            bucket_counts[bucket_label] += 1
            import_rows.append(row)

        result: dict[str, object] = {
            "mode": "execute" if options.get("execute") else "dry-run",
            "source_id": source_id,
            "batch_id": batch.id,
            "prepared_snapshot_id": batch.prepared_snapshot_id,
            "csv_path": str(csv_path),
            "input_row_count": len(input_rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "import_target_count": len(import_rows),
            "created_household_count": 0,
            "reused_household_count": 0,
            "created_head_count": 0,
            "reused_head_count": 0,
            "created_person_count": 0,
            "skipped_existing_person_count": 0,
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "unknown_death_year_count": unknown_death_year_count,
            "ineligible_rows": dict(sorted(ineligible_rows.items())),
        }

        if options.get("execute"):
            existing_households_by_name = synthetic_household_runtime.yuen_household_maps(batch)
            existing_people_by_key = synthetic_household_runtime.yuen_memorial_people_by_import_key(batch)
            with transaction.atomic():
                for row in import_rows:
                    bucket_label = synthetic_household_runtime.yuen_bucket_label_for_row(row)
                    household, household_created = synthetic_household_runtime.get_or_create_yuen_household(
                        batch=batch,
                        bucket_label=bucket_label,
                        existing_households_by_name=existing_households_by_name,
                    )
                    if household_created:
                        result["created_household_count"] = int(result["created_household_count"]) + 1
                    else:
                        result["reused_household_count"] = int(result["reused_household_count"]) + 1

                    _head, head_created = synthetic_household_runtime.get_or_create_yuen_household_head(household)
                    if head_created:
                        result["created_head_count"] = int(result["created_head_count"]) + 1
                    else:
                        result["reused_head_count"] = int(result["reused_head_count"]) + 1

                    synthetic_household_runtime.ensure_yuen_household_profile(
                        source_record=batch.source,
                        household=household,
                    )
                    _person, person_created = synthetic_household_runtime.get_or_create_yuen_memorial_person(
                        household=household,
                        row=row,
                        existing_people_by_key=existing_people_by_key,
                    )
                    if person_created:
                        result["created_person_count"] = int(result["created_person_count"]) + 1
                    else:
                        result["skipped_existing_person_count"] = int(
                            result["skipped_existing_person_count"]
                        ) + 1

        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    def _read_rows(self, csv_path: Path) -> list[dict[str, str]]:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if "家族ID" not in fieldnames:
                raise CommandError("CSV must contain 家族ID column.")
            return [{str(key): value or "" for key, value in row.items()} for row in reader]
