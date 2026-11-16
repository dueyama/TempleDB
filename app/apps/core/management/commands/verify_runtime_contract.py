from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from apps.core.models import DatabaseRuntimeIdentity


class Command(BaseCommand):
    help = "Verify the effective database engine and runtime identity without mutation."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--engine",
            choices=("postgresql", "sqlite"),
            required=True,
        )
        parser.add_argument(
            "--runtime-kind",
            choices=("demo", "product"),
            required=True,
        )

    def handle(self, *args, **options):
        del args
        expected_engine = options["engine"]
        expected_runtime_kind = options["runtime_kind"]
        configured_engine = getattr(settings, "TEMPLEDB_DATABASE_ENGINE", "")
        connection_engine = connection.vendor

        if configured_engine != expected_engine or connection_engine != expected_engine:
            raise CommandError(
                "Database engine contract mismatch: "
                f"expected={expected_engine}, configured={configured_engine}, "
                f"connection={connection_engine}."
            )

        if expected_engine == "postgresql" and expected_runtime_kind == "demo":
            if not getattr(settings, "TEMPLEDB_POSTGRESQL_DEMO_MODE", False):
                raise CommandError(
                    "PostgreSQL demo runtime guard is not enabled."
                )
        if expected_engine == "sqlite" and getattr(
            settings,
            "TEMPLEDB_POSTGRESQL_DEMO_MODE",
            False,
        ):
            raise CommandError(
                "SQLite runtime unexpectedly has the PostgreSQL demo guard enabled."
            )

        try:
            identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
        except DatabaseRuntimeIdentity.DoesNotExist as exc:
            raise CommandError("Database runtime identity is missing.") from exc
        except DatabaseError as exc:
            raise CommandError(
                "Database runtime identity could not be read."
            ) from exc

        if identity.runtime_kind != expected_runtime_kind:
            raise CommandError(
                "Database runtime kind contract mismatch: "
                f"expected={expected_runtime_kind}, actual={identity.runtime_kind}."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Runtime contract verified: "
                f"engine={expected_engine}, runtime_kind={expected_runtime_kind}."
            )
        )
