from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import runtime_identity_guard


class Command(BaseCommand):
    requires_system_checks: list[str] = []
    requires_migrations_checks = False
    help = (
        "Verify the active product/PostgreSQL instance binding against the live "
        "database without mutation."
    )

    def handle(self, *args, **options):
        del args, options
        try:
            verified = runtime_identity_guard.assert_product_database_binding()
        except runtime_identity_guard.RuntimeIdentityGuardError as exc:
            raise CommandError(str(exc)) from exc
        if verified is None:  # Defensive: required=True must never return None.
            raise CommandError("製品DB binding照合が実行されませんでした。")
        self.stdout.write(
            self.style.SUCCESS(
                "Product database binding verified: "
                f"runtime_kind=product, postgresql_major={verified.postgresql_major}."
            )
        )
