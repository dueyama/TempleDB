from __future__ import annotations

from .auxiliary_input_support import POSTAL_FILE_NAME, _list_auxiliary_csv_candidates


def list_auxiliary_postal_csv_candidates() -> list[dict]:
    return _list_auxiliary_csv_candidates(POSTAL_FILE_NAME)


def latest_auxiliary_postal_csv_path(folder_name: str | None = None):
    candidates = list_auxiliary_postal_csv_candidates()
    if folder_name:
        selected = next((item for item in candidates if item["folder_name"] == folder_name), None)
        return selected["csv_path"] if selected else None
    return candidates[0]["csv_path"] if candidates else None
