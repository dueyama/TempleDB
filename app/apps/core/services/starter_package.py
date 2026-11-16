from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from django.conf import settings

from config.platform_file_lock import (
    PlatformFileLockBusyError,
    lock_exclusive,
    unlock,
)
from config.runtime_paths import runtime_root


class StarterPackageError(RuntimeError):
    """Base error safe for the web layer to classify without exposing subprocess output."""


class StarterPackageUnavailableError(StarterPackageError):
    """The private starter-package factory is not available in this runtime."""


class StarterPackageBuildInProgressError(StarterPackageError):
    """Another starter-package build currently owns the process lock."""


class StarterPackageBuildError(StarterPackageError):
    """The fixed starter-package builder failed or produced an invalid artifact."""


BUILDER_PATH = Path(settings.BASE_DIR) / "demo" / "bin" / "build_demo_workspace.sh"
BUILDER_PYTHON_PATH = Path(settings.BASE_DIR) / ".venv" / "bin" / "python"
REPOSITORY_METADATA_PATH = Path(settings.BASE_DIR) / ".git"
BUILD_LOCK_PATH = runtime_root() / "starter_package_build.lock"
BUILD_TIMEOUT_SECONDS = 15 * 60
BUILD_TERMINATION_GRACE_SECONDS = 5
_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def starter_package_available() -> bool:
    """Return whether this checkout owns the private factory used to build a starter."""

    if os.name == "nt" or getattr(settings, "TEMPLEDB_DEMO_MODE", False):
        return False
    return (
        REPOSITORY_METADATA_PATH.exists()
        and shutil.which("git", path=_SAFE_PATH) is not None
        and shutil.which("rsync", path=_SAFE_PATH) is not None
        and _is_executable_regular_file(BUILDER_PATH)
        and _is_executable_file(BUILDER_PYTHON_PATH)
    )


def create_starter_package() -> tuple[BinaryIO, str]:
    """Build the starter with the reviewed demo factory and return an anonymous copy."""

    if not starter_package_available():
        raise StarterPackageUnavailableError("スターターパッケージ作成機能を利用できません。")

    package_file: BinaryIO | None = None
    try:
        with _starter_build_lock():
            with tempfile.TemporaryDirectory(prefix="templedb-starter-package-") as raw_temp_dir:
                private_root = Path(raw_temp_dir)
                private_root.chmod(0o700)
                build_root = private_root / "build"
                build_root.mkdir(mode=0o700)
                archive_path = private_root / _archive_filename()
                env = _build_environment(
                    private_root=private_root,
                    build_root=build_root,
                    archive_path=archive_path,
                )
                _run_builder(env=env)
                _validate_archive_output(archive_path)
                package_file = tempfile.TemporaryFile(mode="w+b", dir=private_root)
                with archive_path.open("rb") as source:
                    shutil.copyfileobj(source, package_file)
                package_file.seek(0)
        return package_file, archive_path.name
    except StarterPackageError:
        if package_file is not None:
            package_file.close()
        raise
    except OSError as exc:
        if package_file is not None:
            package_file.close()
        raise StarterPackageBuildError(
            "スターターパッケージの安全な作業領域を処理できませんでした。"
        ) from exc


def _archive_filename() -> str:
    return f"templedb-demo-workspace-{datetime.now().strftime('%Y%m%d')}.tar.gz"


def _build_environment(
    *,
    private_root: Path,
    build_root: Path,
    archive_path: Path,
) -> dict[str, str]:
    return {
        "PATH": _SAFE_PATH,
        "HOME": str(private_root),
        "TMPDIR": str(private_root),
        "LANG": "C",
        "LC_ALL": "C",
        "DEMO_BUILD_PYTHON": str(BUILDER_PYTHON_PATH),
        "PYTHON_BIN": str(BUILDER_PYTHON_PATH),
        "TEMPLEDB_DEMO_ARCHIVE_PATH": str(archive_path),
        "TEMPLEDB_DEMO_BUILD_TMPDIR": str(build_root),
    }


def _run_builder(*, env: dict[str, str]) -> None:
    try:
        process = subprocess.Popen(
            [str(BUILDER_PATH)],
            cwd=settings.BASE_DIR,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise StarterPackageBuildError(
            "スターターパッケージの作成処理を開始できませんでした。"
        ) from exc
    try:
        process.communicate(timeout=BUILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_builder_process_group(process)
        raise StarterPackageBuildError(
            "スターターパッケージの作成が制限時間を超えました。"
        ) from exc
    except OSError:
        _terminate_builder_process_group(process)
        raise
    if process.returncode != 0:
        raise StarterPackageBuildError("スターターパッケージを作成できませんでした。")


def _terminate_builder_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=BUILD_TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


def _validate_archive_output(archive_path: Path) -> None:
    try:
        metadata = archive_path.lstat()
    except OSError as exc:
        raise StarterPackageBuildError(
            "スターターパッケージの出力を確認できませんでした。"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or archive_path.is_symlink() or metadata.st_size <= 0:
        raise StarterPackageBuildError("スターターパッケージの出力が不正です。")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        archive_path.chmod(0o600)


def _is_executable_regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and os.access(path, os.X_OK)
    )


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


@contextmanager
def _starter_build_lock() -> Iterator[None]:
    BUILD_LOCK_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(BUILD_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        try:
            lock_exclusive(lock_fd, blocking=False)
        except PlatformFileLockBusyError as exc:
            raise StarterPackageBuildInProgressError(
                "別のスターターパッケージ作成処理が実行中です。"
            ) from exc
        try:
            yield
        finally:
            unlock(lock_fd)
    finally:
        os.close(lock_fd)


__all__ = [
    "StarterPackageBuildError",
    "StarterPackageBuildInProgressError",
    "StarterPackageError",
    "StarterPackageUnavailableError",
    "create_starter_package",
    "starter_package_available",
]
