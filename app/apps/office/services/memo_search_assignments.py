from __future__ import annotations

from collections import defaultdict

from apps.imports.models import MemoTagAssignment


def _entry_assignment_key(entry: dict[str, object]) -> tuple[int, int, str]:
    return (
        int(entry["content_type_id"]),
        int(entry["object_id"]),
        str(entry["field_name"]),
    )


def _assignment_map() -> dict[tuple[int, int, str], list[MemoTagAssignment]]:
    assignment_map: dict[tuple[int, int, str], list[MemoTagAssignment]] = defaultdict(list)
    for assignment in MemoTagAssignment.objects.select_related("tag").order_by("tag__label", "id"):
        assignment_map[(assignment.content_type_id, assignment.object_id, assignment.field_name)].append(
            assignment
        )
    return assignment_map
