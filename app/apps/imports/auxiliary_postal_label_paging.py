from __future__ import annotations

from apps.core.services.label_paging import postal_label_pages


def _postal_label_pages(label_rows: list[dict], *, per_page: int) -> list[list[dict | None]]:
    return postal_label_pages(label_rows, per_page=per_page)


__all__ = ["_postal_label_pages"]
