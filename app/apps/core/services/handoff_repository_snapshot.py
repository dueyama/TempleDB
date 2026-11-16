from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

REPOSITORY_SNAPSHOT_VERSION = 1
SOURCE_MANIFEST_FORMAT = "templedb-handoff-source-manifest"
SOURCE_MANIFEST_VERSION = 1
SOURCE_MANIFEST_LOCATIONS = (
    "handoff-source-manifest.json",
    "config/handoff_source_manifest.json",
)
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_FILES = 20_000

ROOT_FILE_ALLOWLIST = (
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    "AGENTS.md",
    "Caddyfile",
    "LICENSE",
    "Makefile",
    "README.md",
    "TempleDB Console.command",
    "TempleDB Server Stop.command",
    "TempleDB Server.command",
    "TempleDB Stop.command",
    "docker-compose.yml",
    "manage.py",
    "memory.md",
    "pyproject.toml",
)
ROOT_DIRECTORY_ALLOWLIST = (
    "apps",
    "config",
    "demo",
    "docs",
    "scripts",
    "static",
    "templates",
    "tests",
)
TEXT_SUFFIX_ALLOWLIST = frozenset(
    {
        ".command",
        ".css",
        ".html",
        ".js",
        ".json",
        ".md",
        ".py",
        ".sh",
        ".svg",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)

_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "archive",
        "archives",
        "credentials",
        "dump",
        "dumps",
        "node_modules",
        "secrets",
        "staticfiles",
    }
)
_GIT_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40,64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PRIVATE_KEY_RE = re.compile(
    rb"-----BEGIN (?:[A-Z0-9]+ )?(?:ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----",
)
_DATABASE_URL_WITH_PASSWORD_RE = re.compile(
    rb"(?i)\b(?:postgres(?:ql)?|mysql|mariadb)://[^\s/:@]+:([^\s/@]+)@",
)
_KNOWN_TOKEN_RE = re.compile(
    rb"(?x)(?:"
    rb"github_pat_[A-Za-z0-9_]{16,}"
    rb"|gh[pousr]_[A-Za-z0-9]{16,}"
    rb"|sk-proj-[A-Za-z0-9_-]{16,}"
    rb"|sk-[A-Za-z0-9_-]{20,}"
    rb"|sk_live_[A-Za-z0-9]{16,}"
    rb"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    rb"|tskey-[A-Za-z0-9_-]{16,}"
    rb"|xox[baprs]-[A-Za-z0-9-]{16,}"
    rb"|AIza[0-9A-Za-z_-]{30,}"
    rb")",
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    rb"(?ix)"
    rb"(?:[\"']?(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    rb"client[_-]?secret|api[_-]?key)[\"']?)"
    rb"\s*(?:=|:)\s*[\"']?([A-Za-z0-9_./+=:-]{24,})[\"']?",
)
_GENERIC_SECRET_ASSIGNMENT_RE = re.compile(
    rb"(?imx)"
    rb"(?:[\"']?[A-Z0-9_.-]*(?:PASSWORD|PASSWD|SECRET(?:_KEY)?)[\"']?)"
    rb"[ \t]*(?:=|:)[ \t]*"
    rb"(?:[\"'](?P<quoted>[^\"'\r\n]{8,})[\"']|"
    rb"(?P<bare>[A-Za-z0-9][A-Za-z0-9_+/=-]{7,})"
    rb"(?=[ \t]*(?:[#;,}\)]|$)))",
)
_CREDENTIAL_FILE_STEMS = frozenset(
    {"credential", "credentials", "secret", "secrets", "token", "tokens"}
)
_CREDENTIAL_FILE_MARKERS = (
    "access-token",
    "api-key",
    "api-token",
    "auth-token",
    "client-secret",
    "credential-token",
    "refresh-token",
    "private-key",
    "service-account",
)
_PLACEHOLDER_SECRET_VALUES = frozenset(
    {
        "changeme",
        "dummy",
        "example",
        "placeholder",
        "redacted",
        "test",
        "templedb",
        "your-token-here",
    }
)
_READ_CHUNK_BYTES = 1024 * 1024
_DEFAULT_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class RepositorySnapshotError(RuntimeError):
    """Raised when a repository snapshot cannot be produced safely."""


class _GitUnavailableError(RepositorySnapshotError):
    """Raised only when Git cannot provide the requested inventory."""


