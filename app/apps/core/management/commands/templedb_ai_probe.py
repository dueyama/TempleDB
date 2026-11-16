from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.office.services.templedb_ai_read import (
    get_templedb_household_summary,
    search_templedb_people,
)


class Command(BaseCommand):
    help = "Probe TempleDB read-only AI tools without starting an MCP server."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "query",
            nargs="?",
            help="Person search query. Omit when --household-id is supplied.",
        )
        parser.add_argument(
            "--household-id",
            help="Return a redacted household summary for this legacy household id.",
        )
        parser.add_argument(
            "--ledger",
            default="all",
            choices=("all", "current", "memorial"),
            help="Ledger filter for person search.",
        )
        parser.add_argument("--limit", type=int, default=10, help="Maximum search rows to return.")
        parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    def handle(self, *args, **options) -> None:
        household_id = (options.get("household_id") or "").strip()
        query = (options.get("query") or "").strip()
        if household_id:
            payload = get_templedb_household_summary(household_id)
        elif query:
            payload = search_templedb_people(
                query,
                ledger=options["ledger"],
                limit=options["limit"],
            )
        else:
            raise CommandError("query または --household-id を指定してください。")

        indent = 2 if options["pretty"] else None
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=indent))
