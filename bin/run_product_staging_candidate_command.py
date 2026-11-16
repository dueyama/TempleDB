#!/usr/bin/python3 -I
from __future__ import annotations

import argparse
import hashlib
import os
import pwd
import re
import stat
from pathlib import Path

ENV_KEY_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
DATABASE_PATTERN = re.compile(r"templedb_clone_[a-z0-9_]+")
MAX_ENV_FILE_SIZE = 128 * 1024
INSTALLED_HELPER_PATH = Path(
    "/usr/local/libexec/templedb-product-staging-candidate-command.py"
)
TRUSTED_EXTERNAL_SYMLINK_ROOTS = tuple(
    Path(path) for path in ("/usr", "/lib", "/lib64")
)
TRANSFER_PREFIX = "TEMPLEDB_TRANSFER_TARGET_"
TRANSFER_KEYS = frozenset(
    {
        f"{TRANSFER_PREFIX}HOST",
        f"{TRANSFER_PREFIX}PORT",
        f"{TRANSFER_PREFIX}ADMIN_DATABASE",
        f"{TRANSFER_PREFIX}ADMIN_USER",
        f"{TRANSFER_PREFIX}ADMIN_PASSWORD",
        f"{TRANSFER_PREFIX}OWNER_USER",
        f"{TRANSFER_PREFIX}OWNER_PASSWORD",
    }
)
REQUIRED_TRANSFER_KEYS = frozenset(
    {
        f"{TRANSFER_PREFIX}HOST",
        f"{TRANSFER_PREFIX}PORT",
        f"{TRANSFER_PREFIX}ADMIN_DATABASE",
        f"{TRANSFER_PREFIX}ADMIN_USER",
        f"{TRANSFER_PREFIX}OWNER_USER",
    }
)
SAFETY_EXPECTED = {
    "DJANGO_DEBUG": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "TEMPLEDB_DEMO_MODE": "0",
    "TEMPLEDB_ALLOW_POSTGRESQL_DEMO": "0",
    "TEMPLEDB_DATABASE_ENGINE": "postgresql",
    "TEMPLEDB_SQLITE_DB_PATH": "",
    "TEMPLEDB_RUNTIME_ROLE": "staging",
    "TEMPLEDB_TAILSCALE_SERVE": "0",
    "TEMPLEDB_TRUSTED_PROXY_HTTPS": "1",
    "TEMPLEDB_LEGACY_REIMPORT_ENABLED": "0",
    "TEMPLEDB_EXTERNAL_BASE_URL": "",
    "TEMPLEDB_GOOGLE_SERVICE_ACCOUNT_FILE": "",
}
SAFETY_REQUIRED_KEYS = frozenset(
    {
        *SAFETY_EXPECTED,
        "TEMPLEDB_TENANT_ROOT",
        "TEMPLEDB_STAGING_ALLOW_OPENAI",
        "DATABASE_HOST",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PORT",
    }
)
SAFETY_ALLOWED_KEYS = frozenset(
    {
        *SAFETY_REQUIRED_KEYS,
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "TEMPLEDB_SQLITE_DB_PATH",
        "MPLCONFIGDIR",
        "XDG_CACHE_HOME",
        "TEMPLEDB_GUNICORN_UPSTREAM",
        "TEMPLEDB_TRUSTED_PROXY_HTTPS",
        "TEMPLEDB_BACKUP_DESTINATION_PATH",
        "TEMPLEDB_EXTERNAL_BASE_URL",
    }
)
SAFETY_REQUIRED_KEYS = SAFETY_ALLOWED_KEYS
MACHINE_REQUIRED_KEYS = frozenset(
    {
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "TEMPLEDB_BASE_URL",
        "DATABASE_PASSWORD",
    }
)
MACHINE_ALLOWED_KEYS = frozenset(
    {
        *MACHINE_REQUIRED_KEYS,
        "TEMPLEDB_BROWSER_HOST",
        "OPENAI_API_KEY",
        "OPENAI_RESPONSES_URL",
        "TEMPLEDB_OPENAI_QUERY_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_RERANK_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_TAG_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_TIMEOUT_SECONDS",
        "TEMPLEDB_POSTAL_SCAN_OCR_MODEL",
        "TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_MODEL",
        "TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE",
        "TEMPLEDB_POSTAL_SCAN_OCR_TIMEOUT_SECONDS",
        "TEMPLEDB_MEMO_AI_MODELS",
        "TEMPLEDB_MAX_AI_RERANK_CANDIDATES",
        "TEMPLEDB_MAX_AUTO_TAG_AI_CALLS_PER_RUN",
        "TEMPLEDB_MAX_AUTO_TAG_NOTES_PER_RUN",
        "TEMPLEDB_MAX_DYNAMIC_MEMO_TAGS",
        "TEMPLEDB_MAX_RENDERED_SEARCH_RESULTS",
        "TEMPLEDB_PDF_CHROME_BIN",
    }
)


