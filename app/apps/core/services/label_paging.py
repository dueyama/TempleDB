from __future__ import annotations


def postal_label_pages(label_rows: list[dict], *, per_page: int) -> list[list[dict | None]]:
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    if not label_rows:
        return []

    pages: list[list[dict | None]] = []
    for start in range(0, len(label_rows), per_page):
        page = list(label_rows[start : start + per_page])
        if len(page) < per_page:
            page.extend([None] * (per_page - len(page)))
        pages.append(page)
    return pages


__all__ = ["postal_label_pages"]
