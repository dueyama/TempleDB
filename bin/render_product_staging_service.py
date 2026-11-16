#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

TOKEN_PATTERN = re.compile(r"@[A-Z0-9_]+@")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
DATABASE_PATTERN = re.compile(r"templedb_clone_[a-z0-9_]+")
IDENTIFIER_PATTERN = re.compile(r"[a-z_][a-z0-9_-]*")
UNIT_PATTERN = re.compile(r"[A-Za-z0-9_.@-]+\.service")
SAFE_PATH_PATTERN = re.compile(r"/[A-Za-z0-9_./-]+")


class RenderError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render fail-closed TempleDB product staging service files.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--tenant-root", type=Path, required=True)
    parser.add_argument("--run-user", required=True)
    parser.add_argument("--run-group", required=True)
    parser.add_argument("--proxy-user", required=True)
    parser.add_argument("--proxy-group", required=True)
    parser.add_argument("--machine-env", type=Path, required=True)
    parser.add_argument("--safety-env", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--proxy-root", type=Path, required=True)
    parser.add_argument("--proxy-state-root", type=Path, required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--database-user", required=True)
    parser.add_argument("--postgresql-unit", required=True)
    parser.add_argument("--database-port", type=int, required=True)
    parser.add_argument("--gunicorn-port", type=int, required=True)
    parser.add_argument("--proxy-port", type=int, required=True)
    parser.add_argument("--allow-openai", choices=("0", "1"), default="0")
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-runtime-git-commit")
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-installation-id", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    workspace = _absolute_clean_path(arguments.workspace_root, "workspace root")
    tenant_root = _absolute_clean_path(arguments.tenant_root, "tenant root")
    output_root = _absolute_clean_path(arguments.output_root, "output root")
    if output_root.exists() or output_root.is_symlink():
        raise RenderError("output rootは未作成pathを指定してください。")
    parent = output_root.parent.resolve(strict=True)
    metadata = parent.stat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RenderError("output rootの親は現在user所有0700にしてください。")

    commit = arguments.expected_git_commit.strip().lower()
    runtime_commit = (
        arguments.expected_runtime_git_commit or commit
    ).strip().lower()
    archive_sha256 = arguments.expected_archive_sha256.strip().lower()
    if not GIT_COMMIT_PATTERN.fullmatch(commit):
        raise RenderError("Git commitは完全hashで指定してください。")
    if not GIT_COMMIT_PATTERN.fullmatch(runtime_commit):
        raise RenderError("runtime Git commitは完全hashで指定してください。")
    if not SHA256_PATTERN.fullmatch(archive_sha256):
        raise RenderError("運用pack SHA256が不正です。")
    try:
        installation_id = str(uuid.UUID(arguments.expected_installation_id.strip()))
    except (ValueError, AttributeError) as exc:
        raise RenderError("installation IDが不正です。") from exc
    if not DATABASE_PATTERN.fullmatch(arguments.database_name):
        raise RenderError("candidate DB名はtempledb_clone_*で指定してください。")
    if (
        not UNIT_PATTERN.fullmatch(arguments.postgresql_unit)
        or "demo" in arguments.postgresql_unit.casefold()
    ):
        raise RenderError("PostgreSQL systemd unit名が不正です。")
    for label, value in (
        ("run user", arguments.run_user),
        ("run group", arguments.run_group),
        ("proxy user", arguments.proxy_user),
        ("proxy group", arguments.proxy_group),
        ("database user", arguments.database_user),
    ):
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise RenderError(f"{label}が不正です。")
    ports = {
        arguments.database_port,
        arguments.gunicorn_port,
        arguments.proxy_port,
    }
    if (
        len(ports) != 3
        or any(port < 1 or port > 65535 for port in ports)
        or ports.intersection({8011, 8012})
    ):
        raise RenderError("DB、Gunicorn、proxy portは異なる有効値にしてください。")

    absolute_paths = {
        "@WORKSPACE_ROOT@": workspace,
        "@TENANT_ROOT@": tenant_root,
        "@PRODUCT_STAGING_MACHINE_ENV@": _absolute_clean_path(
            arguments.machine_env,
            "machine env",
        ),
        "@PRODUCT_STAGING_SAFETY_ENV@": _absolute_clean_path(
            arguments.safety_env,
            "safety env",
        ),
        "@PRODUCT_STAGING_BACKUP_ROOT@": _absolute_clean_path(
            arguments.backup_root,
            "backup root",
        ),
        "@PRODUCT_STAGING_PROXY_ROOT@": _absolute_clean_path(
            arguments.proxy_root,
            "proxy root",
        ),
        "@PRODUCT_STAGING_PROXY_STATE_ROOT@": _absolute_clean_path(
            arguments.proxy_state_root,
            "proxy state root",
        ),
    }
    runtime_python = _absolute_clean_path(
        arguments.runtime_python or workspace / ".venv/bin/python",
        "runtime Python",
    )
    _assert_disjoint_runtime_paths(
        workspace=workspace,
        tenant_root=tenant_root,
        backup_root=absolute_paths["@PRODUCT_STAGING_BACKUP_ROOT@"],
        proxy_root=absolute_paths["@PRODUCT_STAGING_PROXY_ROOT@"],
        proxy_state_root=absolute_paths["@PRODUCT_STAGING_PROXY_STATE_ROOT@"],
        machine_env=absolute_paths["@PRODUCT_STAGING_MACHINE_ENV@"],
        safety_env=absolute_paths["@PRODUCT_STAGING_SAFETY_ENV@"],
        runtime_python=runtime_python,
    )
    runtime_python_verifier = " ".join(
        (
            "/usr/bin/python3",
            "-I",
            str(workspace / "bin/verify_product_staging_runtime_python.py"),
            "--runtime-python",
            str(runtime_python),
            "--workspace-root",
            str(workspace),
            "--tenant-root",
            str(tenant_root),
            "--backup-root",
            str(absolute_paths["@PRODUCT_STAGING_BACKUP_ROOT@"]),
            "--proxy-root",
            str(absolute_paths["@PRODUCT_STAGING_PROXY_ROOT@"]),
            "--proxy-state-root",
            str(absolute_paths["@PRODUCT_STAGING_PROXY_STATE_ROOT@"]),
            "--machine-env",
            str(absolute_paths["@PRODUCT_STAGING_MACHINE_ENV@"]),
            "--safety-env",
            str(absolute_paths["@PRODUCT_STAGING_SAFETY_ENV@"]),
        )
    )
    verifier = " ".join(
        (
            str(runtime_python),
            str(workspace / "app/manage.py"),
            "verify_tenant_operations_candidate",
            "--candidate-tenant-root",
            str(tenant_root),
            "--expected-git-commit",
            commit,
            "--expected-runtime-git-commit",
            runtime_commit,
            "--expected-archive-sha256",
            archive_sha256,
            "--expected-installation-id",
            installation_id,
            "--expected-database-name",
            arguments.database_name,
        )
    )
    replacements = {
        **{token: str(path) for token, path in absolute_paths.items()},
        "@RUN_USER@": arguments.run_user,
        "@RUN_GROUP@": arguments.run_group,
        "@PROXY_USER@": arguments.proxy_user,
        "@PROXY_GROUP@": arguments.proxy_group,
        "@PRODUCT_STAGING_DATABASE_NAME@": arguments.database_name,
        "@PRODUCT_STAGING_DATABASE_USER@": arguments.database_user,
        "@PRODUCT_STAGING_POSTGRESQL_UNIT@": arguments.postgresql_unit,
        "@PRODUCT_STAGING_DATABASE_PORT@": str(arguments.database_port),
        "@PRODUCT_STAGING_GUNICORN_PORT@": str(arguments.gunicorn_port),
        "@PRODUCT_STAGING_PROXY_PORT@": str(arguments.proxy_port),
        "@PRODUCT_STAGING_ALLOW_OPENAI@": arguments.allow_openai,
        "@PRODUCT_STAGING_RUNTIME_PYTHON@": str(runtime_python),
        "@PRODUCT_STAGING_RUNTIME_PYTHON_VERIFIER@": runtime_python_verifier,
        "@ACTIVATED_CANDIDATE_VERIFIER@": verifier,
    }

    template_root = Path(__file__).resolve().parents[1]
    sources = {
        "templedb-product-staging.service": (
            template_root / "systemd/templedb-product-staging.service.in"
        ),
        "templedb-product-staging-proxy.service": (
            template_root / "systemd/templedb-product-staging-proxy.service.in"
        ),
        "env.product-staging-safety": (
            template_root / "systemd/env.product-staging-safety.in"
        ),
        "Caddyfile": template_root / "Caddyfile.product-staging",
    }
    staging_root = parent / f".product-staging-render-{uuid.uuid4().hex}"
    os.mkdir(staging_root, 0o700)
    try:
        rendered_hashes: dict[str, str] = {}
        for name, source in sources.items():
            content = source.read_text(encoding="utf-8")
            for token, value in replacements.items():
                content = content.replace(token, value)
            remaining = sorted(set(TOKEN_PATTERN.findall(content)))
            if remaining:
                raise RenderError(
                    "未置換tokenがあります: " + ", ".join(remaining)
                )
            encoded = content.encode("utf-8")
            _write_exclusive(staging_root / name, encoded)
            rendered_hashes[name] = hashlib.sha256(encoded).hexdigest()
        manifest = {
            "format": "templedb-product-staging-service-render",
            "version": 1,
            "workspace_root": str(workspace),
            "tenant_root": str(tenant_root),
            "database_name": arguments.database_name,
            "platform_commit": commit,
            "source_platform_commit": commit,
            "runtime_platform_commit": runtime_commit,
            "runtime_python": str(runtime_python),
            "archive_sha256": archive_sha256,
            "installation_id": installation_id,
            "allow_openai": arguments.allow_openai == "1",
            "files": rendered_hashes,
        }
        _write_exclusive(
            staging_root / "render-manifest.json",
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        _fsync_directory(staging_root)
        os.rename(staging_root, output_root)
        _fsync_directory(parent)
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    print(f"product staging service設定を生成しました: {output_root}")
    return 0


def _absolute_clean_path(raw_path: Path, label: str) -> Path:
    value = str(raw_path.expanduser())
    if not os.path.isabs(value) or not SAFE_PATH_PATTERN.fullmatch(value):
        raise RenderError(
            f"{label}はASCII英数字、underscore、dot、hyphen、slashだけの"
            "絶対pathで指定してください。"
        )
    if ".." in Path(value).parts:
        raise RenderError(f"{label}に使用できない文字があります。")
    return Path(os.path.abspath(value))


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise RenderError("service設定を完全に書き込めませんでした。")
            offset += written
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_disjoint_runtime_paths(
    *,
    workspace: Path,
    tenant_root: Path,
    backup_root: Path,
    proxy_root: Path,
    proxy_state_root: Path,
    machine_env: Path,
    safety_env: Path,
    runtime_python: Path,
) -> None:
    roots = {
        "workspace": workspace,
        "tenant root": tenant_root,
        "backup root": backup_root,
        "proxy root": proxy_root,
        "proxy state root": proxy_state_root,
    }
    root_items = list(roots.items())
    for index, (left_label, left_path) in enumerate(root_items):
        for right_label, right_path in root_items[index + 1 :]:
            if _paths_overlap(left_path, right_path):
                raise RenderError(
                    f"{left_label}と{right_label}を同一または親子pathにはできません。"
                )
    if machine_env == safety_env:
        raise RenderError("machine envとsafety envは別fileにしてください。")
    for env_label, env_path in (
        ("machine env", machine_env),
        ("safety env", safety_env),
    ):
        for root_label, root_path in roots.items():
            if _paths_overlap(env_path, root_path):
                raise RenderError(
                    f"{env_label}を{root_label}と同一または親子pathにはできません。"
                )
    protected_runtime_paths = {
        "tenant root": tenant_root,
        "backup root": backup_root,
        "proxy root": proxy_root,
        "proxy state root": proxy_state_root,
        "machine env": machine_env,
        "safety env": safety_env,
    }
    for label, protected_path in protected_runtime_paths.items():
        if _paths_overlap(runtime_python, protected_path):
            raise RenderError(
                f"runtime Pythonを{label}と同一または親子pathにはできません。"
            )


def _paths_overlap(left: Path, right: Path) -> bool:
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RenderError as exc:
        raise SystemExit(str(exc)) from exc
