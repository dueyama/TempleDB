from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from config import runtime_paths
from config.platform_file_lock import lock_exclusive, unlock

UI_THEME_CHOICES = (
    ("standard", "標準（立体ボタン）"),
    ("light", "軽量（フラットボタン）"),
)
DEFAULT_UI_THEME = "standard"
ALLOWED_UI_THEMES = frozenset(value for value, _label in UI_THEME_CHOICES)
UI_THEME_LABELS = dict(UI_THEME_CHOICES)
UI_APPEARANCE_SCHEMA_VERSION = 1
UI_APPEARANCE_FILENAME = "ui_appearance.json"
MAX_UI_APPEARANCE_BYTES = 64 * 1024


class UiAppearanceError(ValueError):
    """Raised when the UI appearance preference cannot be read or written safely."""


@dataclass(frozen=True)
class UiAppearanceState:
    theme: str
    source: str
    error: str = ""


def ui_appearance_path() -> Path:
    return runtime_paths.tenant_preferences_root() / UI_APPEARANCE_FILENAME


def configured_default_theme() -> str:
    theme = getattr(settings, "TEMPLEDB_UI_THEME", DEFAULT_UI_THEME)
    allowed = getattr(settings, "TEMPLEDB_ALLOWED_UI_THEMES", ALLOWED_UI_THEMES)
    return theme if theme in allowed else DEFAULT_UI_THEME


def normalize_ui_appearance(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "theme"}:
        raise UiAppearanceError(
            "表示設定JSONは schema_version と theme だけを指定してください。"
        )
    schema_version = payload["schema_version"]
    theme = payload["theme"]
    if (
        isinstance(schema_version, bool)
        or schema_version != UI_APPEARANCE_SCHEMA_VERSION
    ):
        raise UiAppearanceError("表示設定JSONのschema_versionに対応していません。")
    if not isinstance(theme, str) or theme not in ALLOWED_UI_THEMES:
        raise UiAppearanceError("表示テーマは standard または light を指定してください。")
    return {
        "schema_version": UI_APPEARANCE_SCHEMA_VERSION,
        "theme": theme,
    }


def load_ui_appearance(*, path: Path | None = None) -> dict[str, object] | None:
    source_path = (
        Path(path)
        if path is not None
        else _validated_ui_appearance_source(ui_appearance_path())
    )
    if not os.path.lexists(source_path):
        return None
    try:
        source_metadata = source_path.lstat()
    except OSError as exc:
        raise UiAppearanceError("表示設定JSONを確認できません。") from exc
    if (
        not stat.S_ISREG(source_metadata.st_mode)
        or stat.S_ISLNK(source_metadata.st_mode)
        or source_metadata.st_nlink != 1
        or source_metadata.st_size > MAX_UI_APPEARANCE_BYTES
    ):
        raise UiAppearanceError("表示設定JSONが通常の小さいfileではありません。")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise UiAppearanceError("表示設定JSONを安全に開けません。") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_UI_APPEARANCE_BYTES
            or (
                source_metadata.st_ino
                and metadata.st_ino
                and (
                    source_metadata.st_dev,
                    source_metadata.st_ino,
                )
                != (metadata.st_dev, metadata.st_ino)
            )
        ):
            raise UiAppearanceError("表示設定JSONが通常の小さいfileではありません。")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            content = handle.read(MAX_UI_APPEARANCE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > MAX_UI_APPEARANCE_BYTES:
        raise UiAppearanceError("表示設定JSONが大きすぎます。")
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, UiAppearanceError) as exc:
        raise UiAppearanceError("表示設定JSONを読み取れません。") from exc
    return normalize_ui_appearance(payload)


def ui_appearance_state() -> UiAppearanceState:
    fallback = configured_default_theme()
    try:
        payload = load_ui_appearance()
    except UiAppearanceError as exc:
        return UiAppearanceState(
            theme=fallback,
            source="legacy-env-fallback",
            error=str(exc),
        )
    if payload is None:
        return UiAppearanceState(
            theme=fallback,
            source="legacy-env-fallback",
        )
    return UiAppearanceState(
        theme=str(payload["theme"]),
        source="tenant-preferences-json",
    )


def active_ui_theme() -> str:
    return ui_appearance_state().theme


def active_ui_theme_label() -> str:
    return UI_THEME_LABELS[active_ui_theme()]


def save_ui_theme(theme: str) -> Path:
    payload = normalize_ui_appearance(
        {
            "schema_version": UI_APPEARANCE_SCHEMA_VERSION,
            "theme": theme,
        }
    )
    destination = _validated_ui_appearance_destination(ui_appearance_path())
    with _ui_appearance_write_lock():
        _reject_unsafe_existing_file(destination)
        _write_json_atomic(destination, payload)
    return destination


def _validated_ui_appearance_destination(raw_path: Path) -> Path:
    tenant_root = Path(os.path.abspath(runtime_paths.tenant_root()))
    destination = Path(os.path.abspath(raw_path))
    if not destination.is_relative_to(tenant_root):
        raise UiAppearanceError("表示設定JSONの保存先がtenant root外です。")
    _ensure_safe_directory_tree(
        tenant_root,
        destination.parent,
    )
    return destination


