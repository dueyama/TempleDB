"""Bootstrap only from the synthetic seed bundled by the demo build."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "demo_seed"
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


def copy_seed(target: Path) -> None:
    validate_seed(SEED)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=target.name + "-initializing-", dir=target.parent))
        shutil.copytree(SEED, staged, dirs_exist_ok=True)
        # Hidden build files may be omitted by the platform's bundle globbing.
        (staged / ".env").write_text("# Synthetic demo only; no credentials.\n")
        # Export markers are generated caches; their build-host paths are not portable.
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
            pass  # Another worker completed the same synthetic sandbox first.
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
