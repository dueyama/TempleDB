from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand, CommandError

from apps.office.services import templedb_ai_read


class Command(BaseCommand):
    help = "Run the read-only TempleDB MCP server."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--transport",
            choices=("stdio", "streamable-http", "sse"),
            default="stdio",
            help="MCP transport. Use stdio for local clients; streamable-http for tunnel testing.",
        )
        parser.add_argument("--host", default="127.0.0.1", help="HTTP transport host.")
        parser.add_argument("--port", type=int, default=8765, help="HTTP transport port.")

    def handle(self, *args, **options) -> None:
        _require_ai_tools_enabled()
        FastMCP = _load_fastmcp()

        mcp = _build_fastmcp(
            FastMCP,
            host=options["host"],
            port=options["port"],
        )

        @read_only_tool(mcp)
        def search_templedb_people(
            query: str,
            ledger: str = "all",
            limit: int = 10,
        ) -> dict:
            """Read-only search for people in the current TempleDB ledger."""
            return templedb_ai_read.search_templedb_people(
                query=query,
                ledger=ledger,
                limit=limit,
            )

        @read_only_tool(mcp)
        def get_templedb_household_summary(household_id: str) -> dict:
            """Read-only redacted household summary for a current TempleDB household."""
            return templedb_ai_read.get_templedb_household_summary(household_id=household_id)

        if options["transport"] != "stdio":
            print(
                (
                    "Starting TempleDB read-only MCP server "
                    f"with {options['transport']} on {options['host']}:{options['port']}"
                ),
                file=sys.stderr,
            )
        mcp.run(transport=options["transport"])


def _build_fastmcp(FastMCP, *, host: str, port: int):
    kwargs = {
        "instructions": (
            "Read-only TempleDB demo tools. These tools search and summarize "
            "current TempleDB records without creating, updating, or deleting data."
        ),
        "json_response": True,
        "stateless_http": True,
        "host": host,
        "port": port,
    }
    try:
        return FastMCP(
            "TempleDB Demo Read-Only",
            **kwargs,
        )
    except TypeError:
        fallback_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"host", "port", "stateless_http"}
        }
        mcp = FastMCP("TempleDB Demo Read-Only", **fallback_kwargs)
        if hasattr(mcp, "settings"):
            mcp.settings.host = host
            mcp.settings.port = port
            if hasattr(mcp.settings, "stateless_http"):
                mcp.settings.stateless_http = True
        return mcp


def _require_ai_tools_enabled() -> None:
    if _truthy_env("TEMPLEDB_DEMO_MODE") or _truthy_env("TEMPLEDB_AI_TOOLS_ENABLED"):
        return
    raise CommandError(
        "TempleDB MCP server is disabled. Set TEMPLEDB_DEMO_MODE=1 for the demo "
        "workspace or TEMPLEDB_AI_TOOLS_ENABLED=1 for an explicitly approved environment."
    )


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise CommandError(
            "MCP SDK is not installed. Install the optional AI dependencies with "
            "`python -m pip install -e '.[ai]'` in this environment."
        ) from exc
    return FastMCP


def read_only_tool(mcp):
    tool_kwargs = {
        "annotations": _read_only_tool_annotations(),
    }
    try:
        return mcp.tool(**tool_kwargs)
    except TypeError:
        return mcp.tool()


def _read_only_tool_annotations():
    try:
        from mcp.types import ToolAnnotations
    except ImportError:
        return {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    for kwargs in (
        {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        {
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        },
    ):
        try:
            return ToolAnnotations(**kwargs)
        except TypeError:
            continue
    return {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
