from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tarfile
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

WORKSPACE_ARCHIVE_ROOT = "TempleDB"
TENANT_POLICY_SOURCE = Path("config/tenant_policy/default")
TENANT_PREFERENCES_SOURCE = Path("config/tenant_preferences")
POSTAL_SCAN_PRIVATE_SOURCE = Path("data/private/auxiliary/annual_membership_fee_postal_scans")
POSTAL_SCAN_BUNDLE_ROOT = Path("private/annual_membership_fee_postal_scans")
PRIVATE_MIGRATION_PAYLOAD_ROOT = Path("private/migration_payload")
PRIVATE_MIGRATION_WORKSPACE_ROOT = PRIVATE_MIGRATION_PAYLOAD_ROOT / "workspace"
TENANT_POLICY_ARCHIVE_ROOT = PRIVATE_MIGRATION_WORKSPACE_ROOT / TENANT_POLICY_SOURCE
TENANT_PREFERENCES_ARCHIVE_ROOT = (
    PRIVATE_MIGRATION_WORKSPACE_ROOT / TENANT_PREFERENCES_SOURCE
)
PRIVATE_MIGRATION_MANIFEST_PATH = PRIVATE_MIGRATION_PAYLOAD_ROOT / "MANIFEST.json"
ARCHIVE_MANIFEST_PATH = Path("docs/archive_manifest.json")
ARCHIVE_CHECKSUMS_PATH = Path("docs/checksums.txt")
ARCHIVE_MANIFEST_VERSION = 1
PRIVATE_MIGRATION_MANIFEST_VERSION = 1
EXCLUDED_TOP_LEVEL_PATHS = {
    ".venv",
    "staticfiles",
    "templedb.egg-info",
    "data/generated",
    "data/product",
    "data/runtime",
    "data/private",
    "config/tenant_preferences",
}
EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
GENERATED_CACHE_DIR_NAMES = {
    ".cache",
    "cache",
    "caches",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
RUNTIME_TRANSIENT_DIR_NAMES = {
    ".cache",
    "cache",
    "caches",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
RUNTIME_TRANSIENT_FILE_SUFFIXES = (
    ".pid",
    ".lock",
    ".guard",
    ".part",
    ".tmp",
    ".temp",
    ".swp",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".sqlite3-journal",
)


@dataclass(frozen=True)
class _ArchiveMember:
    archive_path: str
    member_type: str
    mode: int
    size: int
    sha256: str
    category: str
    source_path: Path | None = None
    content: bytes | None = None
    source_device: int = 0
    source_inode: int = 0
    source_mtime_ns: int = 0
    source_ctime_ns: int = 0

    def manifest_row(self) -> dict[str, object]:
        return {
            "path": self.archive_path,
            "type": self.member_type,
            "mode": f"{self.mode:04o}",
            "size": self.size,
            "sha256": self.sha256 or None,
            "category": self.category,
        }

    def fingerprint(self) -> tuple[object, ...]:
        return (
            self.archive_path,
            self.member_type,
            self.mode,
            self.size,
            self.sha256,
            self.category,
            self.source_device,
            self.source_inode,
            self.source_mtime_ns,
            self.source_ctime_ns,
        )


class _HashingReader:
    def __init__(self, file_object: BinaryIO) -> None:
        self._file_object = file_object
        self._digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self._file_object.read(size)
        self._digest.update(chunk)
        return chunk

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class _UnsafeArchiveSourceError(RuntimeError):
    pass


def _validate_backup_manifest_for_bundle(
    runtime,
    backup_run,
    backup_file_path: Path,
) -> tuple[Path, str]:
    raw_path = (getattr(backup_run, "manifest_file_path", "") or "").strip()
    if not raw_path:
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_BACKUP_MANIFEST_REQUIRED] バックアップmanifestがありません。"
        )
    manifest_path = Path(raw_path)
    try:
        content = _read_stable_regular_file(manifest_path, max_bytes=4 * 1024 * 1024)
        manifest = json.loads(content.decode("utf-8"))
    except _UnsafeArchiveSourceError as exc:
        raise runtime.BackupServiceError(str(exc)) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_BACKUP_MANIFEST_INVALID] バックアップmanifestを検証できません。"
        ) from exc
    if not isinstance(manifest, dict):
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_BACKUP_MANIFEST_INVALID] バックアップmanifestを検証できません。"
        )
    actual_size = backup_file_path.stat().st_size
    actual_sha256 = (getattr(backup_run, "backup_sha256", "") or "").strip().lower()
    expected = {
        "backup_run_id": getattr(backup_run, "id", None),
        "backup_file_name": backup_file_path.name,
        "backup_file_size": actual_size,
        "backup_sha256": actual_sha256,
    }
    actual = {
        "backup_run_id": manifest.get("backup_run_id"),
        "backup_file_name": manifest.get("backup_file_name"),
        "backup_file_size": manifest.get("backup_file_size"),
        "backup_sha256": str(manifest.get("backup_sha256") or "").lower(),
    }
    if not actual_sha256 or actual != expected:
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_BACKUP_MANIFEST_MISMATCH] バックアップmanifestが選択中のrunと一致しません。"
        )
    return manifest_path, hashlib.sha256(content).hexdigest()


