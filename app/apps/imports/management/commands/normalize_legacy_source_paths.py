from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.imports import source_registry_runtime
from apps.imports.models import LegacySource


class Command(BaseCommand):
    help = (
        "Normalize LegacySource.file_path to match the current runtime source registry. "
        "LegacySource.file_path is treated as a legacy mirror; source authority comes from "
        "source_id + runtime registry."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply DB updates. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        del args
        execute = bool(options["execute"])
        results = []
        updated_count = 0
        skipped_count = 0

        for source in LegacySource.objects.order_by("source_id"):
            result = self._build_result(source)
            if execute and result["will_update"]:
                updated_count += self._apply_updates(source, result)
                result["updated"] = True
            else:
                result["updated"] = False
            if not result["registry_entry_present"]:
                skipped_count += 1
            results.append(result)

        payload = {
            "mode": "execute" if execute else "dry-run",
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "source_count": len(results),
            "sources": results,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))

    def _build_result(self, source: LegacySource) -> dict:
        try:
            summary = source_registry_runtime.source_summary(source.source_id)
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return {
                "source_id": source.source_id,
                "registry_entry_present": False,
                "legacy_file_path": source.file_path,
                "legacy_file_name": source.file_name,
                "legacy_sha256": source.sha256,
                "desired_file_path": "",
                "desired_file_name": "",
                "desired_sha256": "",
                "file_exists": False,
                "will_update": False,
                "changes": [],
                "warning": "runtime registry に source_id が無いため更新をスキップしました。",
            }

        resolved_path = Path(summary["resolved_path"])
        desired_file_path = str(resolved_path)
        desired_file_name = resolved_path.name
        desired_sha256 = summary.get("sha256") or ""
        changes = []
        if source.file_path != desired_file_path:
            changes.append("file_path")
        if source.file_name != desired_file_name:
            changes.append("file_name")
        if source.sha256 != desired_sha256:
            changes.append("sha256")
        return {
            "source_id": source.source_id,
            "registry_entry_present": True,
            "legacy_file_path": source.file_path,
            "legacy_file_name": source.file_name,
            "legacy_sha256": source.sha256,
            "desired_file_path": desired_file_path,
            "desired_file_name": desired_file_name,
            "desired_sha256": desired_sha256,
            "file_exists": bool(summary.get("exists")),
            "will_update": bool(changes),
            "changes": changes,
            "warning": "",
        }

    def _apply_updates(self, source: LegacySource, result: dict) -> int:
        updates: list[str] = []
        for field_name in ("file_path", "file_name", "sha256"):
            desired_value = result[f"desired_{field_name}"]
            if getattr(source, field_name) != desired_value:
                setattr(source, field_name, desired_value)
                updates.append(field_name)
        if not updates:
            return 0
        source.save(update_fields=updates + ["updated_at"])
        return 1
