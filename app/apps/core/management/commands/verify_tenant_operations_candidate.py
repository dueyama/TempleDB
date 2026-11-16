from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import tenant_operations_candidate_activation


class Command(BaseCommand):
    requires_system_checks: list[str] = []
    help = (
        "Read-only verify an activated tenant-pack candidate before starting "
        "the staging service."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--candidate-tenant-root", type=Path, required=True)
        parser.add_argument("--expected-git-commit", required=True)
        parser.add_argument("--expected-runtime-git-commit")
        parser.add_argument("--expected-archive-sha256", required=True)
        parser.add_argument("--expected-installation-id", required=True)
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--candidate-owner-uid", type=int)

    def handle(self, *args, **options) -> None:
        del args
        try:
            result = tenant_operations_candidate_activation.verify_tenant_operations_candidate(
                candidate_tenant_root=options["candidate_tenant_root"],
                expected_git_commit=options["expected_git_commit"],
                expected_runtime_git_commit=options[
                    "expected_runtime_git_commit"
                ],
                expected_archive_sha256=options["expected_archive_sha256"],
                expected_installation_id=options["expected_installation_id"],
                expected_database_name=options["expected_database_name"],
                require_activated=True,
                expected_candidate_owner_uid=options["candidate_owner_uid"],
            )
        except tenant_operations_candidate_activation.TenantOperationsCandidateActivationError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(
                "activated tenant operations candidateを確認できませんでした。"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "activated product staging candidateを確認しました。"
                f" root={result.candidate_root}"
                f" database={result.database_name}"
                f" oid={result.database_oid}"
                " connections_allowed=true"
            )
        )