def _capture_git_snapshot(workspace_root: Path) -> dict[str, object]:
    git_root = workspace_root / ".git"
    try:
        root_stat = os.lstat(workspace_root)
        git_stat = os.lstat(git_root)
        head_stat = os.lstat(git_root / "HEAD")
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_GIT_REQUIRED] 完全な.git metadataが見つかりません。"
        ) from exc
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or not stat.S_ISDIR(git_stat.st_mode)
        or git_stat.st_dev != root_stat.st_dev
        or not stat.S_ISREG(head_stat.st_mode)
        or head_stat.st_nlink != 1
    ):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_GIT_REQUIRED] 完全な.git metadataが見つかりません。"
        )

    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"

    def _git_output(arguments: list[str], *, allow_failure: bool = False) -> bytes:
        completed = subprocess.run(
            ["git", "-C", str(workspace_root), *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
        if completed.returncode and not allow_failure:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_GIT_INVALID] Git metadataを検証できません。"
            )
        return completed.stdout if completed.returncode == 0 else b""

    head = _git_output(["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
    branch = _git_output(["symbolic-ref", "--quiet", "HEAD"], allow_failure=True).decode(
        "utf-8", errors="strict"
    ).strip()
    status = _git_output(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    return {
        "head": head,
        "branch": branch,
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "status_entry_count": status.count(b"\0"),
    }


def _validate_migration_source_roots(
    workspace_root: Path,
    tenant_root: Path,
) -> bool:
    """Validate Platform/Tenant roots and return whether they are the same root."""

    try:
        workspace_stat = os.lstat(workspace_root)
        tenant_stat = os.lstat(tenant_root)
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_ROOT_INVALID] "
            "Platformまたはtenant rootを安全に確認できません。"
        ) from exc
    if (
        stat.S_ISLNK(workspace_stat.st_mode)
        or not stat.S_ISDIR(workspace_stat.st_mode)
        or stat.S_ISLNK(tenant_stat.st_mode)
        or not stat.S_ISDIR(tenant_stat.st_mode)
    ):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_ROOT_INVALID] "
            "Platformまたはtenant rootが通常directoryではありません。"
        )

    workspace_real = Path(os.path.realpath(workspace_root))
    tenant_real = Path(os.path.realpath(tenant_root))
    if workspace_real == tenant_real:
        return True
    if workspace_real in tenant_real.parents or tenant_real in workspace_real.parents:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_ROOT_OVERLAP] "
            "分離したPlatform rootとtenant rootを親子関係にはできません。"
        )
    return False