class CandidateCommandError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one TempleDB product staging candidate control command with "
            "a fixed root-only validator that drops to the dedicated app UID "
            "before executing workspace code."
        )
    )
    parser.add_argument("action", choices=("activate", "verify", "deactivate"))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--candidate-tenant-root", type=Path, required=True)
    parser.add_argument("--run-user", required=True)
    parser.add_argument("--machine-env", type=Path, required=True)
    parser.add_argument("--safety-env", type=Path, required=True)
    parser.add_argument("--operator-env", type=Path)
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-runtime-git-commit")
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-installation-id", required=True)
    parser.add_argument("--expected-database-name", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if os.geteuid() != 0:
        raise CandidateCommandError("このcommandはsudo/rootから実行してください。")
    _assert_installed_helper()
    if arguments.action in {"activate", "deactivate"}:
        if arguments.operator_env is None:
            raise CandidateCommandError(
                "activation/deactivationには--operator-envが必要です。"
            )
    elif arguments.operator_env is not None:
        raise CandidateCommandError("verifyではoperator envを読み込みません。")

    workspace_root = _validated_workspace(arguments.workspace_root)
    _assert_installed_helper_matches_workspace(workspace_root)
    account = _validated_run_account(arguments.run_user)
    candidate_root = _validated_candidate_root(
        arguments.candidate_tenant_root,
        expected_uid=account.pw_uid,
    )
    _validated_candidate_env_sentinel(
        candidate_root / ".env",
        expected_uid=account.pw_uid,
    )
    commit = _validated_pattern(
        arguments.expected_git_commit,
        GIT_COMMIT_PATTERN,
        "Git commit",
    )
    runtime_commit = _validated_pattern(
        arguments.expected_runtime_git_commit or commit,
        GIT_COMMIT_PATTERN,
        "runtime Git commit",
    )
    if arguments.action == "activate" and runtime_commit != commit:
        raise CandidateCommandError(
            "初回activationではpack commitとruntime commitを一致させてください。"
        )
    archive_sha256 = _validated_pattern(
        arguments.expected_archive_sha256,
        SHA256_PATTERN,
        "運用pack SHA256",
    )
    database_name = _validated_pattern(
        arguments.expected_database_name,
        DATABASE_PATTERN,
        "candidate DB名",
    )

    machine_values = _read_root_env(arguments.machine_env)
    _assert_machine_keys_safe(machine_values)
    safety_values = _read_root_env(arguments.safety_env)
    _assert_safety_environment(
        safety_values,
        candidate_root=candidate_root,
        database_name=database_name,
        machine_values=machine_values,
    )
    _validated_staging_backup_root(
        Path(safety_values["TEMPLEDB_BACKUP_DESTINATION_PATH"]),
        candidate_root=candidate_root,
        expected_uid=account.pw_uid,
    )
    operator_values: dict[str, str] = {}
    if arguments.action in {"activate", "deactivate"}:
        assert arguments.operator_env is not None
        operator_values = _read_root_env(arguments.operator_env)
        _assert_operator_environment(
            operator_values,
            safety_values=safety_values,
            machine_values=machine_values,
        )

    python_path = _validated_root_executable(
        arguments.runtime_python or workspace_root / ".venv/bin/python"
    )
    manage_path = _validated_root_file(workspace_root / "app/manage.py")
    command_name = {
        "activate": "activate_tenant_operations_candidate",
        "verify": "verify_tenant_operations_candidate",
        "deactivate": "deactivate_tenant_operations_candidate",
    }[arguments.action]
    command = [
        str(python_path),
        str(manage_path),
        command_name,
        "--candidate-tenant-root",
        str(candidate_root),
        "--expected-git-commit",
        commit,
        "--expected-archive-sha256",
        archive_sha256,
        "--expected-installation-id",
        arguments.expected_installation_id.strip(),
        "--expected-database-name",
        database_name,
        "--candidate-owner-uid",
        str(account.pw_uid),
    ]
    if runtime_commit != commit:
        command.extend(
            (
                "--expected-runtime-git-commit",
                runtime_commit,
            )
        )
    if arguments.action in {"activate", "deactivate"}:
        command.extend(
            (
                "--confirm-candidate-tenant-root",
                str(candidate_root),
                "--confirm-database-name",
                database_name,
            )
        )

    environment = {
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "HOME": account.pw_dir,
        "LANG": "C.UTF-8",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    }
    environment.update(machine_values)
    environment.update(safety_values)
    environment.update(operator_values)
    os.chdir(workspace_root / "app")
    os.umask(0o077)
    try:
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    except OSError as exc:
        raise CandidateCommandError(
            "candidate commandを専用app userへ権限縮小できません。"
        ) from exc
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise CandidateCommandError(
            "candidate commandの権限縮小を確認できません。"
        )
    os.execve(str(python_path), command, environment)
    raise AssertionError("os.execve returned unexpectedly")


def _assert_installed_helper() -> None:
    path = Path(__file__)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CandidateCommandError("root helper自身を確認できません。") from exc
    if (
        resolved != INSTALLED_HELPER_PATH
        or path != INSTALLED_HELPER_PATH
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o755
    ):
        raise CandidateCommandError(
            "root helperは固定pathへroot所有0755の通常fileとしてinstallしてください。"
        )
    current = path.parent
    while True:
        parent_metadata = current.lstat()
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or stat.S_ISLNK(parent_metadata.st_mode)
            or parent_metadata.st_uid != 0
            or stat.S_IMODE(parent_metadata.st_mode) & 0o022
            or current.resolve(strict=True) != current
        ):
            raise CandidateCommandError("root helperの親directoryが安全ではありません。")
        if current == current.parent:
            break
        current = current.parent


