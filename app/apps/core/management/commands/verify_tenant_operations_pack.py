from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import tenant_operations_pack_verification


class Command(BaseCommand):
    requires_system_checks: list[str] = []
    help = (
        "Verify a tenant operations pack without extracting files, writing a database, "
        "or changing machine services."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--archive", type=Path, required=True)
        parser.add_argument("--expected-archive-sha256", required=True)
        parser.add_argument("--expected-git-commit", required=True)
        parser.add_argument("--expected-installation-id", required=True)

    def handle(self, *args, **options) -> None:
        del args
        try:
            result = (
                tenant_operations_pack_verification.verify_tenant_operations_pack(
                    options["archive"],
                    expected_archive_sha256=options["expected_archive_sha256"],
                    expected_git_commit=options["expected_git_commit"],
                    expected_installation_id=options["expected_installation_id"],
                )
            )
        except tenant_operations_pack_verification.TenantOperationsPackVerificationError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(
                "[TENANT_PACK_VERIFY_UNEXPECTED_FAILURE] "
                "運用パック検証を安全に完了できませんでした。"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "テナント運用パックのread-only検証に成功しました。\n"
                + json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            )
        )
