from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.runtime_paths import runtime_source_registry_path

if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None

REGISTRY_PATH = Path(__file__).resolve().with_name("source_registry.json")
RUNTIME_REGISTRY_PATH = runtime_source_registry_path()


def active_registry_path() -> Path:
    if RUNTIME_REGISTRY_PATH.exists():
        return RUNTIME_REGISTRY_PATH
    return REGISTRY_PATH


def load_source_registry() -> dict:
    return json.loads(active_registry_path().read_text(encoding="utf-8"))


def default_source_id() -> str:
    registry = load_source_registry()
    default = registry.get("default_source_id")
    if default:
        return default
    sources = registry.get("sources", [])
    if not sources:
        raise ValueError("source_registry.json に sources がありません。")
    return sources[0]["source_id"]


def list_sources() -> list[dict]:
    registry = load_source_registry()
    return registry.get("sources", [])


def get_source(source_id: str | None = None) -> dict:
    resolved_source_id = source_id or default_source_id()
    for source in list_sources():
        if source["source_id"] == resolved_source_id:
            return source
    raise KeyError(f"Unknown source_id: {resolved_source_id}")


@contextmanager
def source_registry_write_lock() -> Iterator[None]:
    """Serialize every runtime registry read-modify-write operation."""

    path = RUNTIME_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def save_source_registry_locked(registry: dict) -> None:
    """Atomically save the registry while ``source_registry_write_lock`` is held."""

    path = RUNTIME_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def save_source_registry(registry: dict) -> None:
    with source_registry_write_lock():
        save_source_registry_locked(registry)


def upsert_source(source_entry: dict, *, make_default: bool = False) -> dict:
    with source_registry_write_lock():
        registry = load_source_registry()
        sources = registry.setdefault("sources", [])
        matched_index = next(
            (
                index
                for index, source in enumerate(sources)
                if source["source_id"] == source_entry["source_id"]
            ),
            None,
        )
        if matched_index is None:
            sources.append(source_entry)
            stored = source_entry
        else:
            sources[matched_index] = {**sources[matched_index], **source_entry}
            stored = sources[matched_index]

        if make_default:
            registry["default_source_id"] = stored["source_id"]
            for source in sources:
                if source["source_id"] == stored["source_id"]:
                    source["status"] = "primary"
                elif source.get("status") == "primary":
                    source["status"] = "registered"

        save_source_registry_locked(registry)
        return stored


def set_default_source(source_id: str) -> dict:
    with source_registry_write_lock():
        registry = load_source_registry()
        sources = registry.setdefault("sources", [])
        matched = None
        for source in sources:
            if source["source_id"] == source_id:
                matched = source
                source["status"] = "primary"
            elif source.get("status") == "primary":
                source["status"] = "registered"
        if matched is None:
            raise KeyError(f"Unknown source_id: {source_id}")
        registry["default_source_id"] = source_id
        save_source_registry_locked(registry)
        return matched


def remove_source(source_id: str) -> dict:
    with source_registry_write_lock():
        registry = load_source_registry()
        sources = registry.setdefault("sources", [])
        remaining = [source for source in sources if source["source_id"] != source_id]
        if len(remaining) == len(sources):
            raise KeyError(f"Unknown source_id: {source_id}")
        registry["sources"] = remaining
        if registry.get("default_source_id") == source_id:
            registry["default_source_id"] = remaining[0]["source_id"] if remaining else ""
        save_source_registry_locked(registry)
        return registry
