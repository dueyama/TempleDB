from __future__ import annotations

import re
import sqlite3
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
SUPPORTED_DATABASE_ENGINES = {"postgresql", "sqlite"}
POSTGRESQL_DEMO_DATABASE_PATTERN = re.compile(r"templedb_demo_[a-z0-9_]{1,40}")
POSTGRESQL_DEMO_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SQLITE_HEADER = b"SQLite format 3\x00"
PRODUCT_SQLITE_REQUIRED_TABLES = {
    "django_migrations",
    "core_databasebackupsetting",
    "core_databaseruntimeidentity",
    "imports_legacysource",
    "imports_importbatch",
}
PRODUCT_SQLITE_REQUIRED_MIGRATIONS = {
    ("auth", "0001_initial"),
    ("core", "0014_database_runtime_identity"),
    ("imports", "0001_initial"),
}


@dataclass(frozen=True)
class DatabaseRuntimeSelection:
    engine: str
    mode: str
    sqlite_path: str = ""

    @property
    def is_demo(self) -> bool:
        return self.mode in {"demo_sqlite", "demo_postgresql"}

    @property
    def is_product_sqlite(self) -> bool:
        return self.mode == "product_sqlite"

    @property
    def is_postgresql_demo(self) -> bool:
        return self.mode == "demo_postgresql"


def env_flag(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def resolve_allowed_hosts(env_value: str | None, debug: bool) -> list[str]:
    if env_value is None or not env_value.strip():
        raw_value = "*" if debug else "127.0.0.1,localhost,testserver"
    else:
        raw_value = env_value
    return [host.strip() for host in raw_value.split(",") if host.strip()]


def resolve_csrf_trusted_origins(env_value: str | None, *base_urls: str | None) -> list[str]:
    origins: list[str] = []

    def append_origin(value: str) -> None:
        normalized = value.strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)

    if env_value and env_value.strip():
        for raw_origin in env_value.split(","):
            append_origin(raw_origin)

    for raw_url in base_urls:
        if not raw_url:
            continue
        parsed = urlsplit(raw_url.strip())
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            append_origin(f"{parsed.scheme}://{parsed.netloc}")

    return origins


