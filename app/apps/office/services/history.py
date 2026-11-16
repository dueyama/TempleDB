from __future__ import annotations

from apps.office.services.record_history_feed import _build_record_history_context


def build_record_history_context(
    *,
    source_id: str | None = None,
    query: str,
    action: str,
    current_url: str,
) -> dict:
    return _build_record_history_context(
        source_id=source_id,
        query=query,
        action=action,
        current_url=current_url,
    )