def _assert_installed_helper_matches_workspace(workspace_root: Path) -> None:
    source_path = _validated_root_file(
        workspace_root / "bin/run_product_staging_candidate_command.py"
    )
    try:
        installed_digest = hashlib.sha256(
            INSTALLED_HELPER_PATH.read_bytes()
        ).digest()
        source_digest = hashlib.sha256(source_path.read_bytes()).digest()
    except OSError as exc:
        raise CandidateCommandError(
            "root helperとworkspace原本を照合できません。"
        ) from exc
    if installed_digest != source_digest:
        raise CandidateCommandError(
            "root helperが現在workspaceの配布原本と一致しません。再installしてください。"
        )


def _validated_workspace(raw_path: Path) -> Path:
    path = _absolute_path(raw_path, "workspace root")
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or path.resolve(strict=True) != path
    ):
        raise CandidateCommandError(
            "workspace rootはroot所有でgroup/other書込不可の実directoryにしてください。"
        )
    _assert_root_owned_parent_chain(path.parent)
    _assert_workspace_tree_safe(path)
    return path


def _assert_root_owned_parent_chain(start: Path) -> None:
    current = start
    while True:
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise CandidateCommandError(
                "workspace親directoryを確認できません。"
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or resolved != current
        ):
            raise CandidateCommandError(
                f"workspace親directoryがroot所有の固定pathではありません: {current}"
            )
        if current == current.parent:
            return
        current = current.parent