def _looks_like_pytest_argv(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name.lower()
    if "pytest" in executable:
        return True
    return any("pytest" in arg.lower() for arg in argv[1:3])


def _looks_like_manage_py_test(argv: Sequence[str]) -> bool:
    return len(argv) >= 2 and Path(argv[0]).name == "manage.py" and argv[1] == "test"


def should_allow_sqlite_fallback(
    env: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
    module_names: Iterable[str] | None = None,
) -> bool:
    env = {} if env is None else env
    argv = sys.argv if argv is None else argv
    module_names = sys.modules.keys() if module_names is None else module_names
    if env.get("PYTEST_CURRENT_TEST"):
        return True
    if "pytest" in module_names:
        return True
    if _looks_like_pytest_argv(argv):
        return True
    if _looks_like_manage_py_test(argv):
        return True
    return False


def should_allow_demo_sqlite(env: Mapping[str, str] | None = None) -> bool:
    env = {} if env is None else env
    return env_flag(env.get("TEMPLEDB_DEMO_MODE"), default=False)


def resolve_database_runtime(
    env: Mapping[str, str],
    *,
    fallback_sqlite_path: str | Path,
    allow_test_sqlite: bool,
    allow_product_sqlite_initialization: bool = False,
) -> DatabaseRuntimeSelection:
    requested_engine = (env.get("TEMPLEDB_DATABASE_ENGINE") or "").strip().lower()
    database_host = (env.get("DATABASE_HOST") or "").strip()
    demo_requested = should_allow_demo_sqlite(env)

    if requested_engine and requested_engine not in SUPPORTED_DATABASE_ENGINES:
        supported = ", ".join(sorted(SUPPORTED_DATABASE_ENGINES))
        raise ValueError(
            f"TEMPLEDB_DATABASE_ENGINE must be one of: {supported}. "
            f"Received: {requested_engine}"
        )

    if demo_requested and requested_engine == "postgresql":
        _validate_postgresql_demo_runtime(env, database_host=database_host)
        return DatabaseRuntimeSelection(engine="postgresql", mode="demo_postgresql")
    if demo_requested and database_host:
        raise ValueError(
            "TEMPLEDB_DEMO_MODE cannot be used while DATABASE_HOST is configured."
        )

    if demo_requested:
        demo_path = _resolve_demo_sqlite_path(
            env,
            fallback_sqlite_path=fallback_sqlite_path,
        )
        return DatabaseRuntimeSelection(
            engine="sqlite",
            mode="demo_sqlite",
            sqlite_path=str(demo_path),
        )

    if requested_engine == "postgresql":
        if not database_host:
            raise ValueError(
                "DATABASE_HOST is required when TEMPLEDB_DATABASE_ENGINE=postgresql."
            )
        return DatabaseRuntimeSelection(engine="postgresql", mode="product_postgresql")

    if requested_engine == "sqlite":
        if database_host:
            raise ValueError(
                "DATABASE_HOST must be empty when TEMPLEDB_DATABASE_ENGINE=sqlite."
            )
        sqlite_path = _resolve_product_sqlite_path(
            env,
            initialization_allowed=allow_product_sqlite_initialization,
        )
        return DatabaseRuntimeSelection(
            engine="sqlite",
            mode="product_sqlite",
            sqlite_path=str(sqlite_path),
        )

    if database_host:
        return DatabaseRuntimeSelection(engine="postgresql", mode="product_postgresql")

    if allow_test_sqlite:
        return DatabaseRuntimeSelection(
            engine="sqlite",
            mode="test_sqlite",
            sqlite_path=str(fallback_sqlite_path),
        )

    raise ValueError(
        "PostgreSQL settings or an explicit TempleDB database engine are required. "
        "Set DATABASE_HOST for the existing PostgreSQL runtime, or set "
        "TEMPLEDB_DATABASE_ENGINE=sqlite with an absolute TEMPLEDB_SQLITE_DB_PATH."
    )


def _validate_postgresql_demo_runtime(
    env: Mapping[str, str],
    *,
    database_host: str,
) -> None:
    if not env_flag(env.get("TEMPLEDB_ALLOW_POSTGRESQL_DEMO"), default=False):
        raise ValueError(
            "TEMPLEDB_DEMO_MODE with PostgreSQL requires "
            "TEMPLEDB_ALLOW_POSTGRESQL_DEMO=1."
        )
    if not (
        database_host in POSTGRESQL_DEMO_LOCAL_HOSTS
        or (database_host.startswith("/") and Path(database_host).is_absolute())
    ):
        raise ValueError("PostgreSQL demo testing is limited to a local database host.")
    if (env.get("TEMPLEDB_SQLITE_DB_PATH") or "").strip():
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH must be empty during PostgreSQL demo testing."
        )
    database_name = (env.get("DATABASE_NAME") or "").strip()
    if not POSTGRESQL_DEMO_DATABASE_PATTERN.fullmatch(database_name):
        raise ValueError(
            "PostgreSQL demo database names must match "
            "templedb_demo_[a-z0-9_]{1,40}."
        )
    if not (env.get("DATABASE_USER") or "").strip():
        raise ValueError("DATABASE_USER is required during PostgreSQL demo testing.")
    database_port = (env.get("DATABASE_PORT") or "5432").strip()
    if not database_port.isdigit() or not 1 <= int(database_port) <= 65535:
        raise ValueError("DATABASE_PORT must be a valid port number.")


def _resolve_product_sqlite_path(
    env: Mapping[str, str],
    *,
    initialization_allowed: bool,
) -> Path:
    raw_path = (env.get("TEMPLEDB_SQLITE_DB_PATH") or "").strip()
    if not raw_path:
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH is required when TEMPLEDB_DATABASE_ENGINE=sqlite."
        )
    if raw_path == ":memory:":
        raise ValueError(":memory: cannot be used for a product SQLite database.")

    sqlite_path = Path(raw_path).expanduser()
    if not sqlite_path.is_absolute():
        raise ValueError("TEMPLEDB_SQLITE_DB_PATH must be an absolute path.")
    if sqlite_path.is_symlink():
        raise ValueError("TEMPLEDB_SQLITE_DB_PATH must not be a symbolic link.")

    if not sqlite_path.exists():
        if not initialization_allowed:
            raise ValueError(
                "The product SQLite database does not exist. Refusing to create an empty "
                "database during a normal start. Use the dedicated initialization workflow."
            )
        if not sqlite_path.parent.exists() or not sqlite_path.parent.is_dir():
            raise ValueError("The product SQLite database parent directory does not exist.")
        return sqlite_path

    if not sqlite_path.is_file():
        raise ValueError("TEMPLEDB_SQLITE_DB_PATH must point to a regular file.")
    if initialization_allowed:
        if sqlite_path.stat().st_size == 0:
            return sqlite_path
        raise ValueError(
            "Product SQLite initialization refuses to modify a non-empty target file."
        )
    _validate_sqlite_header(sqlite_path)
    _validate_sqlite_database(sqlite_path, expected_runtime_kind="product")
    return sqlite_path