def _collect_bundle_source_members(
    workspace_root: Path,
    *,
    runtime_database_exclusions: set[str],
    tenant_root: Path | None = None,
    tenant_runtime_database_exclusions: set[str] | None = None,
) -> tuple[list[_ArchiveMember], list[dict[str, str]]]:
    workspace_root = workspace_root.absolute()
    tenant_root = (tenant_root or workspace_root).absolute()
    roots_are_shared = _validate_migration_source_roots(
        workspace_root,
        tenant_root,
    )
    if roots_are_shared:
        tenant_runtime_database_exclusions = runtime_database_exclusions
    elif tenant_runtime_database_exclusions is None:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_TENANT_DB_EXCLUSIONS_REQUIRED] "
            "外部tenant rootの稼働DB除外条件を確認できません。"
        )

    members = _collect_tree_archive_members(
        workspace_root,
        Path(WORKSPACE_ARCHIVE_ROOT),
        category="workspace",
        excluded=lambda path, is_dir: _is_workspace_path_excluded(path, is_dir=is_dir)
        or path.as_posix() in runtime_database_exclusions,
        private=False,
        git_metadata=True,
    )
    if not any(member.archive_path == f"{WORKSPACE_ARCHIVE_ROOT}/.git/HEAD" for member in members):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_GIT_REQUIRED] .git/HEADを収録できません。"
        )
    members.extend(
        _collect_tracked_placeholder_members(
            workspace_root,
            runtime_database_exclusions=runtime_database_exclusions,
        )
    )

    selection: list[dict[str, str]] = []
    env_source = workspace_root / ".env"
    env_archive = PRIVATE_MIGRATION_WORKSPACE_ROOT / ".env"
    if ".env" in runtime_database_exclusions:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_ENV_IS_LIVE_DATABASE] .envが稼働SQLite pathと衝突しているため作成を中止しました。"
        )
    env_member = _optional_single_file_member(
        env_source,
        env_archive,
        category="private_payload",
    )
    if env_member is None:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_ENV_REQUIRED] 現行checkoutの.envを安全に収録できません。"
        )
    members.append(env_member)
    selection.append(_selection_row(".env", env_archive, env_member is not None))

    tenant_policy_root = tenant_root / TENANT_POLICY_SOURCE
    tenant_policy_exists = os.path.lexists(tenant_policy_root)
    if roots_are_shared:
        tenant_policy_archive_root = (
            Path(WORKSPACE_ARCHIVE_ROOT) / TENANT_POLICY_SOURCE
        )
    else:
        if not tenant_policy_exists:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_TENANT_POLICY_REQUIRED] "
                "外部tenant rootのtenant policyが見つかりません。"
            )
        tenant_policy_archive_root = TENANT_POLICY_ARCHIVE_ROOT
        members.extend(
            _collect_tree_archive_members(
                tenant_policy_root,
                tenant_policy_archive_root,
                category="private_payload",
                private=True,
            )
        )
    selection.append(
        _selection_row(
            TENANT_POLICY_SOURCE.as_posix(),
            tenant_policy_archive_root,
            tenant_policy_exists,
        )
    )

    tenant_preferences_root = tenant_root / TENANT_PREFERENCES_SOURCE
    tenant_preferences_exists = os.path.lexists(tenant_preferences_root)
    if tenant_preferences_exists:
        tenant_preference_members = _collect_tree_archive_members(
            tenant_preferences_root,
            TENANT_PREFERENCES_ARCHIVE_ROOT,
            category="private_payload",
            excluded=lambda path, is_dir: _is_workspace_relative_file_excluded(
                TENANT_PREFERENCES_SOURCE / path,
                is_dir=is_dir,
                excluded_relative_files=tenant_runtime_database_exclusions,
            ),
            private=True,
        )
        if any(
            member.member_type == "file"
            and Path(member.archive_path).suffix.casefold() != ".json"
            for member in tenant_preference_members
        ):
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_TENANT_PREFERENCES_INVALID] "
                "tenant preferencesにはJSON fileだけを収録できます。"
            )
        members.extend(tenant_preference_members)
    selection.append(
        _selection_row(
            TENANT_PREFERENCES_SOURCE.as_posix(),
            TENANT_PREFERENCES_ARCHIVE_ROOT,
            tenant_preferences_exists,
        )
    )

    private_root = tenant_root / "data/private"
    private_archive_root = PRIVATE_MIGRATION_WORKSPACE_ROOT / "data/private"
    private_exists = os.path.lexists(private_root)
    if private_exists:
        members.extend(
            _collect_tree_archive_members(
                private_root,
                private_archive_root,
                category="private_payload",
                excluded=lambda path, is_dir: _is_private_postal_subtree(path)
                or _is_workspace_relative_file_excluded(
                    Path("data/private") / path,
                    is_dir=is_dir,
                    excluded_relative_files=tenant_runtime_database_exclusions,
                ),
                private=True,
            )
        )
    selection.append(_selection_row("data/private", private_archive_root, private_exists))

    postal_root = tenant_root / POSTAL_SCAN_PRIVATE_SOURCE
    postal_exists = os.path.lexists(postal_root)
    if postal_exists:
        members.extend(
            _collect_tree_archive_members(
                postal_root,
                POSTAL_SCAN_BUNDLE_ROOT,
                category="postal_scans",
                excluded=lambda path, is_dir: _is_workspace_relative_file_excluded(
                    POSTAL_SCAN_PRIVATE_SOURCE / path,
                    is_dir=is_dir,
                    excluded_relative_files=tenant_runtime_database_exclusions,
                ),
                private=True,
            )
        )
    selection.append(_selection_row(POSTAL_SCAN_PRIVATE_SOURCE, POSTAL_SCAN_BUNDLE_ROOT, postal_exists))

    runtime_root = tenant_root / "data/runtime"
    runtime_archive_root = PRIVATE_MIGRATION_WORKSPACE_ROOT / "data/runtime"
    runtime_exists = os.path.lexists(runtime_root)
    if runtime_exists:
        members.extend(
            _collect_tree_archive_members(
                runtime_root,
                runtime_archive_root,
                category="runtime_snapshot",
                excluded=lambda path, is_dir: _is_runtime_snapshot_excluded(path, is_dir)
                or _is_workspace_relative_file_excluded(
                    Path("data/runtime") / path,
                    is_dir=is_dir,
                    excluded_relative_files=tenant_runtime_database_exclusions,
                ),
                private=True,
            )
        )
    selection.append(_selection_row("data/runtime", runtime_archive_root, runtime_exists))

    generated_root = tenant_root / "data/generated"
    generated_archive_root = PRIVATE_MIGRATION_WORKSPACE_ROOT / "data/generated"
    generated_exists = os.path.lexists(generated_root)
    if generated_exists:
        members.extend(
            _collect_tree_archive_members(
                generated_root,
                generated_archive_root,
                category="generated_snapshot",
                excluded=lambda path, is_dir: _is_generated_snapshot_excluded(path, is_dir)
                or _is_workspace_relative_file_excluded(
                    Path("data/generated") / path,
                    is_dir=is_dir,
                    excluded_relative_files=tenant_runtime_database_exclusions,
                ),
                private=True,
            )
        )
    selection.append(_selection_row("data/generated", generated_archive_root, generated_exists))

    source_registry_archive = PRIVATE_MIGRATION_WORKSPACE_ROOT / "data/runtime/source_registry.json"
    registry_included = any(
        member.archive_path == source_registry_archive.as_posix() and member.member_type == "file"
        for member in members
    )
    selection.append(
        _selection_row("data/runtime/source_registry.json", source_registry_archive, registry_included)
    )
    return sorted(members, key=lambda member: member.archive_path), selection


