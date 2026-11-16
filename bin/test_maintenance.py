#!/usr/bin/env python3
"""Run public maintenance tests on a disposable code/data copy, never a live DB."""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ROOTS = ("apps", "config", "static", "templates")
SKIP_DIRECTORIES = {
    "__pycache__", "data", "runtime", "private", "credentials", "secrets",
    "archive", "archives", "node_modules", "staticfiles",
}
TEXT_AND_ASSET_SUFFIXES = {
    ".py", ".json", ".html", ".css", ".js", ".svg", ".txt", ".toml",
    ".png", ".ico", ".ttf", ".otf", ".woff", ".woff2",
}
MAX_COPY_BYTES = 256 * 1024 * 1024
MAX_COPY_FILES = 20_000

CHILD_CODE = r'''
import importlib.abc
import importlib.machinery
import os
import socket
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
sys.path[:0] = [str(workspace / "app"), str(workspace)]

class IsolatedApplicationFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] not in {"apps", "config", "maintenance"}:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.origin is None or not Path(spec.origin).resolve().is_relative_to(workspace):
            raise ModuleNotFoundError("Missing isolated application module: " + fullname, name=fullname)
        return spec

# An editable install may still point at the caller's app. Never use it to fill
# missing modules in the disposable snapshot, even when the same venv is reused.
sys.meta_path.insert(0, IsolatedApplicationFinder())

def deny_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled in maintenance tests")

socket.create_connection = deny_network
socket.getaddrinfo = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network

import django
from django.conf import settings

database = settings.DATABASES
expected = str(workspace / "runtime" / "bootstrap.sqlite3")
if set(database) != {"default"} or database["default"]["ENGINE"] != "django.db.backends.sqlite3":
    raise RuntimeError("Maintenance tests require only the isolated SQLite database")
if str(database["default"]["NAME"]) != expected or not settings.TEMPLEDB_DEMO_MODE:
    raise RuntimeError("Maintenance database or demo identity escaped the isolated workspace")
if Path(settings.TEMPLEDB_TENANT_ROOT).resolve() != workspace / "app":
    raise RuntimeError("Maintenance tenant root escaped the isolated workspace")
database["default"]["TEST"] = {"NAME": str(workspace / "runtime" / "test.sqlite3")}
settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# Scheduled backup/calendar dispatch is operational behavior, not part of this suite.
settings.MIDDLEWARE = [
    item for item in settings.MIDDLEWARE
    if item != "apps.core.middleware.DatabaseBackupScheduleMiddleware"
]
django.setup()
from django.test.runner import DiscoverRunner

class MaintenanceRunner(DiscoverRunner):
    def suite_result(self, suite, result, **kwargs):
        if not result.testsRun or len(result.skipped) == result.testsRun:
            return 1
        return super().suite_result(suite, result, **kwargs)

failures = MaintenanceRunner(verbosity=2, interactive=False, keepdb=False).run_tests(["maintenance"])
raise SystemExit(1 if failures else 0)
'''


def copy_public_tree(source: Path, target: Path, budget: list[int], *, dataset=False) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Expected a regular source directory: {source.name}")
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        if item.name.startswith(".") or item.name in SKIP_DIRECTORIES:
            continue
        mode = item.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symbolic links are not accepted in maintenance inputs: {item.name}")
        destination = target / item.name
        if stat.S_ISDIR(mode):
            copy_public_tree(item, destination, budget, dataset=dataset)
        elif stat.S_ISREG(mode):
            suffixes = TEXT_AND_ASSET_SUFFIXES | ({".pdf"} if dataset else set())
            if item.suffix.lower() not in suffixes:
                continue
            budget[0] += item.stat().st_size
            budget[1] += 1
            if budget[0] > MAX_COPY_BYTES or budget[1] > MAX_COPY_FILES:
                raise ValueError("Maintenance input copy exceeds its bounded size/file limit")
            shutil.copyfile(item, destination)
        else:
            raise ValueError(f"Special files are not accepted in maintenance inputs: {item.name}")


def isolated_environment(workspace: Path) -> dict[str, str]:
    # Construct a fresh environment instead of inheriting DB credentials, tenant
    # selection, Python paths, proxies, API keys or settings from the caller.
    environment = {
        "PATH": os.defpath,
        "HOME": str(workspace / "home"),
        "USERPROFILE": str(workspace / "home"),
        "TMPDIR": str(workspace / "tmp"),
        "TEMP": str(workspace / "tmp"),
        "TMP": str(workspace / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "MPLCONFIGDIR": str(workspace / "tmp" / "matplotlib"),
        "XDG_CACHE_HOME": str(workspace / "tmp" / "cache"),
        "DATABASE_HOST": "",
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": "public-maintenance-test-only",
        "DJANGO_DEBUG": "0",
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "TEMPLEDB_DATABASE_ENGINE": "sqlite",
        "TEMPLEDB_DEMO_MODE": "1",
        "TEMPLEDB_RUNTIME_ROLE": "staging",
        "TEMPLEDB_SQLITE_DB_PATH": str(workspace / "runtime" / "bootstrap.sqlite3"),
        "TEMPLEDB_TENANT_ROOT": str(workspace / "app"),
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scratch-root", type=Path,
        help="Existing writable temporary parent; no fallback if unavailable.",
    )
    args = parser.parse_args(argv)
    starter = Path(__file__).resolve().parents[1]
    try:
        for name in ("app", "datasets", "maintenance"):
            if (starter / name).is_symlink() or not (starter / name).is_dir():
                raise ValueError(f"Expected a regular starter directory: {name}")
        if args.scratch_root is not None and not args.scratch_root.is_dir():
            raise ValueError("The requested scratch root is not an existing directory")
        if args.scratch_root is not None and any(
            args.scratch_root.resolve().is_relative_to(starter / name)
            for name in ("app", "datasets", "maintenance")
        ):
            raise ValueError("Scratch root must be outside the copied maintenance inputs")
        with tempfile.TemporaryDirectory(
            prefix="templedb-maintenance-", dir=args.scratch_root,
        ) as temporary:
            workspace = Path(temporary).resolve()
            for name in ("home", "tmp", "runtime", "app"):
                (workspace / name).mkdir()
            budget = [0, 0]
            for name in APP_ROOTS:
                copy_public_tree(starter / "app" / name, workspace / "app" / name, budget)
            copy_public_tree(starter / "maintenance", workspace / "maintenance", budget)
            copy_public_tree(
                starter / "datasets" / "synthetic_demo_v1",
                workspace / "datasets" / "synthetic_demo_v1", budget, dataset=True,
            )
            # An empty tenant env prevents config.env from consulting any live env.
            (workspace / "app" / ".env").write_text("", encoding="utf-8")
            print("Testing a disposable source copy and synthetic SQLite only.", flush=True)
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", CHILD_CODE, str(workspace)],
                cwd=workspace, env=isolated_environment(workspace), check=False,
                timeout=600,
            )
            if result.returncode:
                print("Maintenance tests FAILED; do not apply the change to the product DB.")
                return 1
            print("Maintenance tests PASSED. Live databases were not used.")
            return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Maintenance tests could not complete: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
