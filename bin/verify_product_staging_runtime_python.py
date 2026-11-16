#!/usr/bin/python3 -I
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path


class RuntimePythonVerificationError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the product staging Python is outside writable runtime "
            "roots and remains rooted in an immutable root-owned path."
        )
    )
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--tenant-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--proxy-root", type=Path, required=True)
    parser.add_argument("--proxy-state-root", type=Path, required=True)
    parser.add_argument("--machine-env", type=Path, required=True)
    parser.add_argument("--safety-env", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    workspace_root = _absolute_path(arguments.workspace_root, "workspace root")
    script_path = workspace_root / "bin/verify_product_staging_runtime_python.py"
    if Path(__file__).resolve(strict=True) != script_path:
        raise RuntimePythonVerificationError(
            "runtime Python verifierは指定workspace内の固定pathから実行してください。"
        )
    _validated_root_regular_file(script_path)
    verify_runtime_python(
        runtime_python=arguments.runtime_python,
        protected_paths=(
            arguments.tenant_root,
            arguments.backup_root,
            arguments.proxy_root,
            arguments.proxy_state_root,
            arguments.machine_env,
            arguments.safety_env,
        ),
    )
    return 0


def verify_runtime_python(
    *,
    runtime_python: Path,
    protected_paths: tuple[Path, ...],
    expected_owner_uid: int = 0,
    parent_chain_stop: Path | None = None,
) -> Path:
    path = _absolute_path(runtime_python, "runtime Python")
    protected = tuple(
        _absolute_path(candidate, "protected runtime path")
        for candidate in protected_paths
    )
    _assert_path_disjoint(path, protected)
    _assert_owned_parent_chain(
        path.parent,
        expected_owner_uid=expected_owner_uid,
        stop_at=parent_chain_stop,
    )
    try:
        link_metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimePythonVerificationError(
            "runtime Pythonを確認できません。"
        ) from exc
    if stat.S_ISLNK(link_metadata.st_mode):
        if link_metadata.st_uid != expected_owner_uid:
            raise RuntimePythonVerificationError(
                "runtime Python symlinkのownerが不正です。"
            )
    elif not stat.S_ISREG(link_metadata.st_mode):
        raise RuntimePythonVerificationError(
            "runtime Pythonは通常fileまたは安全なsymlinkにしてください。"
        )
    _assert_path_disjoint(resolved, protected)
    _assert_owned_parent_chain(
        resolved.parent,
        expected_owner_uid=expected_owner_uid,
        stop_at=parent_chain_stop,
    )
    metadata = resolved.stat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != expected_owner_uid
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise RuntimePythonVerificationError(
            "runtime Python実体はroot所有・単一link・共有書込不可・実行可能にしてください。"
        )
    return path


def _validated_root_regular_file(path: Path) -> Path:
    _assert_owned_parent_chain(path.parent, expected_owner_uid=0)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimePythonVerificationError(
            "runtime Python verifier自身を確認できません。"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimePythonVerificationError(
            "runtime Python verifierはroot所有・単一link・共有書込不可にしてください。"
        )
    return path


def _assert_owned_parent_chain(
    start: Path,
    *,
    expected_owner_uid: int,
    stop_at: Path | None = None,
) -> None:
    stop = _absolute_path(stop_at, "parent chain stop") if stop_at else None
    current = _absolute_path(start, "runtime Python parent")
    if stop is not None and current != stop and not current.is_relative_to(stop):
        raise RuntimePythonVerificationError(
            "test用parent chain stopがruntime Pythonの親ではありません。"
        )
    while True:
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise RuntimePythonVerificationError(
                "runtime Pythonの親directoryを確認できません。"
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != expected_owner_uid
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or resolved != current
        ):
            raise RuntimePythonVerificationError(
                f"runtime Pythonの親directoryが安全ではありません: {current}"
            )
        if current == (stop or current.parent):
            return
        current = current.parent


def _assert_path_disjoint(path: Path, protected_paths: tuple[Path, ...]) -> None:
    for protected in protected_paths:
        if _paths_overlap(path, protected):
            raise RuntimePythonVerificationError(
                "runtime Pythonをtenant / backup / proxy / env pathと"
                "同一または親子pathにはできません。"
            )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _absolute_path(raw_path: Path, label: str) -> Path:
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute() or ".." in expanded.parts:
        raise RuntimePythonVerificationError(f"{label}はcleanな絶対pathにしてください。")
    return Path(os.path.abspath(expanded))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimePythonVerificationError as exc:
        raise SystemExit(str(exc)) from exc
