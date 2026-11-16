from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.office.services import google_calendar_sync


class Command(BaseCommand):
    help = "Reconcile TempleDB service schedules with Google Calendar bindings."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--schedule-id",
            action="append",
            default=[],
        )
        parser.add_argument(
            "--sync-key",
            action="append",
            default=[],
        )
        parser.add_argument(
            "--scheduled",
            action="store_true",
        )
        parser.add_argument(
            "--skip-remote-check",
            action="store_true",
        )

    def handle(self, *args, **options) -> None:
        lock_fd = None
        try:
            if options["scheduled"]:
                lock_fd = google_calendar_sync.acquire_google_calendar_reconcile_lock()
                if lock_fd is None:
                    self.stdout.write(self.style.WARNING("google calendar reconcile is already running"))
                    return
            results = google_calendar_sync.reconcile_google_calendar_sync(
                schedule_ids=options["schedule_id"],
                sync_keys=options["sync_key"],
                check_remote=not options["skip_remote_check"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        finally:
            google_calendar_sync.release_google_calendar_reconcile_lock(lock_fd)

        if not results:
            self.stdout.write(self.style.SUCCESS("no google calendar sync work was required"))
            return

        for result in results:
            self.stdout.write(
                f"{result.sync_key}: {result.action}: {result.binding_status}: {result.message}"
            )