def _collect_tracked_placeholder_members(
    workspace_root: Path,
    *,
    runtime_database_exclusions: set[str],
) -> list[_ArchiveMember]:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    completed = subprocess.run(
        ["git", "-C", str(workspace_root), "ls-files", "-z", "--cached"],
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_GIT_INVALID] Git tracked placeholderを検証できません。"
        )
    workspace_device = os.lstat(workspace_root).st_dev
    members: list[_ArchiveMember] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative_path = Path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_GIT_PATH_INVALID] Git tracked pathを安全に解釈できません。"
            ) from exc
        if relative_path.name != ".gitkeep":
            continue
        if relative_path.parts[:2] not in {
            ("data", "private"),
            ("data", "runtime"),
            ("data", "generated"),
        }:
            continue
        if relative_path.as_posix() in runtime_database_exclusions:
            continue
        source_path = workspace_root / relative_path
        if not os.path.lexists(source_path):
            continue
        members.append(
            _source_file_archive_member(
                source_path,
                (Path(WORKSPACE_ARCHIVE_ROOT) / relative_path).as_posix(),
                category="workspace_placeholder",
                private=False,
                expected_device=workspace_device,
            )
        )
    return members


def _selection_row(source_path: str | Path, archive_path: Path, included: bool) -> dict[str, str]:
    return {
        "source_path": Path(source_path).as_posix(),
        "archive_path": archive_path.as_posix(),
        "status": "included" if included else "absent",
    }


def _optional_single_file_member(
    source_path: Path,
    archive_path: Path,
    *,
    category: str,
) -> _ArchiveMember | None:
    if not os.path.lexists(source_path):
        return None
    return _source_file_archive_member(
        source_path,
        archive_path.as_posix(),
        category=category,
        private=True,
    )


def _collect_tree_archive_members(
    source_root: Path,
    archive_root: Path,
    *,
    category: str,
    excluded=None,
    private: bool,
    git_metadata: bool = False,
) -> list[_ArchiveMember]:
    excluded = excluded or (lambda _path, _is_dir: False)
    try:
        root_stat = os.lstat(source_root)
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_UNREADABLE] 収録元を安全に読み取れません。"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_ROOT_INVALID] 収録元rootが通常directoryではありません。"
        )
    root_device = root_stat.st_dev
    members = [
        _directory_archive_member(
            archive_root.as_posix(),
            category=category,
            source_path=source_root,
            source_stat=root_stat,
        )
    ]

    def _walk(current_root: Path, relative_root: Path) -> None:
        try:
            with os.scandir(current_root) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_UNREADABLE] 収録元を安全に読み取れません。"
            ) from exc
        for entry in entries:
            relative_path = relative_root / entry.name
            try:
                entry_stat = os.lstat(entry.path)
            except OSError as exc:
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録元が走査中に変更されました。"
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_SYMLINK_REJECTED] symlinkを含むため作成を中止しました。"
                )
            if entry_stat.st_dev != root_device:
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_CROSS_DEVICE_REJECTED] 収録root内の別deviceを拒否しました。"
                )
            is_dir = stat.S_ISDIR(entry_stat.st_mode)
            is_file = stat.S_ISREG(entry_stat.st_mode)
            if not is_dir and not is_file:
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_SPECIAL_FILE_REJECTED] 通常file/directory以外を含むため作成を中止しました。"
                )
            if git_metadata and relative_path.parts[:1] == (".git",) and entry.name.endswith(
                ".lock"
            ):
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_GIT_LOCKED] Git操作中またはlock残存中のため作成を中止しました。"
                )
            if excluded(relative_path, is_dir):
                continue
            archive_path = archive_root / relative_path
            if is_dir:
                members.append(
                    _directory_archive_member(
                        archive_path.as_posix(),
                        category=category,
                        source_path=Path(entry.path),
                        source_stat=entry_stat,
                    )
                )
                _walk(Path(entry.path), relative_path)
                continue
            if entry_stat.st_nlink != 1:
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_HARDLINK_REJECTED] hardlinkを含むため作成を中止しました。"
                )
            members.append(
                _source_file_archive_member(
                    Path(entry.path),
                    archive_path.as_posix(),
                    category=category,
                    private=private,
                    expected_device=root_device,
                )
            )

    _walk(source_root, Path())
    return members