def _assert_workspace_tree_safe(workspace_root: Path) -> None:
    stack = [workspace_root]
    while stack:
        directory = stack.pop()
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            raise CandidateCommandError("workspace treeを列挙できません。") from exc
        with entries:
            for entry in entries:
                path = Path(entry.path)
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise CandidateCommandError(
                        "workspace metadataを確認できません。"
                    ) from exc
                if metadata.st_uid != 0:
                    raise CandidateCommandError(
                        f"workspace pathがroot所有ではありません: {path}"
                    )
                if stat.S_ISLNK(metadata.st_mode):
                    _assert_workspace_symlink_safe(
                        path,
                        workspace_root=workspace_root,
                    )
                elif stat.S_ISDIR(metadata.st_mode):
                    if stat.S_IMODE(metadata.st_mode) & 0o022:
                        raise CandidateCommandError(
                            f"workspace directoryが共有書込可能です: {path}"
                        )
                    stack.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) & 0o022:
                        raise CandidateCommandError(
                            f"workspace fileのlink数またはmodeが不正です: {path}"
                        )
                else:
                    raise CandidateCommandError(
                        f"workspaceに特殊fileがあります: {path}"
                    )


def _assert_workspace_symlink_safe(path: Path, *, workspace_root: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise CandidateCommandError("workspace symlinkを解決できません。") from exc
    trusted_target = resolved.is_relative_to(workspace_root) or any(
        resolved.is_relative_to(root) for root in TRUSTED_EXTERNAL_SYMLINK_ROOTS
    )
    if (
        not trusted_target
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
    ):
        raise CandidateCommandError(
            f"workspace symlinkの参照先が安全ではありません: {path}"
        )
    _assert_root_owned_parent_chain(resolved.parent)


def _validated_run_account(raw_user: str):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", raw_user):
        raise CandidateCommandError("run user名が不正です。")
    try:
        account = pwd.getpwnam(raw_user)
    except KeyError as exc:
        raise CandidateCommandError("run userが存在しません。") from exc
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise CandidateCommandError("root accountをrun userには指定できません。")
    return account


def _validated_candidate_root(raw_path: Path, *, expected_uid: int) -> Path:
    path = _absolute_path(raw_path, "candidate tenant root")
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or path.resolve(strict=True) != path
    ):
        raise CandidateCommandError(
            "candidate rootはrun user所有0700の実directoryにしてください。"
        )
    _assert_root_owned_parent_chain(path.parent)
    return path


def _validated_staging_backup_root(
    raw_path: Path,
    *,
    candidate_root: Path,
    expected_uid: int,
) -> Path:
    path = _absolute_path(raw_path, "staging backup root")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CandidateCommandError(
            "Staging backup rootを確認できません。"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or resolved != path
        or path == candidate_root
        or path.is_relative_to(candidate_root)
        or candidate_root.is_relative_to(path)
    ):
        raise CandidateCommandError(
            "Staging backup rootはrun user所有0700でcandidateと重ならない実directoryにしてください。"
        )
    _assert_root_owned_parent_chain(path.parent)
    return path


def _validated_candidate_env_sentinel(path: Path, *, expected_uid: int) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CandidateCommandError("candidateのsealed .envを開けません。") from exc
    try:
        before = os.fstat(descriptor)
        content = os.read(descriptor, 1)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_uid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != 0
            or content
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise CandidateCommandError(
                "candidate .envはrun user所有0600の空sealed fileである必要があります。"
            )
    finally:
        os.close(descriptor)


def _validated_root_executable(path: Path) -> Path:
    path = _absolute_path(path, "workspace Python")
    _assert_root_owned_parent_chain(path.parent)
    link_metadata = path.lstat()
    if stat.S_ISLNK(link_metadata.st_mode):
        if link_metadata.st_uid != 0:
            raise CandidateCommandError("workspace Python symlinkが安全ではありません。")
        resolved = path.resolve(strict=True)
        _assert_root_owned_parent_chain(resolved.parent)
        metadata = resolved.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise CandidateCommandError("workspace Pythonの参照先が安全ではありません。")
    else:
        resolved = _validated_root_file(path)
    if not os.access(path, os.X_OK):
        raise CandidateCommandError("workspace Pythonを実行できません。")
    return path


def _validated_root_file(path: Path) -> Path:
    path = _absolute_path(path, "workspace file")
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or path.resolve(strict=True) != path
    ):
        raise CandidateCommandError(
            "workspace executableはroot所有でgroup/other書込不可の通常fileにしてください。"
        )
    return path


def _absolute_path(raw_path: Path, label: str) -> Path:
    value = Path(os.path.abspath(Path(raw_path).expanduser()))
    if not Path(raw_path).expanduser().is_absolute():
        raise CandidateCommandError(f"{label}は絶対pathで指定してください。")
    return value


