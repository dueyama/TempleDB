from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
CURRENT_POINTER_NAME = "current"
INSTANCES_DIRECTORY_NAME = "instances"
INSTANCE_ENV_FILENAME = ".env"
MAX_INSTANCE_ENV_BYTES = 256 * 1024
SWITCH_RECORD_FILENAME = ".last-instance-switch.json"
SWITCH_RECORD_SCHEMA_VERSION = 1
ALLOWED_INSTANCE_TARGETS = {
    "demo": Path(INSTANCES_DIRECTORY_NAME) / "demo",
    "product": Path(INSTANCES_DIRECTORY_NAME) / "product",
}


class InstanceSelectionError(RuntimeError):
    """Raised when the active demo/product instance cannot be selected safely."""


@dataclass(frozen=True)
class InstanceSelection:
    name: str
    root: Path
    env_path: Path


def selected_instance(
    *,
    platform_root: Path | None = None,
) -> InstanceSelection | None:
    root = _absolute_platform_root(platform_root)
    _validate_owned_directory(
        root,
        label="Platform root",
        allow_root_owner=True,
    )
    pointer = root / CURRENT_POINTER_NAME
    pointer_exists = os.path.lexists(pointer)
    recorded_current = _validated_completed_switch_record(root)
    if not pointer_exists:
        if recorded_current not in {None, "legacy"}:
            raise InstanceSelectionError(
                "TempleDBのcurrentと前回instance切替記録が一致しません。"
            )
        return None

    try:
        pointer_metadata = pointer.lstat()
    except OSError as exc:
        raise InstanceSelectionError(
            "TempleDBのcurrent instanceを確認できません。"
        ) from exc
    if not stat.S_ISLNK(pointer_metadata.st_mode):
        raise InstanceSelectionError(
            "TempleDBのcurrentはdemoまたはproductへの相対symlinkにしてください。"
        )

    try:
        raw_target = os.readlink(pointer)
    except OSError as exc:
        raise InstanceSelectionError(
            "TempleDBのcurrent instanceを読み取れません。"
        ) from exc
    if Path(raw_target).is_absolute():
        raise InstanceSelectionError(
            "TempleDBのcurrentはinstances/demoまたはinstances/productへの"
            "相対symlinkにしてください。"
        )

    instance_name = next(
        (
            name
            for name, allowed_target in ALLOWED_INSTANCE_TARGETS.items()
            if raw_target == str(allowed_target)
        ),
        None,
    )
    if instance_name is None:
        raise InstanceSelectionError(
            "TempleDBのcurrentはinstances/demoまたはinstances/productだけを"
            "選択できます。"
        )
    if recorded_current is None:
        raise InstanceSelectionError(
            "TempleDBのcurrentに対応する完了済みinstance切替記録がありません。"
        )
    if recorded_current != instance_name:
        raise InstanceSelectionError(
            "TempleDBのcurrentと前回instance切替記録が一致しません。"
        )
    return validate_instance(instance_name, platform_root=root)


def validate_instance(
    instance_name: str,
    *,
    platform_root: Path | None = None,
) -> InstanceSelection:
    root = _absolute_platform_root(platform_root)
    if instance_name not in ALLOWED_INSTANCE_TARGETS:
        raise InstanceSelectionError(
            "TempleDBのinstanceはdemoまたはproductだけを指定できます。"
        )
    _validate_owned_directory(
        root,
        label="Platform root",
        allow_root_owner=True,
    )
    target = ALLOWED_INSTANCE_TARGETS[instance_name]

    instances_root = root / INSTANCES_DIRECTORY_NAME
    _validate_owned_directory(
        instances_root,
        label="instances",
        allow_root_owner=True,
    )
    instance_root = root / target
    _validate_owned_directory(
        instance_root,
        label=f"instances/{instance_name}",
        owner_only=True,
    )
    env_path = instance_root / INSTANCE_ENV_FILENAME
    _validate_instance_env_file(env_path)
    _validate_instance_env_content(env_path)
    return InstanceSelection(
        name=instance_name,
        root=instance_root,
        env_path=env_path,
    )


def _absolute_platform_root(platform_root: Path | None) -> Path:
    root = PLATFORM_ROOT if platform_root is None else Path(platform_root)
    if not root.is_absolute():
        raise InstanceSelectionError("TempleDBのPlatform rootは絶対pathが必要です。")
    return Path(os.path.abspath(root))


def _enforces_posix_permissions() -> bool:
    return os.name == "posix"