def _directory_archive_member(
    archive_path: str,
    *,
    category: str,
    source_path: Path | None = None,
    source_stat=None,
) -> _ArchiveMember:
    _validated_archive_path(archive_path)
    return _ArchiveMember(
        archive_path=archive_path,
        member_type="directory",
        mode=0o700,
        size=0,
        sha256="",
        category=category,
        source_path=source_path,
        source_device=getattr(source_stat, "st_dev", 0),
        source_inode=getattr(source_stat, "st_ino", 0),
        source_mtime_ns=getattr(source_stat, "st_mtime_ns", 0),
        source_ctime_ns=getattr(source_stat, "st_ctime_ns", 0),
    )


def _source_file_archive_member(
    source_path: Path,
    archive_path: str,
    *,
    category: str,
    private: bool,
    expected_device: int | None = None,
) -> _ArchiveMember:
    _validated_archive_path(archive_path)
    size, sha256, source_stat = _stable_regular_file_metadata(
        source_path,
        expected_device=expected_device,
    )
    source_executable = bool(source_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    mode = 0o600 if private or not source_executable else 0o700
    return _ArchiveMember(
        archive_path=archive_path,
        member_type="file",
        mode=mode,
        size=size,
        sha256=sha256,
        category=category,
        source_path=source_path,
        source_device=source_stat.st_dev,
        source_inode=source_stat.st_ino,
        source_mtime_ns=source_stat.st_mtime_ns,
        source_ctime_ns=source_stat.st_ctime_ns,
    )


def _stable_regular_file_metadata(
    source_path: Path,
    *,
    expected_device: int | None = None,
) -> tuple[int, str, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_UNREADABLE] 収録fileを安全に読み取れません。"
        ) from exc
    try:
        before = os.fstat(descriptor)
        _validate_open_regular_file(before, expected_device=expected_device)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        _ensure_same_stat(before, after)
        return before.st_size, digest.hexdigest(), before
    finally:
        os.close(descriptor)


def _read_stable_regular_file(source_path: Path, *, max_bytes: int) -> bytes:
    size, expected_sha256, _source_stat = _stable_regular_file_metadata(source_path)
    if size > max_bytes:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_MANIFEST_TOO_LARGE] manifestのsize上限を超えています。"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_UNREADABLE] 収録fileを安全に読み取れません。"
        ) from exc
    try:
        before = os.fstat(descriptor)
        _validate_open_regular_file(before)
        content = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        _ensure_same_stat(before, after)
    finally:
        os.close(descriptor)
    if len(content) != size or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録fileが読み取り中に変更されました。"
        )
    return content


def _validate_open_regular_file(source_stat, *, expected_device: int | None = None) -> None:
    if not stat.S_ISREG(source_stat.st_mode):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SPECIAL_FILE_REJECTED] 通常file以外を含むため作成を中止しました。"
        )
    if source_stat.st_nlink != 1:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_HARDLINK_REJECTED] hardlinkを含むため作成を中止しました。"
        )
    if expected_device is not None and source_stat.st_dev != expected_device:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_CROSS_DEVICE_REJECTED] 収録root内の別deviceを拒否しました。"
        )


def _ensure_same_stat(before, after) -> None:
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録fileが読み取り中に変更されました。"
        )


def _is_private_postal_subtree(relative_path: Path) -> bool:
    postal_relative = POSTAL_SCAN_PRIVATE_SOURCE.relative_to("data/private")
    return relative_path == postal_relative or postal_relative in relative_path.parents


def _is_generated_snapshot_excluded(relative_path: Path, is_dir: bool) -> bool:
    return is_dir and relative_path.name.casefold() in GENERATED_CACHE_DIR_NAMES


def _is_runtime_snapshot_excluded(relative_path: Path, is_dir: bool) -> bool:
    if is_dir:
        return relative_path.name.casefold() in RUNTIME_TRANSIENT_DIR_NAMES
    name = relative_path.name.casefold()
    return name.endswith(RUNTIME_TRANSIENT_FILE_SUFFIXES) or name.endswith("~")


def _is_workspace_relative_file_excluded(
    workspace_relative_path: Path,
    *,
    is_dir: bool,
    excluded_relative_files: set[str],
) -> bool:
    return not is_dir and workspace_relative_path.as_posix() in excluded_relative_files