def build_repository_snapshot(
    repository_root: str | Path | None = None,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[str, Any]:
    """Return a bounded snapshot of tracked, allowlisted repository text files.

    The result intentionally keeps file bodies as bytes.  A package assembler can
    therefore write the exact worktree contents without a second filesystem read,
    while using each entry's SHA-256 as an integrity check.
    """

    _validate_limit("max_file_bytes", max_file_bytes)
    _validate_limit("max_total_bytes", max_total_bytes)
    _validate_limit("max_files", max_files)
    root = _resolve_repository_root(repository_root)

    try:
        git_metadata, tracked_paths, untracked_paths = _read_git_inventory(root)
    except _GitUnavailableError as git_error:
        return _build_manifest_repository_snapshot(
            root,
            git_error=git_error,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            max_files=max_files,
        )
    _assert_no_tracked_symlinks(root, tracked_paths)
    tracked_allowlisted = sorted(path for path in tracked_paths if _is_allowlisted_path(path))
    untracked_omitted = sum(1 for path in untracked_paths if _is_allowlisted_path(path))
    if len(tracked_allowlisted) > max_files:
        raise RepositorySnapshotError(
            "Repository snapshot exceeds max_files "
            f"({len(tracked_allowlisted)} > {max_files})."
        )
    relative_paths, tracked_missing_omitted = _collect_tracked_paths(root, tracked_allowlisted)
    git_metadata.update(
        {
            "tracked_included": len(relative_paths),
            "tracked_missing_omitted": tracked_missing_omitted,
            "untracked_omitted": untracked_omitted,
        }
    )
    files: list[dict[str, object]] = []
    total_bytes = 0
    snapshot_digest = hashlib.sha256()

    for relative_path in relative_paths:
        content, executable = _read_text_file(
            root,
            relative_path,
            max_file_bytes=max_file_bytes,
        )
        _scan_for_secrets(relative_path, content)
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise RepositorySnapshotError(
                "Repository snapshot exceeds max_total_bytes "
                f"({total_bytes} > {max_total_bytes})."
            )

        content_sha256 = hashlib.sha256(content).hexdigest()
        path_bytes = relative_path.encode("utf-8")
        snapshot_digest.update(len(path_bytes).to_bytes(8, byteorder="big"))
        snapshot_digest.update(path_bytes)
        snapshot_digest.update(len(content).to_bytes(8, byteorder="big"))
        snapshot_digest.update(content)
        files.append(
            {
                "path": relative_path,
                "content": content,
                "executable": executable,
                "size": len(content),
                "sha256": content_sha256,
            }
        )

    return {
        "format_version": REPOSITORY_SNAPSHOT_VERSION,
        "source": "git_tracked_allowlisted_worktree",
        "repository_name": root.name,
        "git": git_metadata,
        "limits": {
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_files": max_files,
            "text_only": True,
        },
        "summary": {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "sha256": snapshot_digest.hexdigest(),
            "binary_assets_included": False,
            "text_only": True,
            "tracked_missing_omitted": tracked_missing_omitted,
            "untracked_omitted": untracked_omitted,
        },
        "files": files,
    }


def build_source_manifest(
    repository_root: str | Path,
    *,
    source_commit: str | None = None,
    allow_release_root_inventory: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[str, object]:
    """Build a release-time source manifest from Git or an explicit release root.

    ``allow_release_root_inventory`` is intentionally command/build-only. Runtime
    snapshot creation never uses a filesystem inventory as an inclusion fallback;
    it only compares the bounded source allowlist with an existing build manifest.
    """

    _validate_limit("max_file_bytes", max_file_bytes)
    _validate_limit("max_total_bytes", max_total_bytes)
    _validate_limit("max_files", max_files)
    root = _resolve_repository_root(repository_root)
    try:
        git_metadata, tracked_paths, untracked_paths = _read_git_inventory(root)
    except _GitUnavailableError:
        if not allow_release_root_inventory:
            raise RepositorySnapshotError(
                "Git is required unless an explicit release-root inventory is authorized."
            ) from None
        relative_paths = _inventory_explicit_release_root(root, max_files=max_files)
        commit = _validate_source_commit(source_commit)
    else:
        if git_metadata.get("tracked_dirty"):
            raise RepositorySnapshotError(
                "Cannot build a release source manifest from a tracked-dirty worktree."
            )
        untracked_allowlisted = [
            path
            for path in untracked_paths
            if _is_allowlisted_path(path) and path not in SOURCE_MANIFEST_LOCATIONS
        ]
        if untracked_allowlisted:
            raise RepositorySnapshotError(
                "Cannot build a release source manifest while allowlisted untracked files exist."
            )
        _assert_no_tracked_symlinks(root, tracked_paths)
        relative_paths, missing = _collect_tracked_paths(
            root,
            sorted(
                path
                for path in tracked_paths
                if _is_allowlisted_path(path) and path not in SOURCE_MANIFEST_LOCATIONS
            ),
        )
        if missing:
            raise RepositorySnapshotError(
                "Cannot build a source manifest while allowlisted tracked files are missing."
            )
        git_commit = _validate_source_commit(git_metadata.get("commit"))
        if source_commit is not None and _validate_source_commit(source_commit) != git_commit:
            raise RepositorySnapshotError(
                "Source commit override must match the Git worktree HEAD."
            )
        commit = git_commit

    if len(relative_paths) > max_files:
        raise RepositorySnapshotError(
            "Source manifest exceeds max_files "
            f"({len(relative_paths)} > {max_files})."
        )
    files: list[dict[str, object]] = []
    total_bytes = 0
    for relative_path in relative_paths:
        content, executable = _read_text_file(
            root,
            relative_path,
            max_file_bytes=max_file_bytes,
        )
        _scan_for_secrets(relative_path, content)
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise RepositorySnapshotError(
                "Source manifest exceeds max_total_bytes "
                f"({total_bytes} > {max_total_bytes})."
            )
        files.append(
            {
                "path": relative_path,
                "baseline_sha256": hashlib.sha256(content).hexdigest(),
                "executable": executable,
            }
        )
    if not files:
        raise RepositorySnapshotError("Source manifest would contain no source files.")
    return {
        "format": SOURCE_MANIFEST_FORMAT,
        "version": SOURCE_MANIFEST_VERSION,
        "source_commit": commit,
        "files": files,
    }


def write_source_manifest_atomic(
    repository_root: str | Path,
    manifest: dict[str, object],
    *,
    output_path: str = "config/handoff_source_manifest.json",
    replace: bool = False,
) -> Path:
    """Publish a source manifest inside the release root without partial writes."""

    root = _resolve_repository_root(repository_root)
    if output_path not in SOURCE_MANIFEST_LOCATIONS:
        raise RepositorySnapshotError("Source manifest output path is not an approved location.")
    destination = root / output_path
    parent = destination.parent
    if parent.is_symlink():
        raise RepositorySnapshotError("Source manifest output directory must not be a symlink.")
    try:
        parent.mkdir(parents=True, exist_ok=True)
        parent_resolved = parent.resolve(strict=True)
    except OSError as exc:
        raise RepositorySnapshotError("Source manifest output directory is not accessible.") from exc
    if not parent_resolved.is_relative_to(root):
        raise RepositorySnapshotError("Source manifest output directory escapes the release root.")
    if destination.is_symlink():
        raise RepositorySnapshotError("Source manifest output must not be a symlink.")
    if destination.exists() and not replace:
        raise RepositorySnapshotError("Source manifest already exists; use explicit replacement.")

    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    payload += b"\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".handoff_source_manifest.",
        suffix=".part",
        dir=parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o644)
        with os.fdopen(file_descriptor, "wb") as output_file:
            file_descriptor = -1
            output_file.write(payload)
            output_file.flush()
            os.fsync(output_file.fileno())
        if replace:
            os.replace(temporary_path, destination)
        else:
            try:
                os.link(temporary_path, destination, follow_symlinks=False)
            except FileExistsError as exc:
                raise RepositorySnapshotError(
                    "Source manifest already exists; no file was overwritten."
                ) from exc
            temporary_path.unlink()
        directory_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    return destination


def _build_manifest_repository_snapshot(
    root: Path,
    *,
    git_error: RepositorySnapshotError,
    max_file_bytes: int,
    max_total_bytes: int,
    max_files: int,
) -> dict[str, Any]:
    manifest_path = _locate_source_manifest(root, git_error=git_error)
    manifest_content, _manifest_executable = _read_text_file(
        root,
        manifest_path,
        max_file_bytes=max_file_bytes,
    )
    manifest = _parse_source_manifest(manifest_content, max_files=max_files)
    entries = manifest["files"]
    if not isinstance(entries, list):  # Kept as a defensive type guard.
        raise RepositorySnapshotError("Source manifest files must be a list.")
    listed_paths = {str(entry["path"]) for entry in entries if isinstance(entry, dict)}
    observed_paths = set(_inventory_explicit_release_root(root, max_files=max_files))
    if observed_paths - listed_paths:
        raise RepositorySnapshotError(
            "Allowlisted release source exists outside the build-time manifest; "
            "rebuild the release manifest before creating an AI handoff."
        )

    files: list[dict[str, object]] = []
    missing_files: list[dict[str, object]] = []
    total_bytes = 0
    snapshot_digest = hashlib.sha256()
    matching_count = 0
    modified_count = 0
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):  # Validated by _parse_source_manifest.
            raise RepositorySnapshotError(
                f"Source manifest file entry {entry_index} must be an object."
            )
        relative_path = str(entry["path"])
        baseline_sha256 = str(entry["baseline_sha256"])
        baseline_executable = bool(entry["executable"])
        path = root / relative_path
        if not path.exists() and not path.is_symlink():
            missing_files.append(
                {
                    "path": relative_path,
                    "baseline_sha256": baseline_sha256,
                    "executable": baseline_executable,
                }
            )
            continue
        content, executable = _read_text_file(
            root,
            relative_path,
            max_file_bytes=max_file_bytes,
        )
        _scan_for_secrets(relative_path, content)
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise RepositorySnapshotError(
                "Repository snapshot exceeds max_total_bytes "
                f"({total_bytes} > {max_total_bytes})."
            )
        content_sha256 = hashlib.sha256(content).hexdigest()
        matches_baseline = (
            content_sha256 == baseline_sha256 and executable == baseline_executable
        )
        if matches_baseline:
            matching_count += 1
        else:
            modified_count += 1
        path_bytes = relative_path.encode("utf-8")
        snapshot_digest.update(len(path_bytes).to_bytes(8, byteorder="big"))
        snapshot_digest.update(path_bytes)
        snapshot_digest.update(len(content).to_bytes(8, byteorder="big"))
        snapshot_digest.update(content)
        files.append(
            {
                "path": relative_path,
                "content": content,
                "executable": executable,
                "size": len(content),
                "sha256": content_sha256,
                "baseline_sha256": baseline_sha256,
                "baseline_executable": baseline_executable,
                "matches_baseline": matches_baseline,
            }
        )

    source_commit = str(manifest["source_commit"])
    git_metadata = {
        "available": False,
        "commit": source_commit,
        "branch": None,
        "detached": False,
        "tracked_dirty": bool(modified_count or missing_files),
        "tracked_included": len(files),
        "tracked_missing_omitted": len(missing_files),
        "untracked_omitted": 0,
        "inventory_source": "build_time_source_manifest",
        "inventory_scope": "bounded_allowlisted_paths_compared_to_manifest",
        "unlisted_files_inspected": True,
    }
    return {
        "format_version": REPOSITORY_SNAPSHOT_VERSION,
        "source": "build_time_manifest_allowlisted_worktree",
        "repository_name": root.name,
        "git": git_metadata,
        "release_manifest": {
            "path": manifest_path,
            "format": SOURCE_MANIFEST_FORMAT,
            "version": SOURCE_MANIFEST_VERSION,
            "source_commit": source_commit,
            "sha256": hashlib.sha256(manifest_content).hexdigest(),
            "listed_file_count": len(entries),
            "baseline_matching_count": matching_count,
            "modified_count": modified_count,
            "missing_count": len(missing_files),
            "missing_files": missing_files,
            "inventory_scope": "bounded_allowlisted_paths_compared_to_manifest",
            "unlisted_files_inspected": True,
        },
        "limits": {
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_files": max_files,
            "text_only": True,
        },
        "summary": {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "sha256": snapshot_digest.hexdigest(),
            "binary_assets_included": False,
            "text_only": True,
            "tracked_missing_omitted": len(missing_files),
            "untracked_omitted": 0,
            "baseline_matching_count": matching_count,
            "modified_count": modified_count,
            "missing_count": len(missing_files),
            "inventory_scope": "bounded_allowlisted_paths_compared_to_manifest",
            "unlisted_files_inspected": True,
        },
        "files": files,
    }


