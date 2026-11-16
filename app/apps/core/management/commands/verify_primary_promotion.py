from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.services.primary_promotion_guard import (
    PrimaryPromotionGuardError,
    verify_primary_promotion,
)


class Command(BaseCommand):
    requires_system_checks: list[str] = []
    help = "Read-only verify a root-authorized in-place primary promotion before serving."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--promotion-receipt", type=Path, required=True)

    def handle(self, *args, **options) -> None:
        del args
        try:
            result = verify_primary_promotion(promotion_receipt=options["promotion_receipt"])
        except PrimaryPromotionGuardError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError("Primary promotion verification failed closed.") from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Primary promotion verified:"
                f" database={result.database_name} oid={result.database_oid}"
                f" installation_id={result.installation_id} runtime_commit={result.runtime_commit}"
                f" receipt_sha256={result.receipt_sha256}"
            )
        )
