from __future__ import annotations

import unicodedata
from pathlib import Path

from config.runtime_paths import private_auxiliary_root as runtime_private_auxiliary_root

from .runtime_shared import _clean_value, _normalize_same_name_text

HAND_DELIVERY_DIRECTORY_PREFIX = "門徒名簿_"
HAND_DELIVERY_FILE_NAME = "手配り-表1.csv"
HAND_DELIVERY_SKIP_DISTRICTS = {"正", "畑"}
POSTAL_FILE_NAME = "郵送（遠隔地門徒＋婦人会）-表1.csv"
MONTO_SODAI_FILE_NAME = "総代-表1.csv"
AUXILIARY_WORKSPACE_HINT = "data/private/auxiliary/"


def _private_auxiliary_root() -> Path:
    return runtime_private_auxiliary_root()


def _auxiliary_input_roots() -> list[Path]:
    return [_private_auxiliary_root()]


def _list_auxiliary_csv_candidates(file_name: str) -> list[dict]:
    candidates = []
    seen_folders: set[str] = set()
    for root in _auxiliary_input_roots():
        if not root.exists():
            continue
        for directory in sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and path.name.startswith(HAND_DELIVERY_DIRECTORY_PREFIX)
            ),
            reverse=True,
        ):
            csv_path = directory / file_name
            if not csv_path.exists():
                continue
            if directory.name in seen_folders:
                continue
            seen_folders.add(directory.name)
            candidates.append(
                {
                    "folder_name": directory.name,
                    "csv_path": csv_path,
                }
            )
    return candidates


def _normalize_auxiliary_district_name(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    return "".join(char for char in normalized if char not in {" ", "　"})


def _normalize_auxiliary_household_name(value: str | None) -> str:
    return _normalize_same_name_text(value)


def _parse_auxiliary_sort_order(value: str | None, fallback: int) -> int:
    cleaned = _clean_value(value)
    if cleaned.isdigit():
        return int(cleaned)
    return fallback


def _normalize_auxiliary_postal_code(value: str | None) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        return ""
    normalized = unicodedata.normalize("NFKC", cleaned)
    return "".join(char for char in normalized if char.isdigit() or char == "-")