def _locate_source_manifest(root: Path, *, git_error: RepositorySnapshotError) -> str:
    existing = [
        location
        for location in SOURCE_MANIFEST_LOCATIONS
        if (root / location).exists() or (root / location).is_symlink()
    ]
    if not existing:
        raise RepositorySnapshotError(
            "Git is required unless a build-time handoff source manifest is present."
        ) from git_error
    if len(existing) != 1:
        raise RepositorySnapshotError(
            "Multiple handoff source manifests are present; source inventory is ambiguous."
        )
    relative_path = existing[0]
    _assert_safe_regular_file(root, root / relative_path, relative_path)
    return relative_path


def _parse_source_manifest(content: bytes, *, max_files: int) -> dict[str, object]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositorySnapshotError("Build-time handoff source manifest is invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RepositorySnapshotError("Build-time handoff source manifest must be an object.")
    expected_keys = {"format", "version", "source_commit", "files"}
    if set(payload) != expected_keys:
        raise RepositorySnapshotError(
            "Build-time handoff source manifest has an unsupported field set."
        )
    if payload.get("format") != SOURCE_MANIFEST_FORMAT:
        raise RepositorySnapshotError("Build-time handoff source manifest format is unsupported.")
    if payload.get("version") != SOURCE_MANIFEST_VERSION:
        raise RepositorySnapshotError("Build-time handoff source manifest version is unsupported.")
    _validate_source_commit(payload.get("source_commit"))
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise RepositorySnapshotError("Build-time handoff source manifest files must be non-empty.")
    if len(entries) > max_files:
        raise RepositorySnapshotError(
            "Build-time handoff source manifest exceeds max_files "
            f"({len(entries)} > {max_files})."
        )
    seen_paths: set[str] = set()
    previous_path: str | None = None
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "baseline_sha256",
            "executable",
        }:
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} is invalid."
            )
        relative_path = entry.get("path")
        baseline_sha256 = entry.get("baseline_sha256")
        executable = entry.get("executable")
        if not isinstance(relative_path, str) or not _is_allowlisted_path(relative_path):
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} has an unsafe path."
            )
        if relative_path in SOURCE_MANIFEST_LOCATIONS:
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} is self-referential."
            )
        _assert_safe_source_filename(relative_path)
        if relative_path in seen_paths:
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} duplicates a path."
            )
        if previous_path is not None and relative_path <= previous_path:
            raise RepositorySnapshotError(
                "Build-time handoff source manifest files must be strictly path-sorted."
            )
        if not isinstance(baseline_sha256, str) or _SHA256_RE.fullmatch(
            baseline_sha256
        ) is None:
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} has an invalid digest."
            )
        if not isinstance(executable, bool):
            raise RepositorySnapshotError(
                f"Build-time handoff source manifest entry {entry_index} has an invalid mode."
            )
        seen_paths.add(relative_path)
        previous_path = relative_path
    return payload