def _validate_runtime_source_registry_snapshot(
    workspace_root: Path,
    source_members: list[_ArchiveMember],
    selection: list[dict[str, str]],
    *,
    tenant_root: Path | None = None,
) -> None:
    tenant_root = (tenant_root or workspace_root).absolute()
    registry_selection = next(
        row for row in selection if row["source_path"] == "data/runtime/source_registry.json"
    )
    if registry_selection["status"] == "absent":
        return
    registry_archive_path = registry_selection["archive_path"]
    registry_member = next(
        (
            member
            for member in source_members
            if member.archive_path == registry_archive_path and member.member_type == "file"
        ),
        None,
    )
    if registry_member is None or registry_member.source_path is None:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_REGISTRY_MISSING] source registryをinventoryへ収録できません。"
        )
    try:
        registry = json.loads(
            _read_stable_regular_file(registry_member.source_path, max_bytes=4 * 1024 * 1024).decode(
                "utf-8"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_REGISTRY_INVALID] source registryを検証できません。"
        ) from exc
    if not isinstance(registry, dict) or not isinstance(registry.get("sources", []), list):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_REGISTRY_INVALID] source registryを検証できません。"
        )
    member_by_source = {
        member.source_path.absolute(): member
        for member in source_members
        if member.source_path is not None and member.member_type == "file"
    }
    for source in registry.get("sources", []):
        if not isinstance(source, dict):
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_REGISTRY_INVALID] source registryを検証できません。"
            )
        raw_path = str(source.get("path") or source.get("file_path") or "").strip()
        if not raw_path:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_REGISTRY_INVALID] source registryを検証できません。"
            )
        relative_path = Path(raw_path)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.parts[:3] != ("data", "private", "sources")
        ):
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_REGISTRY_PATH_INVALID] source registryのpath境界が不正です。"
            )
        source_member = member_by_source.get((tenant_root / relative_path).absolute())
        if source_member is None or not source_member.sha256:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_REGISTRY_FILE_MISSING] registry参照sourceを収録・hash検証できません。"
            )
        recorded_sha256 = str(
            source.get("sha256")
            or source.get("file_sha256")
            or source.get("source_sha256")
            or ""
        ).strip().lower()
        if recorded_sha256 and recorded_sha256 != source_member.sha256:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_REGISTRY_HASH_MISMATCH] registry参照sourceの記録済みSHA256が一致しません。"
            )


def _render_private_migration_manifest(
    private_members: list[_ArchiveMember],
    selection: list[dict[str, str]],
) -> bytes:
    payload = {
        "manifest_version": PRIVATE_MIGRATION_MANIFEST_VERSION,
        "purpose": "inactive_migration_snapshot",
        "active_workspace_restore_root": WORKSPACE_ARCHIVE_ROOT,
        "isolated_workspace_snapshot_root": PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix(),
        "selection": selection,
        "members": [member.manifest_row() for member in sorted(private_members, key=lambda row: row.archive_path)],
        "restore_policy": {
            "source_registry": "restore after path review",
            "env": "review machine-specific URL/path/secret values before restore",
            "data_private": "restore with owner-only permissions",
            "runtime_other": "retain for inspection; do not bulk restore transient state",
            "generated": "retain for provenance and adapter verification",
        },
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _bytes_archive_member(archive_path: str, content: bytes, category: str) -> _ArchiveMember:
    _validated_archive_path(archive_path)
    return _ArchiveMember(
        archive_path=archive_path,
        member_type="file",
        mode=0o600,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        category=category,
        content=content,
    )


def _with_archive_parent_directories(members: list[_ArchiveMember]) -> list[_ArchiveMember]:
    by_path: dict[str, _ArchiveMember] = {}
    for member in members:
        existing = by_path.get(member.archive_path)
        if existing is not None and existing.fingerprint() != member.fingerprint():
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_DUPLICATE_PATH] 複数の資産が同じarchive pathへ衝突しました。"
            )
        by_path[member.archive_path] = member
    for member in list(by_path.values()):
        path = Path(member.archive_path)
        for parent in reversed(path.parents):
            parent_path = parent.as_posix()
            if parent_path in {".", ""}:
                continue
            existing = by_path.get(parent_path)
            if existing is not None:
                if existing.member_type != "directory":
                    raise _UnsafeArchiveSourceError(
                        "[MIGRATION_BUNDLE_PATH_TYPE_COLLISION] archive pathのfile/directoryが衝突しました。"
                    )
                continue
            by_path[parent_path] = _directory_archive_member(
                parent_path,
                category="archive_directory",
            )
    return sorted(by_path.values(), key=lambda member: member.archive_path)


def _validate_archive_member_set(members: list[_ArchiveMember]) -> None:
    exact: set[str] = set()
    by_path: dict[str, _ArchiveMember] = {}
    portable: dict[str, str] = {}
    for member in members:
        path = _validated_archive_path(member.archive_path)
        if path in exact:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_DUPLICATE_PATH] archive pathが重複しています。"
            )
        exact.add(path)
        by_path[path] = member
        portable_key = unicodedata.normalize("NFC", path).casefold()
        previous = portable.get(portable_key)
        if previous is not None and previous != path:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_PORTABLE_PATH_COLLISION] Mac上で衝突するpathを含むため作成を中止しました。"
            )
        portable[portable_key] = path
    for path in exact:
        for parent in Path(path).parents:
            parent_path = parent.as_posix()
            if parent_path in {".", ""}:
                continue
            parent_member = by_path.get(parent_path)
            if parent_member is None or parent_member.member_type != "directory":
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_PARENT_PATH_INVALID] archiveの親directory inventoryが不正です。"
                )


def _validated_archive_path(raw_path: str) -> str:
    if not raw_path or raw_path.startswith("/") or "\\" in raw_path:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_PATH_INVALID] archive pathが安全ではありません。"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_path):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_PATH_INVALID] archive pathが安全ではありません。"
        )
    path = Path(raw_path)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_PATH_INVALID] archive pathが安全ではありません。"
        )
    return path.as_posix()