def _validated_pattern(raw_value: str, pattern: re.Pattern[str], label: str) -> str:
    value = raw_value.strip().lower()
    if not pattern.fullmatch(value):
        raise CandidateCommandError(f"{label}が不正です。")
    return value


def _read_root_env(raw_path: Path) -> dict[str, str]:
    path = _absolute_path(raw_path, "environment file")
    parent_metadata = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_ISLNK(parent_metadata.st_mode)
        or parent_metadata.st_uid != 0
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or path.parent.resolve(strict=True) != path.parent
    ):
        raise CandidateCommandError(
            "environment fileの親directoryはroot所有0700にしてください。"
        )
    _assert_root_owned_parent_chain(path.parent.parent)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CandidateCommandError("environment fileを安全に開けません。") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_ENV_FILE_SIZE
        ):
            raise CandidateCommandError(
                "environment fileはroot所有0600の単一通常fileにしてください。"
            )
        content = b""
        while chunk := os.read(descriptor, 64 * 1024):
            content += chunk
            if len(content) > MAX_ENV_FILE_SIZE:
                raise CandidateCommandError("environment fileが大きすぎます。")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
        ):
            raise CandidateCommandError("environment fileが読取中に変化しました。")
    finally:
        os.close(descriptor)
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CandidateCommandError("environment fileはUTF-8で保存してください。") from exc
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CandidateCommandError(
                f"environment fileの{line_number}行目がKEY=VALUE形式ではありません。"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        parsed = value.strip()
        if not ENV_KEY_PATTERN.fullmatch(key) or key in values:
            raise CandidateCommandError(
                f"environment fileの{line_number}行目のkeyが不正または重複しています。"
            )
        if parsed.startswith(("'", '"')) or parsed.endswith(("'", '"')):
            if len(parsed) < 2 or parsed[0] != parsed[-1]:
                raise CandidateCommandError(
                    f"environment fileの{line_number}行目のquoteが不正です。"
                )
            parsed = parsed[1:-1]
        if "\x00" in parsed:
            raise CandidateCommandError("environment valueにNULは使用できません。")
        values[key] = parsed
    return values


def _assert_machine_keys_safe(values: dict[str, str]) -> None:
    unknown = sorted(values.keys() - MACHINE_ALLOWED_KEYS)
    missing = sorted(MACHINE_REQUIRED_KEYS - values.keys())
    if unknown or missing:
        details = []
        if unknown:
            details.append("未許可key=" + ",".join(unknown))
        if missing:
            details.append("不足key=" + ",".join(missing))
        raise CandidateCommandError(
            "machine envがstrict allowlistと一致しません: " + " ".join(details)
        )
    if (
        len(values["DJANGO_SECRET_KEY"]) < 50
        or not values["DJANGO_ALLOWED_HOSTS"].strip()
        or not values["DJANGO_CSRF_TRUSTED_ORIGINS"].strip()
        or not values["TEMPLEDB_BASE_URL"].strip()
        or not values["DATABASE_PASSWORD"]
    ):
        raise CandidateCommandError("machine envの必須値が空または短すぎます。")
    allowed_hosts = {
        host.strip().casefold()
        for host in values["DJANGO_ALLOWED_HOSTS"].split(",")
        if host.strip()
    }
    if not {"localhost", "127.0.0.1"}.issubset(allowed_hosts):
        raise CandidateCommandError(
            "machine envのallowed hostsにはlocalhostと127.0.0.1が必要です。"
        )


def _assert_safety_environment(
    values: dict[str, str],
    *,
    candidate_root: Path,
    database_name: str,
    machine_values: dict[str, str],
) -> None:
    unknown = sorted(values.keys() - SAFETY_ALLOWED_KEYS)
    missing = sorted(SAFETY_REQUIRED_KEYS - values.keys())
    if unknown or missing:
        details = []
        if unknown:
            details.append("未許可key=" + ",".join(unknown))
        if missing:
            details.append("不足key=" + ",".join(missing))
        raise CandidateCommandError(
            "safety envがtracked templateのallowlistと一致しません: "
            + " ".join(details)
        )
    for key, expected in SAFETY_EXPECTED.items():
        if values.get(key) != expected:
            raise CandidateCommandError(f"safety envの{key}が安全値ではありません。")
    if values["TEMPLEDB_TENANT_ROOT"] != str(candidate_root):
        raise CandidateCommandError("safety envのtenant rootが確認値と一致しません。")
    if values["DATABASE_NAME"] != database_name:
        raise CandidateCommandError("safety envのDB名が確認値と一致しません。")
    if values["DATABASE_HOST"] != "127.0.0.1":
        raise CandidateCommandError("safety envのDB hostは127.0.0.1に固定します。")
    if not values["DATABASE_PORT"].isdigit() or not 1 <= int(
        values["DATABASE_PORT"]
    ) <= 65535:
        raise CandidateCommandError("safety envのDB portが不正です。")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", values["DATABASE_USER"]):
        raise CandidateCommandError("safety envのDB userが不正です。")
    if values["TEMPLEDB_STAGING_ALLOW_OPENAI"] not in {"0", "1"}:
        raise CandidateCommandError("safety envのOpenAI許可値が不正です。")
    if (
        values["TEMPLEDB_STAGING_ALLOW_OPENAI"] == "1"
        and not machine_values.get("OPENAI_API_KEY", "")
    ):
        raise CandidateCommandError(
            "Staging OpenAIを許可する場合はmachine envにAPI keyが必要です。"
        )
    if values["MPLCONFIGDIR"] != str(candidate_root / "data/runtime/matplotlib"):
        raise CandidateCommandError("safety envのMatplotlib pathが不正です。")
    if values["XDG_CACHE_HOME"] != str(candidate_root / "data/runtime/xdg-cache"):
        raise CandidateCommandError("safety envのcache pathが不正です。")
    if not re.fullmatch(
        r"127\.0\.0\.1:(?:[1-9][0-9]{0,4})",
        values["TEMPLEDB_GUNICORN_UPSTREAM"],
    ) or int(values["TEMPLEDB_GUNICORN_UPSTREAM"].rsplit(":", 1)[1]) > 65535:
        raise CandidateCommandError("safety envのGunicorn upstreamが不正です。")
    backup_root = _absolute_path(
        Path(values["TEMPLEDB_BACKUP_DESTINATION_PATH"]),
        "staging backup root",
    )
    if (
        backup_root == candidate_root
        or backup_root.is_relative_to(candidate_root)
        or candidate_root.is_relative_to(backup_root)
    ):
        raise CandidateCommandError(
            "Staging backup rootとcandidate rootを同一または親子pathにはできません。"
        )


def _assert_operator_environment(
    values: dict[str, str],
    *,
    safety_values: dict[str, str],
    machine_values: dict[str, str],
) -> None:
    unknown = sorted(values.keys() - TRANSFER_KEYS)
    missing = sorted(REQUIRED_TRANSFER_KEYS - values.keys())
    if unknown or missing:
        details = []
        if unknown:
            details.append("未許可key=" + ",".join(unknown))
        if missing:
            details.append("不足key=" + ",".join(missing))
        raise CandidateCommandError("operator envが不正です: " + " ".join(details))
    runtime_user = safety_values["DATABASE_USER"]
    runtime_password = machine_values["DATABASE_PASSWORD"]
    if (
        values[f"{TRANSFER_PREFIX}HOST"] != safety_values["DATABASE_HOST"]
        or values[f"{TRANSFER_PREFIX}PORT"] != safety_values["DATABASE_PORT"]
        or values[f"{TRANSFER_PREFIX}ADMIN_DATABASE"] != "postgres"
        or values[f"{TRANSFER_PREFIX}ADMIN_USER"] != runtime_user
        or values[f"{TRANSFER_PREFIX}OWNER_USER"] != runtime_user
        or values.get(f"{TRANSFER_PREFIX}ADMIN_PASSWORD", "")
        != runtime_password
        or values.get(f"{TRANSFER_PREFIX}OWNER_PASSWORD", "")
        != runtime_password
    ):
        raise CandidateCommandError(
            "operator envはlocal postgresと同じcandidate owner資格へ限定します。"
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CandidateCommandError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