def _validate_source_commit(value: object) -> str:
    if not isinstance(value, str) or _GIT_COMMIT_RE.fullmatch(value) is None:
        raise RepositorySnapshotError("Source commit must be a full Git object identifier.")
    return value.lower()


def _inventory_explicit_release_root(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
) -> list[str]:
    paths: list[str] = []

    def append_path(relative_path: str) -> None:
        paths.append(relative_path)
        if len(paths) > max_files:
            raise RepositorySnapshotError(
                "Allowlisted release source exceeds max_files "
                f"({len(paths)} > {max_files})."
            )

    for relative_path in ROOT_FILE_ALLOWLIST:
        candidate = root / relative_path
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if _is_allowlisted_path(relative_path):
            _assert_safe_regular_file(root, candidate, relative_path)
            append_path(relative_path)

    for directory_name in ROOT_DIRECTORY_ALLOWLIST:
        directory = root / directory_name
        if not directory.exists() and not directory.is_symlink():
            continue
        if directory.is_symlink():
            raise RepositorySnapshotError(
                "Symbolic links are not allowed in an explicit release-root inventory."
            )
        if not directory.is_dir():
            raise RepositorySnapshotError(
                "Expected an allowlisted release-root directory."
            )
        for current_root, directory_names, file_names in os.walk(
            directory,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_root)
            safe_directories: list[str] = []
            for name in sorted(directory_names):
                child = current / name
                if child.is_symlink():
                    raise RepositorySnapshotError(
                        "Symbolic links are not allowed in an explicit release-root inventory."
                    )
                if name.casefold() not in _EXCLUDED_DIRECTORY_NAMES:
                    safe_directories.append(name)
            directory_names[:] = safe_directories
            for file_name in sorted(file_names):
                candidate = current / file_name
                relative_path = candidate.relative_to(root).as_posix()
                if relative_path in SOURCE_MANIFEST_LOCATIONS:
                    continue
                if not _is_allowlisted_path(relative_path):
                    continue
                _assert_safe_regular_file(root, candidate, relative_path)
                append_path(relative_path)
    return sorted(set(paths))