def _validate_owned_directory(
    path: Path,
    *,
    label: str,
    owner_only: bool = False,
    allow_root_owner: bool = False,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise InstanceSelectionError(f"{label} directoryがありません。") from exc
    except OSError as exc:
        raise InstanceSelectionError(f"{label} directoryを確認できません。") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise InstanceSelectionError(f"{label}は通常のdirectoryである必要があります。")
    enforce_permissions = _enforces_posix_permissions()
    if enforce_permissions and owner_only and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise InstanceSelectionError(
            f"{label}はownerだけがアクセスできる権限にしてください。"
        )
    if enforce_permissions and not owner_only and metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise InstanceSelectionError(
            f"{label}はgroupまたは他userから書き込めない権限にしてください。"
        )
    if (
        enforce_permissions
        and hasattr(os, "geteuid")
        and metadata.st_uid != os.geteuid()
        and not (allow_root_owner and metadata.st_uid == 0)
    ):
        raise InstanceSelectionError(f"{label}の所有者が現在userではありません。")


def _validate_instance_env_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise InstanceSelectionError("選択したinstanceに.envがありません。") from exc
    except OSError as exc:
        raise InstanceSelectionError("選択したinstanceの.envを確認できません。") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise InstanceSelectionError(
            "選択したinstanceの.envは単一linkの通常fileである必要があります。"
        )
    if metadata.st_size > MAX_INSTANCE_ENV_BYTES:
        raise InstanceSelectionError("選択したinstanceの.envが大きすぎます。")
    enforce_permissions = _enforces_posix_permissions()
    if enforce_permissions and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise InstanceSelectionError(
            "選択したinstanceの.envはownerだけがアクセスできる権限にしてください。"
        )
    if enforce_permissions and not metadata.st_mode & stat.S_IRUSR:
        raise InstanceSelectionError(
            "選択したinstanceの.envをownerが読み取れる権限にしてください。"
        )
    if (
        enforce_permissions
        and hasattr(os, "geteuid")
        and metadata.st_uid != os.geteuid()
    ):
        raise InstanceSelectionError(
            "選択したinstanceの.envの所有者が現在userではありません。"
        )


def _validate_instance_env_content(path: Path) -> None:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise InstanceSelectionError(
            "選択したinstanceの.envをUTF-8として読み取れません。"
        ) from exc
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key == "TEMPLEDB_TENANT_ROOT":
            raise InstanceSelectionError(
                "instanceの.envにはTEMPLEDB_TENANT_ROOTを書かず、"
                "TempleDB/currentで選択してください。"
            )
        if normalized_key.startswith("TEMPLEDB_LAUNCHER_"):
            raise InstanceSelectionError(
                "instanceの.envにはTEMPLEDB_LAUNCHER_内部変数を書けません。"
            )


def _validated_completed_switch_record(root: Path) -> str | None:
    record_path = root / INSTANCES_DIRECTORY_NAME / SWITCH_RECORD_FILENAME
    if not os.path.lexists(record_path):
        return None
    try:
        metadata = record_path.lstat()
    except OSError as exc:
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録を確認できません。"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録は単一linkの通常fileが必要です。"
        )
    enforce_permissions = _enforces_posix_permissions()
    if enforce_permissions and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録はowner-onlyにしてください。"
        )
    if (
        enforce_permissions
        and hasattr(os, "geteuid")
        and metadata.st_uid != os.geteuid()
    ):
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録の所有者が現在userではありません。"
        )
    if metadata.st_size > 64 * 1024:
        raise InstanceSelectionError("TempleDBのinstance切替記録が大きすぎます。")
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録を読み取れません。"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SWITCH_RECORD_SCHEMA_VERSION
        or payload.get("state") != "complete"
    ):
        raise InstanceSelectionError(
            "TempleDBのinstance切替が未完了です。rollbackまたは復旧を行ってください。"
        )
    recorded_current = payload.get("current")
    if recorded_current not in {"legacy", *ALLOWED_INSTANCE_TARGETS}:
        raise InstanceSelectionError(
            "TempleDBのinstance切替記録のcurrentが不正です。"
        )
    return str(recorded_current)


__all__ = [
    "ALLOWED_INSTANCE_TARGETS",
    "CURRENT_POINTER_NAME",
    "INSTANCE_ENV_FILENAME",
    "INSTANCES_DIRECTORY_NAME",
    "InstanceSelection",
    "InstanceSelectionError",
    "PLATFORM_ROOT",
    "SWITCH_RECORD_FILENAME",
    "SWITCH_RECORD_SCHEMA_VERSION",
    "selected_instance",
    "validate_instance",
]
