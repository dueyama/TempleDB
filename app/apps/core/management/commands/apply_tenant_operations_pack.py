from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import tenant_operations_pack_apply


class Command(BaseCommand):
    help = (
        "Create a frozen PostgreSQL and tenant-root staging candidate from a "
        "verified tenant operations pack without activating services."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--archive", type=Path, required=True)
        parser.add_argument("--expected-archive-sha256", required=True)
        parser.add_argument("--expected-git-commit", required=True)
        parser.add_argument("--expected-installation-id", required=True)
        parser.add_argument("--candidate-tenant-root", type=Path, required=True)
        parser.add_argument("--confirm-candidate-tenant-root", required=True)
        parser.add_argument("--target-database-name", required=True)
        parser.add_argument("--confirm-target-database-name", required=True)
        parser.add_argument(
            "--expected-target-postgresql-major",
            type=int,
            required=True,
        )

    def handle(self, *args, **options) -> None:
        del args
        try:
            result = tenant_operations_pack_apply.apply_tenant_operations_pack(
                options["archive"],
                expected_archive_sha256=options["expected_archive_sha256"],
                expected_git_commit=options["expected_git_commit"],
                expected_installation_id=options["expected_installation_id"],
                candidate_tenant_root=options["candidate_tenant_root"],
                confirm_candidate_tenant_root=options[
                    "confirm_candidate_tenant_root"
                ],
                target_database_name=options["target_database_name"],
                confirm_target_database_name=options[
                    "confirm_target_database_name"
                ],
                expected_target_postgresql_major=options[
                    "expected_target_postgresql_major"
                ],
            )
        except tenant_operations_pack_apply.TenantOperationsPackApplyError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(
                "tenant operations packの隔離applyを安全に完了できませんでした。"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "凍結staging candidateを作成しました。"
                f" root={result.candidate_root}"
                f" database={result.database_name}"
                f" oid={result.database_oid}"
                f" postgresql={result.source_postgresql_major}"
                f"->{result.target_postgresql_major}"
                " connections_allowed=false"
            )
        )
