from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO

SAFE_PACKAGE_ROOT_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}\Z")
SAFE_ARCHIVE_NAME_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,180}\.tar\.gz\Z")
ARCHIVE_FILE_MODE = 0o600
OUTPUT_DIRECTORY_MODE = 0o700


@dataclass(frozen=True)
class HandoffFile:
    path: str
    content: bytes


def normalize_files(files: Iterable[HandoffFile | tuple[str, bytes]]) -> list[HandoffFile]:
    normalized: list[HandoffFile] = []
    seen: set[str] = set()
    seen_portable: set[str] = set()
    for item in files:
        file = item if isinstance(item, HandoffFile) else HandoffFile(*item)
        safe_path = _safe_relative_path(file.path)
        portable_path = unicodedata.normalize("NFC", safe_path).casefold()
        if portable_path == "manifest.json" or portable_path.startswith("manifest.json/"):
            raise ValueError("MANIFEST.json is reserved for the package manifest.")
        if safe_path in seen:
            raise ValueError(f"Duplicate handoff package path: {safe_path}")
        if portable_path in seen_portable:
            raise ValueError(
                "Portable handoff package path collision: "
                f"{safe_path}"
            )
        if not isinstance(file.content, bytes):
            raise TypeError(f"Handoff package content must be bytes: {safe_path}")
        seen.add(safe_path)
        seen_portable.add(portable_path)
        normalized.append(HandoffFile(safe_path, file.content))
    for portable_path in seen_portable:
        parts = portable_path.split("/")
        if any("/".join(parts[:index]) in seen_portable for index in range(1, len(parts))):
            raise ValueError(
                "Handoff package file/descendant path collision: "
                f"{portable_path}"
            )
    return sorted(normalized, key=lambda file: file.path)


def build_file_inventory(files: Iterable[HandoffFile | tuple[str, bytes]]) -> list[dict[str, object]]:
    return [
        {
            "path": file.path,
            "size": len(file.content),
            "sha256": hashlib.sha256(file.content).hexdigest(),
        }
        for file in normalize_files(files)
    ]


def build_archive(
    *,
    package_root: str,
    files: Iterable[HandoffFile | tuple[str, bytes]],
    manifest: Mapping[str, object],
) -> tuple[BinaryIO, str]:
    if not SAFE_PACKAGE_ROOT_RE.fullmatch(package_root):
        raise ValueError(f"Unsafe handoff package root: {package_root!r}")
    normalized = normalize_files(files)
    expected_inventory = build_file_inventory(normalized)
    if manifest.get("files") != expected_inventory:
        raise ValueError("Manifest file inventory does not match the archive members.")
    if manifest.get("package_root") not in {None, package_root}:
        raise ValueError("Manifest package_root does not match the archive root.")
    manifest_content = _json_bytes(manifest)
    package_file = tempfile.TemporaryFile(mode="w+b")
    try:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=package_file,
            mtime=0,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                _add_bytes(archive, f"{package_root}/MANIFEST.json", manifest_content)
                for file in normalized:
                    _add_bytes(archive, f"{package_root}/{file.path}", file.content)
        package_file.seek(0)
        return package_file, f"{package_root}.tar.gz"
    except BaseException:
        package_file.close()
        raise


def write_archive_atomic(
    package_file: BinaryIO,
    *,
    filename: str,
    output_root: str | Path,
) -> dict[str, object]:
    if not SAFE_ARCHIVE_NAME_RE.fullmatch(filename):
        raise ValueError(f"Unsafe handoff archive filename: {filename!r}")
    root = Path(os.path.abspath(Path(output_root).expanduser()))
    _prepare_private_output_root(root)
    final_path = root / filename
    if final_path.exists() or final_path.is_symlink():
        raise FileExistsError(f"Handoff archive already exists: {final_path}")

    digest, size = _stream_digest(package_file)
    temp_path: Path | None = None
    published_inode: tuple[int, int] | None = None
    linked = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=root,
            prefix=f".{filename}.",
            suffix=".part",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            os.chmod(temp_path, ARCHIVE_FILE_MODE)
            package_file.seek(0)
            shutil.copyfileobj(package_file, temporary, length=1024 * 1024)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_digest, temporary_size = _path_digest(temp_path)
        if temporary_size != size or temporary_digest != digest:
            raise OSError("Handoff archive bytes changed while writing the private temporary file.")
        temporary_stat = temp_path.lstat()
        if not stat.S_ISREG(temporary_stat.st_mode):
            raise OSError("Handoff archive temporary output is not a regular file.")
        published_inode = (temporary_stat.st_dev, temporary_stat.st_ino)
        os.link(temp_path, final_path, follow_symlinks=False)
        linked = True
        temp_path.unlink()
        temp_path = None
        _fsync_directory(root)
    except BaseException:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        if linked:
            # The hard link publishes the complete, fsynced bytes atomically. If the
            # directory fsync itself fails, leave that valid no-clobber result in place
            # instead of risking deletion of a path another process may now observe.
            pass
        raise
    finally:
        package_file.seek(0)

    final_stat = final_path.lstat()
    if not stat.S_ISREG(final_stat.st_mode) or (
        final_stat.st_dev,
        final_stat.st_ino,
    ) != published_inode:
        raise OSError(f"Handoff archive publication identity changed: {final_path}")
    if stat.S_IMODE(final_stat.st_mode) != ARCHIVE_FILE_MODE:
        raise PermissionError(f"Handoff archive is not owner-only: {final_path}")
    final_digest, final_size = _path_digest(final_path)
    if final_size != size or final_digest != digest:
        raise OSError(f"Published handoff archive integrity changed: {final_path}")
    return {
        "archive_path": str(final_path),
        "archive_size": size,
        "archive_sha256": digest,
    }


def _safe_relative_path(raw_path: str) -> str:
    raw_text = str(raw_path)
    if "\\" in raw_text or any(ord(character) < 32 or ord(character) == 127 for character in raw_text):
        raise ValueError(f"Unsafe handoff package path: {raw_path!r}")
    path = PurePosixPath(raw_text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe handoff package path: {raw_path!r}")
    return path.as_posix()


def _add_bytes(archive: tarfile.TarFile, arcname: str, content: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(content)
    info.mode = ARCHIVE_FILE_MODE
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, BytesIO(content))


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _prepare_private_output_root(root: Path) -> None:
    root.mkdir(parents=True, mode=OUTPUT_DIRECTORY_MODE, exist_ok=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise NotADirectoryError(f"Handoff output root must be a real directory: {root}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError(f"Handoff output root must be owner-only (0700): {root}")


def _stream_digest(package_file: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    package_file.seek(0)
    while chunk := package_file.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    package_file.seek(0)
    return digest.hexdigest(), size


def _path_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ARCHIVE_FILE_MODE",
    "HandoffFile",
    "OUTPUT_DIRECTORY_MODE",
    "build_archive",
    "build_file_inventory",
    "normalize_files",
    "write_archive_atomic",
]
