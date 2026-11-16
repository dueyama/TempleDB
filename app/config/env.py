from __future__ import annotations

import argparse
import base64
import os
import re
from collections.abc import Iterable
from pathlib import Path

from config.instance_runtime import (
    PLATFORM_ROOT,
    InstanceSelection,
    InstanceSelectionError,
    selected_instance,
)

_loaded_instance: InstanceSelection | None = None
_ENV_KEY_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
_ENV_LINE_BREAK_CHARACTERS = frozenset(
    "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
)
class EnvFileSyntaxError(ValueError):
    """Raised when a TempleDB env file is not safe to parse consistently."""


def parse_env_lines(raw_lines: Iterable[str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for line_number, raw_line in enumerate(raw_lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvFileSyntaxError(
                f".envの{line_number}行目にKEY=VALUE形式がありません。"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_PATTERN.fullmatch(key):
            raise EnvFileSyntaxError(
                f".envの{line_number}行目のkeyは英大文字・数字・underscoreだけで"
                "指定してください。"
            )
        if key in seen_keys:
            raise EnvFileSyntaxError(
                f".envの{line_number}行目でkey {key}が重複しています。"
            )
        seen_keys.add(key)
        parsed = value.strip()
        if parsed.startswith(("'", '"')) or parsed.endswith(("'", '"')):
            if (
                len(parsed) < 2
                or parsed[0] != parsed[-1]
                or parsed[0] not in {"'", '"'}
            ):
                raise EnvFileSyntaxError(
                    f".envの{line_number}行目のquoteが対応していません。"
                )
            parsed = parsed[1:-1]
        if "\x00" in parsed:
            raise EnvFileSyntaxError(
                f".envの{line_number}行目のvalueにNULは使用できません。"
            )
        values.append((key, parsed))
    return values


def serialize_env_pairs(pairs: Iterable[tuple[str, str]]) -> str:
    """Serialize parsed env pairs without changing any supported value."""

    normalized: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    serialized_lines: list[str] = []
    for pair_number, pair in enumerate(pairs, start=1):
        try:
            key, value = pair
        except (TypeError, ValueError) as exc:
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目はkeyとvalueの組で指定してください。"
            ) from exc
        if not isinstance(key, str) or not _ENV_KEY_PATTERN.fullmatch(key):
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目のkeyは英大文字・数字・underscoreだけで"
                "指定してください。"
            )
        if key in seen_keys:
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目でkey {key}が重複しています。"
            )
        if not isinstance(value, str):
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目のvalueは文字列で指定してください。"
            )
        if "\x00" in value:
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目のvalueにNULは使用できません。"
            )
        if any(character in _ENV_LINE_BREAK_CHARACTERS for character in value):
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目のvalueに改行は使用できません。"
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise EnvFileSyntaxError(
                f".envの{pair_number}番目のvalueをUTF-8で保存できません。"
            ) from exc

        seen_keys.add(key)
        normalized.append((key, value))
        # The parser treats only the outer quote pair specially. Quoting every
        # value therefore preserves leading/trailing whitespace and literal
        # quote, hash, dollar, backtick, and backslash characters without
        # introducing shell-style escaping or expansion.
        serialized_lines.append(f"{key}='{value}'")

    content = "\n".join(serialized_lines)
    if serialized_lines:
        content += "\n"
    if parse_env_lines(content.splitlines()) != normalized:
        raise EnvFileSyntaxError(".envのserialize後round-trip検証に失敗しました。")
    return content


def load_env_file(
    *,
    override: bool = False,
    env_path: Path | None = None,
    platform_root: Path | None = None,
) -> None:
    global _loaded_instance
    selected = None
    explicit_tenant_root = False
    if env_path is None:
        explicit_tenant_root = bool(
            os.environ.get("TEMPLEDB_TENANT_ROOT", "").strip()
        )
        if (
            _loaded_instance is not None
            and os.environ.get("TEMPLEDB_TENANT_ROOT")
            == str(_loaded_instance.root)
        ):
            selected = _loaded_instance
        else:
            selected = _selected_instance_for_environment(
                platform_root=platform_root
            )
        path = selected.env_path if selected is not None else _default_env_path(
            platform_root=platform_root
        )
    else:
        path = Path(env_path)
    if not path.exists():
        if selected is not None:
            raise InstanceSelectionError(
                "選択したinstanceの.envが読み込み前に失われました。"
            )
        if explicit_tenant_root:
            raise EnvFileSyntaxError(
                "TEMPLEDB_TENANT_ROOTで指定したrootに.envがありません。"
            )
        return
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        if selected is not None:
            raise InstanceSelectionError(
                "選択したinstanceの.envをUTF-8として読み取れません。"
            ) from exc
        raise
    if selected is not None:
        os.environ["TEMPLEDB_TENANT_ROOT"] = str(selected.root)
        _loaded_instance = selected
    for key, parsed in parse_env_lines(raw_lines):
        if not override and key in os.environ:
            continue
        os.environ[key] = parsed


def _selected_instance_for_environment(
    *,
    platform_root: Path | None,
) -> InstanceSelection | None:
    if os.environ.get("TEMPLEDB_TENANT_ROOT", "").strip():
        return None
    return selected_instance(platform_root=platform_root)


def _default_env_path(*, platform_root: Path | None = None) -> Path:
    configured_tenant_root = os.environ.get("TEMPLEDB_TENANT_ROOT", "").strip()
    if configured_tenant_root:
        configured = Path(configured_tenant_root).expanduser()
        if not configured.is_absolute():
            raise EnvFileSyntaxError(
                "TEMPLEDB_TENANT_ROOTは絶対pathで指定してください。"
            )
        return Path(os.path.abspath(configured)) / ".env"
    root = PLATFORM_ROOT if platform_root is None else Path(platform_root)
    return root / ".env"


def _emit_base64_pairs(path: Path) -> None:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        values = parse_env_lines(raw_lines)
    except (OSError, UnicodeError, EnvFileSyntaxError) as exc:
        raise SystemExit(str(exc)) from exc
    for key, value in values:
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        print(f"{key}\t{encoded}")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-base64", type=Path)
    args = parser.parse_args()
    if args.emit_base64 is None:
        parser.error("--emit-base64 is required")
    _emit_base64_pairs(args.emit_base64)


__all__ = [
    "EnvFileSyntaxError",
    "load_env_file",
    "parse_env_lines",
    "serialize_env_pairs",
]


if __name__ == "__main__":
    _main()