def _validate_limit(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def _resolve_repository_root(repository_root: str | Path | None) -> Path:
    raw_root = Path(repository_root) if repository_root is not None else _DEFAULT_REPOSITORY_ROOT
    if raw_root.is_symlink():
        raise RepositorySnapshotError("Repository root must not be a symbolic link.")
    try:
        root_stat = raw_root.stat()
        root = raw_root.resolve(strict=True)
    except OSError as exc:
        raise RepositorySnapshotError("Repository root is not accessible.") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise RepositorySnapshotError("Repository root must be a directory.")
    return root


def _collect_tracked_paths(root: Path, tracked_paths: list[str]) -> tuple[list[str], int]:
    included: list[str] = []
    missing = 0
    for relative_path in tracked_paths:
        _assert_safe_source_filename(relative_path)
        path = root / relative_path
        if not path.exists() and not path.is_symlink():
            missing += 1
            continue
        _assert_safe_regular_file(root, path, relative_path)
        included.append(relative_path)
    return included, missing


def _assert_no_tracked_symlinks(root: Path, tracked_paths: tuple[str, ...]) -> None:
    for relative_path in tracked_paths:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
            raise RepositorySnapshotError(f"Invalid Git tracked path: {relative_path}")
        in_scope = relative_path in ROOT_FILE_ALLOWLIST or (
            len(pure_path.parts) > 1 and pure_path.parts[0] in ROOT_DIRECTORY_ALLOWLIST
        )
        if in_scope and (root / relative_path).is_symlink():
            raise RepositorySnapshotError(
                f"Symbolic links are not allowed in repository snapshot: {relative_path}"
            )


def _is_allowlisted_path(relative_path: str) -> bool:
    if not relative_path or "\x00" in relative_path:
        return False
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        return False
    parts = pure_path.parts
    if len(parts) == 1:
        return relative_path in ROOT_FILE_ALLOWLIST
    if parts[0] not in ROOT_DIRECTORY_ALLOWLIST:
        return False
    if any(part.casefold() in _EXCLUDED_DIRECTORY_NAMES for part in parts[1:-1]):
        return False
    file_name = parts[-1]
    return not _is_excluded_file(file_name) and pure_path.suffix.casefold() in TEXT_SUFFIX_ALLOWLIST


def _is_excluded_file(file_name: str) -> bool:
    normalized = file_name.casefold()
    return normalized == ".env" or normalized.startswith(".env.")


def _assert_safe_source_filename(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
        return
    normalized_stem = re.sub(r"[_\s]+", "-", path.stem.casefold())
    name_tokens = set(re.split(r"[-.]+", normalized_stem))
    credential_word = bool(name_tokens & {"credential", "credentials", "secret", "secrets"})
    token_name = (
        normalized_stem in _CREDENTIAL_FILE_STEMS
        or normalized_stem.startswith("token-")
        or (normalized_stem.endswith("-token") and normalized_stem != "design-token")
    )
    if credential_word or token_name or any(
        marker in normalized_stem for marker in _CREDENTIAL_FILE_MARKERS
    ):
        raise RepositorySnapshotError(
            f"Credential-like source filename is not allowed: {relative_path}"
        )


def _assert_safe_regular_file(root: Path, path: Path, relative_path: str) -> os.stat_result:
    current = root
    for part in PurePosixPath(relative_path).parts[:-1]:
        current /= part
        if current.is_symlink():
            raise RepositorySnapshotError(
                f"Symbolic links are not allowed in repository snapshot: {relative_path}"
            )
    if path.is_symlink():
        raise RepositorySnapshotError(
            f"Symbolic links are not allowed in repository snapshot: {relative_path}"
        )
    try:
        path_stat = path.stat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RepositorySnapshotError(f"Repository file is not accessible: {relative_path}") from exc
    if not resolved.is_relative_to(root):
        raise RepositorySnapshotError(f"Repository path escapes root: {relative_path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise RepositorySnapshotError(f"Expected regular repository file: {relative_path}")
    try:
        root_device = root.stat().st_dev
    except OSError as exc:
        raise RepositorySnapshotError("Repository root is not accessible.") from exc
    if path_stat.st_dev != root_device:
        raise RepositorySnapshotError(
            f"Repository file must be on the root filesystem: {relative_path}"
        )
    if path_stat.st_nlink != 1:
        raise RepositorySnapshotError(f"Hard-linked repository file is not allowed: {relative_path}")
    return path_stat


def _read_text_file(root: Path, relative_path: str, *, max_file_bytes: int) -> tuple[bytes, bool]:
    path = root / relative_path
    before = _assert_safe_regular_file(root, path, relative_path)
    if before.st_size > max_file_bytes:
        raise RepositorySnapshotError(
            f"Repository file exceeds max_file_bytes: {relative_path} "
            f"({before.st_size} > {max_file_bytes})."
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as exc:
        raise RepositorySnapshotError(f"Repository file could not be opened: {relative_path}") from exc

    try:
        opened = os.fstat(file_descriptor)
        _assert_same_file(before, opened, relative_path)
        chunks: list[bytes] = []
        read_bytes = 0
        while True:
            chunk = os.read(file_descriptor, min(_READ_CHUNK_BYTES, max_file_bytes + 1 - read_bytes))
            if not chunk:
                break
            chunks.append(chunk)
            read_bytes += len(chunk)
            if read_bytes > max_file_bytes:
                raise RepositorySnapshotError(
                    f"Repository file exceeds max_file_bytes while reading: {relative_path}"
                )
        after = os.fstat(file_descriptor)
        _assert_unchanged_file(opened, after, relative_path)
    finally:
        os.close(file_descriptor)

    final_path_stat = _assert_safe_regular_file(root, path, relative_path)
    _assert_unchanged_file(after, final_path_stat, relative_path)
    content = b"".join(chunks)
    if b"\x00" in content:
        raise RepositorySnapshotError(f"NUL byte found in text repository file: {relative_path}")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositorySnapshotError(
            f"Repository text file is not valid UTF-8: {relative_path}"
        ) from exc
    return content, bool(after.st_mode & 0o111)


def _scan_for_secrets(relative_path: str, content: bytes) -> None:
    if _PRIVATE_KEY_RE.search(content):
        _raise_secret(relative_path, "private key")
    database_url_match = _DATABASE_URL_WITH_PASSWORD_RE.search(content)
    if database_url_match is not None:
        password = database_url_match.group(1).decode("utf-8", errors="ignore").casefold()
        if not _is_placeholder_database_password(password):
            _raise_secret(relative_path, "database URL containing a password")
    if _KNOWN_TOKEN_RE.search(content):
        _raise_secret(relative_path, "credential token")
    credential_match = _CREDENTIAL_ASSIGNMENT_RE.search(content)
    if credential_match is not None:
        candidate = credential_match.group(1).decode("ascii", errors="ignore").casefold()
        if candidate not in _PLACEHOLDER_SECRET_VALUES:
            _raise_secret(relative_path, "credential token")
    for secret_match in _GENERIC_SECRET_ASSIGNMENT_RE.finditer(content):
        candidate_bytes = secret_match.group("quoted") or secret_match.group("bare")
        if candidate_bytes is None:
            continue
        candidate = candidate_bytes.decode("utf-8", errors="ignore")
        if not _is_placeholder_or_expression_secret_assignment(candidate):
            _raise_secret(relative_path, "password or secret assignment")
    if PurePosixPath(relative_path).suffix.casefold() == ".json":
        _scan_json_for_service_account_private_key(relative_path, content)


def _is_placeholder_database_password(password: str) -> bool:
    normalized = password.strip().strip("<>{}[]()")
    return (
        not normalized
        or "$" in password
        or normalized
        in {
            "change-me",
            "changeme",
            "dummy",
            "example",
            "pass",
            "password",
            "redacted",
            "your-password",
            "your_password_here",
        }
    )


def _is_placeholder_or_expression_secret_assignment(candidate: str) -> bool:
    normalized = candidate.strip().strip("<>{}[]()").casefold()
    if not normalized or "$" in candidate:
        return True
    if normalized in _PLACEHOLDER_SECRET_VALUES or normalized in {
        "change-me",
        "existing-pass",
        "pass",
        "password",
        "unsafe-dev-key",
        "your-password",
        "your_password_here",
    }:
        return True
    if any(
        marker in normalized
        for marker in (
            "dummy",
            "example",
            "placeholder",
            "redacted",
            "test",
            "demo",
            "secret",
        )
    ):
        return True
    if normalized in {
        "current-secret",
        "old-secret",
        "secret",
        "secret-pass",
        "secret-value",
    }:
        return True
    return "_" in normalized and normalized.replace("_", "").islower()


def _scan_json_for_service_account_private_key(relative_path: str, content: bytes) -> None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict) or payload.get("type") != "service_account":
        return
    private_key = payload.get("private_key")
    if isinstance(private_key, str) and private_key.strip():
        _raise_secret(relative_path, "service-account private_key")


def _raise_secret(relative_path: str, secret_kind: str) -> NoReturn:
    raise RepositorySnapshotError(
        f"High-confidence {secret_kind} detected in repository source: {relative_path}"
    )


def _assert_same_file(before: os.stat_result, after: os.stat_result, relative_path: str) -> None:
    if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (
        after.st_dev,
        after.st_ino,
    ):
        raise RepositorySnapshotError(f"Repository file changed while opening: {relative_path}")


def _assert_unchanged_file(before: os.stat_result, after: os.stat_result, relative_path: str) -> None:
    _assert_same_file(before, after, relative_path)
    before_signature = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_signature = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_signature != after_signature:
        raise RepositorySnapshotError(f"Repository file changed while reading: {relative_path}")


def _read_git_inventory(root: Path) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    try:
        top_level = _run_git_required(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RepositorySnapshotError("Git worktree root is not valid UTF-8.") from exc
    try:
        git_root = Path(top_level).resolve(strict=True)
        starter_app = (
            root.name == "app"
            and root.parent == git_root
            and (git_root / "PUBLIC_BUILD.json").is_file()
        )
        if git_root != root and not starter_app:
            raise RepositorySnapshotError("Repository root must be the Git worktree root.")
    except OSError as exc:
        raise RepositorySnapshotError("Git worktree root is not accessible.") from exc

    commit = _run_git_optional(root, "rev-parse", "--verify", "HEAD")
    if commit is not None and _GIT_COMMIT_RE.fullmatch(commit) is None:
        raise RepositorySnapshotError("Git returned an invalid commit identifier.")

    branch = _run_git_optional(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    status = _run_git_required(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=no",
        "--ignore-submodules=all",
    )
    tracked_paths = _decode_git_paths(
        _run_git_required(root, "ls-files", "--cached", "-z"),
        label="tracked",
    )
    untracked_paths = _decode_git_paths(
        _run_git_required(root, "ls-files", "--others", "--exclude-standard", "-z"),
        label="untracked",
    )
    metadata = {
        "available": True,
        "commit": commit,
        "branch": branch,
        "detached": branch is None and commit is not None,
        "tracked_dirty": bool(status),
    }
    return metadata, tracked_paths, untracked_paths


def _decode_git_paths(output: bytes, *, label: str) -> tuple[str, ...]:
    try:
        paths = tuple(part.decode("utf-8") for part in output.split(b"\x00") if part)
    except UnicodeDecodeError as exc:
        raise RepositorySnapshotError(f"Git {label} paths are not valid UTF-8.") from exc
    return tuple(sorted(set(paths)))


def _run_git_optional(root: Path, *arguments: str) -> str | None:
    completed = _run_git_process(root, *arguments)
    if completed is None or completed.returncode != 0:
        return None
    try:
        return completed.stdout.decode("utf-8").strip() or None
    except UnicodeDecodeError:
        return None


def _run_git_required(root: Path, *arguments: str) -> bytes:
    completed = _run_git_process(root, *arguments)
    if completed is None or completed.returncode != 0:
        raise _GitUnavailableError("Git is required to build a repository snapshot.")
    return completed.stdout


def _run_git_process(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
