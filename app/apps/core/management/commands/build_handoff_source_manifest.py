from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.services import handoff_repository_snapshot


class Command(BaseCommand):
    help = (
        "Build the allowlisted source manifest used by AI handoff in a Git-less "
        "release copy."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--release-root",
            default=None,
            help=(
                "Explicit release application root. When omitted, BASE_DIR must be "
                "a Git worktree root."
            ),
        )
        parser.add_argument(
            "--source-commit",
            default=None,
            help="Full source Git object ID; required when --release-root has no Git metadata.",
        )
        parser.add_argument(
            "--output",
            choices=handoff_repository_snapshot.SOURCE_MANIFEST_LOCATIONS,
            default="config/handoff_source_manifest.json",
            help="Approved manifest path relative to the release root.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Atomically replace an existing manifest at the approved output path.",
        )

    def handle(self, *args, **options) -> None:
        del args
        explicit_release_root = options["release_root"] is not None
        root = Path(options["release_root"] or settings.BASE_DIR)
        try:
            manifest = handoff_repository_snapshot.build_source_manifest(
                root,
                source_commit=options["source_commit"],
                allow_release_root_inventory=explicit_release_root,
            )
            output_path = handoff_repository_snapshot.write_source_manifest_atomic(
                root,
                manifest,
                output_path=options["output"],
                replace=options["replace"],
            )
        except (OSError, ValueError, handoff_repository_snapshot.RepositorySnapshotError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"AI handoff source manifest written: {output_path} "
                f"({len(manifest['files'])} files)."
            )
        )
