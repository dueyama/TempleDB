from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.office.services import google_calendar_sync


class Command(BaseCommand):
    help = "Run Google Calendar bulk sync in the background and write progress into data/runtime/."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--actor",
            default="",
            help="Username of the operator who started the bulk sync.",
        )

    def handle(self, *args, **options) -> None:
        try:
            payload = google_calendar_sync.execute_google_calendar_bulk_sync(
                actor=options["actor"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(payload.get("summary") or "Google Calendar bulk sync completed.")))
