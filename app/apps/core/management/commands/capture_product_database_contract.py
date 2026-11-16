from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import runtime_database_contract


class Command(BaseCommand):
    requires_system_checks: list[str] = []
    help = (
        "Capture a read-only, aggregate-only contract for a PostgreSQL product "
        "database and an explicitly selected verified backup."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--backup-run-id",
            type=int,
            required=True,
        )
        parser.add_argument(
            "--expected-postgresql-major",
            type=int,
            required=True,
        )

    def handle(self, *args, **options):
        del args
        try:
            payload = runtime_database_contract.capture_product_database_contract(
                backup_run_id=options["backup_run_id"],
                expected_postgresql_major=options["expected_postgresql_major"],
            )
        except runtime_database_contract.RuntimeDatabaseContractError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
