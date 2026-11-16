#!/usr/bin/env python3
"""Check an isolated synthetic DB copy over loopback HTTP; never a live server."""
from __future__ import annotations

import argparse
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from test_maintenance import APP_ROOTS, copy_public_tree, isolated_environment

SERVER_CODE = r'''
import socket, sys, types
from pathlib import Path
root = Path(sys.argv[1])
sys.path[:0] = [str(root / "app")]
def deny(*args, **kwargs):
    raise RuntimeError("Outgoing network is disabled in the HTTP smoke server")
socket.create_connection = deny
socket.socket.connect = deny
socket.socket.connect_ex = deny
import django
django.setup()
from django.conf import settings
from django.core.handlers.wsgi import WSGIHandler
from django.core.management import call_command
settings.WSGI_APPLICATION = "smoke_application.application"
module = types.ModuleType("smoke_application")
handler = WSGIHandler()
def application(environ, start_response):
    def respond(status, headers, exc_info=None):
        return start_response(status, headers + [("X-TempleDB-Smoke", sys.argv[2])], exc_info)
    return handler(environ, respond)
module.application = application
sys.modules[module.__name__] = module
call_command("runserver", "127.0.0.1:" + sys.argv[3], use_reloader=False, use_threading=False)
'''


class LocalRedirects(HTTPRedirectHandler):
    def __init__(self, base: str):
        self.base = base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl)[:2] != urlsplit(self.base)[:2]:
            raise ValueError("Smoke requests must remain on the owned loopback server")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def backup_demo(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("Run the synthetic demo Setup first")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        identity = original.execute(
            "SELECT runtime_kind FROM core_databaseruntimeidentity WHERE singleton_key=1"
        ).fetchone()
        sources = original.execute("SELECT source_id FROM imports_legacysource").fetchall()
        if identity != ("demo",) or sources != [("demo-synthetic-rich",)]:
            raise ValueError("Only the standard synthetic demo may be used")
        with sqlite3.connect(target) as copied:
            original.backup(copied)


def check_http(workspace: Path) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = secrets.token_hex(24)
    base = f"http://127.0.0.1:{port}"
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies), LocalRedirects(base))
    with (workspace / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", SERVER_CODE, str(workspace), token, str(port)],
            cwd=workspace, env=isolated_environment(workspace), stdout=log, stderr=log,
        )
        try:
            def get(request):
                with opener.open(request, timeout=3) as response:
                    if response.headers.get("X-TempleDB-Smoke") != token:
                        raise ValueError("Response did not come from this test's server")
                    response.read()
                    return response.status, response.url

            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Temporary server exited before readiness")
                try:
                    status, _ = get(base + "/login/?next=/")
                    if status == 200:
                        break
                except URLError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Temporary server did not become ready") from None
                    time.sleep(0.2)
            csrf = next(cookie.value for cookie in cookies if cookie.name == "csrftoken")
            request = Request(
                base + "/login/?next=/",
                data=urlencode({"username": "demo", "password": "demo", "csrfmiddlewaretoken": csrf, "next": "/"}).encode(),
                headers={"Referer": base + "/login/"},
            )
            status, url = get(request)
            if status != 200 or url != base + "/":
                raise RuntimeError("Synthetic demo login did not reach the home page")
            if get(base + "/households/")[0] != 200:
                raise RuntimeError("Authenticated household page failed")
        finally:
            if server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()  # Only the child handle created above; no PID search.
                server.wait(timeout=10)
        if server.poll() is None:
            raise RuntimeError("Temporary server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-native", action="store_true")
    parser.add_argument("--scratch-root", type=Path, required=True, help="Existing writable scratch directory")
    args = parser.parse_args()
    starter = Path(__file__).resolve().parents[1]
    try:
        if (starter / "app").is_symlink() or not (starter / "app").is_dir():
            raise ValueError("Expected a regular application root")
        if not args.scratch_root.is_dir():
            raise ValueError("Scratch directory does not exist")
        if any(args.scratch_root.resolve().is_relative_to(starter / name) for name in ("app", "datasets", "maintenance")):
            raise ValueError("Scratch must be outside source inputs")
        runtime = starter / "runtime"
        database = runtime / "windows-demo/demo.sqlite3" if args.windows_native else runtime / "demo.sqlite3"
        for path in (runtime, database.parent):
            if path.is_symlink():
                raise ValueError("Runtime links are not accepted")
        with tempfile.TemporaryDirectory(prefix="templedb-http-", dir=args.scratch_root) as temporary:
            workspace = Path(temporary).resolve()
            for name in ("home", "tmp", "runtime", "app"):
                (workspace / name).mkdir()
            budget = [0, 0]
            for name in APP_ROOTS:
                copy_public_tree(starter / "app" / name, workspace / "app" / name, budget)
            (workspace / "app/.env").write_text("", encoding="utf-8")
            backup_demo(database, workspace / "runtime/bootstrap.sqlite3")
            check_http(workspace)
        print("Synthetic HTTP login, home, household page and owned server shutdown PASSED.")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, StopIteration, subprocess.TimeoutExpired) as exc:
        print(f"Synthetic HTTP smoke FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