def _render_archive_integrity_files(
    payload_members: list[_ArchiveMember],
    *,
    root_dir: str,
    git_snapshot: dict[str, object],
) -> tuple[bytes, bytes]:
    manifest_size = 0
    checksums_size = 0
    manifest_content = b""
    checksums_content = b""
    for _attempt in range(12):
        integrity_rows = [
            {
                "path": ARCHIVE_MANIFEST_PATH.as_posix(),
                "type": "file",
                "mode": "0600",
                "size": manifest_size,
                "sha256": None,
                "category": "archive_manifest",
            },
            {
                "path": ARCHIVE_CHECKSUMS_PATH.as_posix(),
                "type": "file",
                "mode": "0600",
                "size": checksums_size,
                "sha256": None,
                "category": "archive_checksums",
            },
        ]
        root_row = {
            "path": ".",
            "type": "directory",
            "mode": "0700",
            "size": 0,
            "sha256": None,
            "category": "bundle_root",
        }
        manifest_payload = {
            "manifest_version": ARCHIVE_MANIFEST_VERSION,
            "bundle_root_dir": root_dir,
            "member_count": len(payload_members) + len(integrity_rows) + 1,
            "git_snapshot": git_snapshot,
            "members": [root_row]
            + [
                member.manifest_row()
                for member in sorted(payload_members, key=lambda row: row.archive_path)
            ]
            + integrity_rows,
            "integrity_convention": {
                "archive_manifest_sha256": "recorded in docs/checksums.txt",
                "checksums_sha256": "self-hash intentionally omitted",
                "null_sha256_rows": [
                    ARCHIVE_MANIFEST_PATH.as_posix(),
                    ARCHIVE_CHECKSUMS_PATH.as_posix(),
                ],
            },
        }
        manifest_content = (json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        checksum_rows = [
            f"{member.sha256}  {member.archive_path}"
            for member in sorted(payload_members, key=lambda row: row.archive_path)
            if member.member_type == "file"
        ]
        checksum_rows.append(
            f"{hashlib.sha256(manifest_content).hexdigest()}  {ARCHIVE_MANIFEST_PATH.as_posix()}"
        )
        checksums_content = ("\n".join(checksum_rows) + "\n").encode("utf-8")
        new_sizes = (len(manifest_content), len(checksums_content))
        if new_sizes == (manifest_size, checksums_size):
            return manifest_content, checksums_content
        manifest_size, checksums_size = new_sizes
    raise _UnsafeArchiveSourceError(
        "[MIGRATION_BUNDLE_MANIFEST_UNSTABLE] archive manifestを安定して生成できません。"
    )


def _source_inventory_fingerprint(members: list[_ArchiveMember]) -> tuple[tuple[object, ...], ...]:
    return tuple(member.fingerprint() for member in sorted(members, key=lambda row: row.archive_path))


def _write_archive_member(
    archive: tarfile.TarFile,
    root_dir: str,
    member: _ArchiveMember,
) -> None:
    arcname = f"{root_dir}/{member.archive_path}"
    _validated_archive_path(arcname)
    info = tarfile.TarInfo(name=arcname)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = member.mode
    info.mtime = 0
    if member.member_type == "directory":
        if member.source_path is not None:
            current = os.lstat(member.source_path)
            current_identity = (
                current.st_dev,
                current.st_ino,
                current.st_mtime_ns,
                current.st_ctime_ns,
            )
            expected_identity = (
                member.source_device,
                member.source_inode,
                member.source_mtime_ns,
                member.source_ctime_ns,
            )
            if not stat.S_ISDIR(current.st_mode) or current_identity != expected_identity:
                raise _UnsafeArchiveSourceError(
                    "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録directoryが作成中に変更されました。"
                )
        info.type = tarfile.DIRTYPE
        info.size = 0
        archive.addfile(info)
        return
    if member.member_type != "file":
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_MEMBER_TYPE_INVALID] archive member typeが不正です。"
        )
    info.type = tarfile.REGTYPE
    info.size = member.size
    if member.content is not None:
        if hashlib.sha256(member.content).hexdigest() != member.sha256:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_GENERATED_CONTENT_CHANGED] 生成contentのhashが一致しません。"
            )
        archive.addfile(info, BytesIO(member.content))
        return
    if member.source_path is None:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_MISSING] archive memberの収録元がありません。"
        )
    _write_source_file_to_archive(archive, info, member)


def _write_archive_root_directory(archive: tarfile.TarFile, root_dir: str) -> None:
    _validated_archive_path(root_dir)
    info = tarfile.TarInfo(name=root_dir)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o700
    info.mtime = 0
    info.type = tarfile.DIRTYPE
    info.size = 0
    archive.addfile(info)