def _validated_ui_appearance_source(raw_path: Path) -> Path:
    tenant_root = Path(os.path.abspath(runtime_paths.tenant_root()))
    source = Path(os.path.abspath(raw_path))
    if not source.is_relative_to(tenant_root):
        raise UiAppearanceError("表示設定JSONの読込先がtenant root外です。")
    if os.path.lexists(source):
        _validate_existing_directory_tree(tenant_root, source.parent)
    return source


def _validate_existing_directory_tree(
    tenant_root: Path,
    source_parent: Path,
) -> None:
    try:
        tenant_metadata = tenant_root.lstat()
    except OSError as exc:
        raise UiAppearanceError("tenant rootを確認できません。") from exc
    if (
        not stat.S_ISDIR(tenant_metadata.st_mode)
        or stat.S_ISLNK(tenant_metadata.st_mode)
    ):
        raise UiAppearanceError("tenant rootが通常directoryではありません。")
    current = tenant_root
    for part in source_parent.relative_to(tenant_root).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise UiAppearanceError(
                "表示設定JSONの親directoryを確認できません。"
            ) from exc
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise UiAppearanceError("表示設定JSONの親directoryが安全ではありません。")


def _ensure_safe_directory_tree(tenant_root: Path, destination_parent: Path) -> None:
    try:
        tenant_metadata = tenant_root.lstat()
    except OSError as exc:
        raise UiAppearanceError("tenant rootを確認できません。") from exc
    if (
        not stat.S_ISDIR(tenant_metadata.st_mode)
        or stat.S_ISLNK(tenant_metadata.st_mode)
    ):
        raise UiAppearanceError("tenant rootが通常directoryではありません。")

    current = tenant_root
    for part in destination_parent.relative_to(tenant_root).parts:
        current = current / part
        if os.path.lexists(current):
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise UiAppearanceError("表示設定JSONの親directoryが安全ではありません。")
            continue
        try:
            current.mkdir(mode=0o700)
        except FileExistsError as exc:
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise UiAppearanceError(
                    "表示設定JSONの親directoryが安全ではありません。"
                ) from exc
        except OSError as exc:
            raise UiAppearanceError("表示設定JSONの親directoryを作成できません。") from exc


def _reject_unsafe_existing_file(path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UiAppearanceError("既存の表示設定JSONを確認できません。") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise UiAppearanceError("既存の表示設定JSONが安全な通常fileではありません。")


@contextmanager
def _ui_appearance_write_lock() -> Iterator[None]:
    tenant_root = Path(os.path.abspath(runtime_paths.tenant_root()))
    runtime_root = Path(os.path.abspath(runtime_paths.runtime_root()))
    if not runtime_root.is_relative_to(tenant_root):
        raise UiAppearanceError("表示設定の保存lockがtenant root外です。")
    _ensure_safe_directory_tree(tenant_root, runtime_root)
    lock_path = runtime_root / "ui_appearance.lock"
    existing_metadata: os.stat_result | None = None
    if os.path.lexists(lock_path):
        try:
            existing_metadata = lock_path.lstat()
        except OSError as exc:
            raise UiAppearanceError("表示設定の保存lockを確認できません。") from exc
        if (
            not stat.S_ISREG(existing_metadata.st_mode)
            or stat.S_ISLNK(existing_metadata.st_mode)
            or existing_metadata.st_nlink != 1
        ):
            raise UiAppearanceError(
                "表示設定の保存lockが安全な通常fileではありません。"
            )
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise UiAppearanceError("表示設定の保存lockを取得できません。") from exc
    try:
        try:
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise UiAppearanceError(
                "表示設定の保存lockを確認できません。"
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (
                existing_metadata is not None
                and existing_metadata.st_ino
                and metadata.st_ino
                and (
                    existing_metadata.st_dev,
                    existing_metadata.st_ino,
                )
                != (metadata.st_dev, metadata.st_ino)
            )
        ):
            raise UiAppearanceError("表示設定の保存lockが安全な通常fileではありません。")
        _lock_file_descriptor(descriptor)
        try:
            yield
        finally:
            _unlock_file_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        if os.name != "nt":
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except OSError as exc:
        raise UiAppearanceError("表示設定JSONを保存できません。") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _lock_file_descriptor(descriptor: int) -> None:
    try:
        lock_exclusive(descriptor)
    except OSError as exc:
        raise UiAppearanceError("表示設定の保存lockを取得できません。") from exc


def _unlock_file_descriptor(descriptor: int) -> None:
    try:
        unlock(descriptor)
    except OSError:
        # Closing the descriptor immediately afterwards also releases the lock.
        pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise UiAppearanceError("表示設定JSONのkeyが重複しています。")
        payload[key] = value
    return payload


def clear_ui_theme_cache() -> None:
    return None
