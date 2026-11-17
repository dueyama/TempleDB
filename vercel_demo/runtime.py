"""Bootstrap only from the synthetic seed bundled by the demo build."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "demo_seed"
SANDBOX_TTL = 4 * 60 * 60
MAX_SANDBOXES = 16
MAX_STATE_BYTES = 128 * 1024 * 1024
sys.path.insert(0, str(ROOT / "app"))


def validate_seed(root: Path) -> None:
    database = root / "data/runtime/demo.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        identity = connection.execute(
            "SELECT runtime_kind FROM core_databaseruntimeidentity WHERE singleton_key=1"
        ).fetchone()
        sources = connection.execute("SELECT source_id FROM imports_legacysource").fetchall()
        if identity != ("demo",) or sources != [("demo-synthetic-rich",)]:
            raise RuntimeError("Only the standard synthetic demo seed is allowed")


def state_root() -> Path:
    version = hashlib.sha256((SEED / "data/runtime/demo.sqlite3").read_bytes()).hexdigest()[:16]
    parent = Path(os.environ.get("TEMPLEDB_VERCEL_STATE_ROOT", tempfile.gettempdir()))
    if not parent.is_absolute():
        raise RuntimeError("The demo state parent must be absolute")
    return parent / ("templedb-vercel-" + version)


class SandboxCapacityError(Exception):
    """New visitors must wait rather than evicting another active demo."""


@contextmanager
def sandbox_lock():
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    # Also serialize different Python processes sharing this temporary volume.
    with (root / ".sandbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield root
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if not path.is_symlink() and path.is_file())


def discard_sandbox(tenant: Path) -> None:
    # Never remove the bundled seed, bootstrap, symlinks, or unrelated directories.
    if re.fullmatch(r"[a-f0-9]{32}", tenant.name) and not tenant.is_symlink():
        shutil.rmtree(tenant)


def prepare_sandbox(root: Path, identifier: str) -> tuple[Path, bool]:
    """Call only while holding sandbox_lock, through the entire response."""
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid synthetic sandbox identifier")
    now = time.time()
    for tenant in root.iterdir():
        marker = tenant / ".last_used"
        if (re.fullmatch(r"[a-f0-9]{32}", tenant.name) and tenant.is_dir()
                and not tenant.is_symlink() and marker.is_file() and not marker.is_symlink()
                and now - marker.stat().st_mtime >= SANDBOX_TTL):
            discard_sandbox(tenant)
    tenant = root / identifier
    if tenant.is_symlink():
        raise RuntimeError("Invalid synthetic sandbox path")
    created = not tenant.exists()
    if created:
        count = sum(bool(re.fullmatch(r"[a-f0-9]{32}", path.name)) for path in root.iterdir())
        if count >= MAX_SANDBOXES or tree_bytes(root) + tree_bytes(SEED) > MAX_STATE_BYTES:
            raise SandboxCapacityError
    copy_seed(tenant)
    (tenant / ".last_used").touch()
    return tenant, created


def copy_seed(target: Path) -> None:
    validate_seed(SEED)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=target.name + "-initializing-", dir=target.parent))
        try:
            shutil.copytree(SEED, staged, dirs_exist_ok=True)
            # Hidden build files may be omitted by the platform's bundle globbing.
            (staged / ".env").write_text("# Synthetic demo only; no credentials.\n")
            # Export markers are generated caches; build-host paths are not portable.
            with sqlite3.connect(staged / "data/runtime/demo.sqlite3") as connection:
                for key, source_id, snapshot_id in connection.execute(
                    "SELECT e.id, s.source_id, e.snapshot_id FROM imports_exportsnapshot e "
                    "JOIN imports_legacysource s ON e.source_id=s.id"
                ).fetchall():
                    snapshot = target / "data/generated/legacy_exports" / source_id / snapshot_id
                    connection.execute(
                        "UPDATE imports_exportsnapshot SET export_dir=?, manifest_path=?, log_path=? WHERE id=?",
                        (str(snapshot), str(snapshot / "manifest.json"), str(snapshot / "export.log"), key),
                    )
            validate_seed(staged)
            try:
                staged.rename(target)
            except FileExistsError:
                pass  # Another worker completed the same synthetic bootstrap first.
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    validate_seed(target)


def configure() -> Path:
    building = os.environ.get("TEMPLEDB_VERCEL_BUILD") == "1"
    discovering = not (SEED / "data/runtime/demo.sqlite3").exists() and not building
    if building:
        tenant = SEED
    elif discovering:
        # Vercel discovers Django settings before running the build command.
        parent = os.environ.get("TEMPLEDB_VERCEL_STATE_ROOT", tempfile.gettempdir())
        Path(parent).mkdir(parents=True, exist_ok=True)
        tenant = Path(tempfile.mkdtemp(prefix="templedb-discovery-", dir=parent))
    else:
        tenant = state_root() / "bootstrap"
    if building or discovering:
        if building:
            tenant.mkdir(exist_ok=False)
        (tenant / "data/runtime").mkdir(parents=True)
        (tenant / "config").mkdir()
        shutil.copytree(ROOT / "app/config/tenant_policy", tenant / "config/tenant_policy")
        (tenant / ".env").write_text("# Synthetic demo only; no credentials.\n")
    else:
        copy_seed(tenant)
    for name in ("DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_PORT"):
        os.environ.pop(name, None)
    os.environ.update(
        DJANGO_SETTINGS_MODULE="vercel_demo.settings",
        TEMPLEDB_DEMO_MODE="1",
        TEMPLEDB_DATABASE_ENGINE="sqlite",
        TEMPLEDB_TENANT_ROOT=str(tenant),
        TEMPLEDB_SQLITE_DB_PATH=str(tenant / "data/runtime/demo.sqlite3"),
        TEMPLEDB_RUNTIME_ROLE="staging",
        DJANGO_DEBUG="0",
        DJANGO_ALLOWED_HOSTS=".vercel.app,127.0.0.1,localhost,testserver",
        MPLCONFIGDIR=str(tenant / "data/runtime/matplotlib"),
    )
    if not os.environ.get("DJANGO_SECRET_KEY"):
        raise RuntimeError("A separate demo DJANGO_SECRET_KEY is required")
    return tenant
