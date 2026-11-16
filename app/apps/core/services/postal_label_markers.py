from __future__ import annotations


def postal_marker_text(
    *,
    is_womens_association: bool,
    include_memorial_notice_marker: bool,
    has_memorial_notice_target: bool,
    memorial_notice_marker_label: str,
) -> str:
    markers: list[str] = []
    if is_womens_association:
        markers.append("F")
    if include_memorial_notice_marker and has_memorial_notice_target:
        markers.append(memorial_notice_marker_label)
    return " ".join(markers)


__all__ = ["postal_marker_text"]