def _write_source_file_to_archive(
    archive: tarfile.TarFile,
    info: tarfile.TarInfo,
    member: _ArchiveMember,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(member.source_path, flags)
    except OSError as exc:
        raise _UnsafeArchiveSourceError(
            "[MIGRATION_BUNDLE_SOURCE_UNREADABLE] 収録fileを安全に読み取れません。"
        ) from exc
    with os.fdopen(descriptor, "rb", closefd=True) as file_object:
        before = os.fstat(file_object.fileno())
        _validate_open_regular_file(before)
        expected_identity = (
            member.source_device,
            member.source_inode,
            member.size,
            member.source_mtime_ns,
            member.source_ctime_ns,
        )
        actual_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if actual_identity != expected_identity:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録fileが作成中に変更されました。"
            )
        hashing_reader = _HashingReader(file_object)
        archive.addfile(info, hashing_reader)
        after = os.fstat(file_object.fileno())
        _ensure_same_stat(before, after)
        if hashing_reader.hexdigest != member.sha256:
            raise _UnsafeArchiveSourceError(
                "[MIGRATION_BUNDLE_SOURCE_CHANGED] 収録fileのhashが作成中に変わりました。"
            )


def _iter_workspace_archive_files(
    workspace_root: Path,
    *,
    excluded_relative_files: set[str] | None = None,
):
    excluded_relative_files = excluded_relative_files or set()
    members = _collect_tree_archive_members(
        workspace_root,
        Path(WORKSPACE_ARCHIVE_ROOT),
        category="workspace",
        excluded=lambda path, is_dir: _is_workspace_path_excluded(path, is_dir=is_dir)
        or path.as_posix() in excluded_relative_files,
        private=False,
        git_metadata=True,
    )
    for member in members:
        if member.member_type == "file" and member.source_path is not None:
            yield member.source_path


def _workspace_runtime_database_exclusions(runtime, workspace_root: Path) -> set[str]:
    return _runtime_database_exclusions_relative_to(runtime, workspace_root)


def _runtime_database_exclusions_for_roots(
    runtime,
    workspace_root: Path,
    tenant_root: Path,
) -> tuple[set[str], set[str]]:
    return (
        _runtime_database_exclusions_relative_to(runtime, workspace_root),
        _runtime_database_exclusions_relative_to(runtime, tenant_root),
    )


def _runtime_database_exclusions_relative_to(runtime, source_root: Path) -> set[str]:
    database = runtime.settings.DATABASES["default"]
    if database.get("ENGINE") != "django.db.backends.sqlite3":
        return set()

    raw_name = database.get("NAME")
    if not raw_name or str(raw_name) == ":memory:":
        return set()

    source_root_resolved = source_root.resolve()
    database_path = Path(str(raw_name)).expanduser().resolve()
    exclusions: set[str] = set()
    for candidate in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        Path(f"{database_path}-journal"),
    ):
        try:
            relative_path = candidate.relative_to(source_root_resolved)
        except ValueError:
            continue
        exclusions.add(relative_path.as_posix())
    return exclusions


def _private_postal_scan_archive_files_exist(
    workspace_root: Path,
    *,
    tenant_root: Path | None = None,
) -> bool:
    source_root = tenant_root or workspace_root
    return os.path.lexists(source_root / POSTAL_SCAN_PRIVATE_SOURCE)


def _private_migration_payload_sources_exist(
    workspace_root: Path,
    *,
    tenant_root: Path | None = None,
) -> bool:
    tenant_root = tenant_root or workspace_root
    return os.path.lexists(workspace_root / ".env") or any(
        os.path.lexists(tenant_root / relative_path)
        for relative_path in (
            TENANT_POLICY_SOURCE,
            TENANT_PREFERENCES_SOURCE,
            "data/private",
            "data/runtime",
            "data/generated",
        )
    )


def _iter_private_postal_scan_archive_files(
    workspace_root: Path,
    *,
    tenant_root: Path | None = None,
):
    source_root = (tenant_root or workspace_root) / POSTAL_SCAN_PRIVATE_SOURCE
    if not os.path.lexists(source_root):
        return
    members = _collect_tree_archive_members(
        source_root,
        POSTAL_SCAN_BUNDLE_ROOT,
        category="postal_scans",
        private=True,
    )
    for member in members:
        if member.member_type == "file" and member.source_path is not None:
            yield member.source_path, Path(member.archive_path)


def _is_workspace_path_excluded(relative_path: Path, *, is_dir: bool) -> bool:
    relative_str = relative_path.as_posix()
    if relative_str.startswith("./"):
        relative_str = relative_str[2:]
    if relative_str in EXCLUDED_TOP_LEVEL_PATHS:
        return True
    if any(relative_str.startswith(f"{prefix}/") for prefix in EXCLUDED_TOP_LEVEL_PATHS):
        return True
    path_parts = relative_path.parts
    if not path_parts:
        return False
    if path_parts[0] == ".git":
        return False
    if is_dir and path_parts[-1] in EXCLUDED_DIR_NAMES:
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in path_parts[:-1]):
        return True
    if not is_dir and path_parts[-1] == ".DS_Store":
        return True
    if not is_dir and relative_str == ".env":
        return True
    return False