def _resolve_demo_sqlite_path(
    env: Mapping[str, str],
    *,
    fallback_sqlite_path: str | Path,
) -> str | Path:
    raw_path = (env.get("TEMPLEDB_SQLITE_DB_PATH") or "").strip()
    if raw_path == ":memory:":
        return raw_path
    sqlite_path = Path(raw_path or fallback_sqlite_path).expanduser()
    if not sqlite_path.is_absolute():
        raise ValueError("The demo TEMPLEDB_SQLITE_DB_PATH must be an absolute path.")
    if sqlite_path.is_symlink():
        raise ValueError("The demo TEMPLEDB_SQLITE_DB_PATH must not be a symbolic link.")
    if not sqlite_path.exists():
        if not sqlite_path.parent.exists() or not sqlite_path.parent.is_dir():
            raise ValueError("The demo SQLite database parent directory does not exist.")
        return sqlite_path
    if not sqlite_path.is_file():
        raise ValueError("The demo TEMPLEDB_SQLITE_DB_PATH must point to a regular file.")
    _validate_sqlite_header(sqlite_path)
    _validate_sqlite_database(sqlite_path, expected_runtime_kind="demo")
    return sqlite_path


def _validate_sqlite_header(sqlite_path: Path) -> None:
    try:
        with sqlite_path.open("rb") as database_file:
            header = database_file.read(len(SQLITE_HEADER))
    except OSError as exc:
        raise ValueError("The SQLite database cannot be read.") from exc
    if header != SQLITE_HEADER:
        raise ValueError("TEMPLEDB_SQLITE_DB_PATH is not a valid SQLite database file.")


def _validate_sqlite_database(
    sqlite_path: Path,
    *,
    expected_runtime_kind: str,
) -> None:
    quoted_path = quote(str(sqlite_path), safe="/")
    try:
        with sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True) as connection:
            quick_check_rows = connection.execute("PRAGMA quick_check").fetchall()
            if quick_check_rows != [("ok",)]:
                raise ValueError(
                    "TEMPLEDB_SQLITE_DB_PATH failed SQLite integrity validation."
                )
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError("The SQLite database cannot be opened read-only.") from exc
    table_names = {str(row[0]) for row in rows}
    missing_tables = sorted(PRODUCT_SQLITE_REQUIRED_TABLES - table_names)
    if missing_tables:
        missing_label = ", ".join(missing_tables)
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH is not an initialized TempleDB database. "
            f"Missing tables: {missing_label}"
        )
    try:
        with sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True) as connection:
            migration_rows = connection.execute(
                "SELECT app, name FROM django_migrations"
            ).fetchall()
            identity_row = connection.execute(
                "SELECT installation_id, runtime_kind "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("The SQLite validation records cannot be read.") from exc
    migrations = {(str(row[0]), str(row[1])) for row in migration_rows}
    missing_migrations = sorted(PRODUCT_SQLITE_REQUIRED_MIGRATIONS - migrations)
    if missing_migrations:
        missing_label = ", ".join(f"{app}.{name}" for app, name in missing_migrations)
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH is missing required TempleDB migrations: "
            f"{missing_label}"
        )
    if identity_row is None:
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH has no database identity record."
        )
    installation_id, runtime_kind = identity_row
    try:
        parsed_installation_id = uuid.UUID(str(installation_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH has an invalid installation identity."
        ) from exc
    if parsed_installation_id.int == 0:
        raise ValueError(
            "TEMPLEDB_SQLITE_DB_PATH has an invalid installation identity."
        )
    if runtime_kind != expected_runtime_kind:
        raise ValueError(
            f"TEMPLEDB_SQLITE_DB_PATH is not a {expected_runtime_kind} database "
            f"(runtime_kind={runtime_kind!r})."
        )
