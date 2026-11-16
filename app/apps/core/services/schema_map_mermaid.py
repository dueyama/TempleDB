from __future__ import annotations


def _build_mermaid_source(apps_payload: list[dict[str, object]], relation_lines: list[str]) -> str:
    lines = ["erDiagram"]
    for app_payload in apps_payload:
        for model in app_payload["models"]:
            lines.append(f"  {model['name']} {{")
            for field in model["fields"]:
                markers: list[str] = []
                if field["primary_key"]:
                    markers.append("PK")
                elif field["is_relation"]:
                    markers.append("FK")
                marker_text = f" {' '.join(markers)}" if markers else ""
                lines.append(f"    {field['type_label']} {field['name']}{marker_text}")
            lines.append("  }")
    for relation_line in relation_lines:
        lines.append(f"  {relation_line}")
    return "\n".join(lines)


def _build_flow_diagram(
    steps: list[dict[str, str]],
    model_lookup: dict[str, dict[str, object]],
    *,
    business_model_metadata: dict[str, dict[str, object]],
    find_model_label,
    find_relation_label_between,
) -> dict[str, object]:
    box_width = 210
    box_height = 108
    box_gap = 56
    left_padding = 20
    top_padding = 18
    boxes: list[dict[str, object]] = []
    connectors: list[dict[str, object]] = []

    for index, step in enumerate(steps):
        x = left_padding + index * (box_width + box_gap)
        y = top_padding
        key_fields = business_model_metadata.get(
            f"imports.{step['model_name']}" if not step["model_name"].startswith("Database") else "",
            {},
        ).get("key_fields", ())
        boxes.append(
            {
                "x": x,
                "y": y,
                "width": box_width,
                "height": box_height,
                "label": step["label"],
                "model_name": step["model_name"],
                "summary": step["summary"],
                "key_fields": key_fields,
            }
        )

    for index in range(len(steps) - 1):
        current_step = steps[index]
        next_step = steps[index + 1]
        current_label = find_model_label(current_step["model_name"], model_lookup)
        next_label = find_model_label(next_step["model_name"], model_lookup)
        relation_label = find_relation_label_between(current_label, next_label, model_lookup)
        current_box = boxes[index]
        next_box = boxes[index + 1]
        connectors.append(
            {
                "x1": current_box["x"] + box_width,
                "y1": current_box["y"] + box_height / 2,
                "x2": next_box["x"],
                "y2": next_box["y"] + box_height / 2,
                "label": relation_label,
            }
        )

    return {
        "width": left_padding * 2 + len(boxes) * box_width + max(len(boxes) - 1, 0) * box_gap,
        "height": top_padding * 2 + box_height,
        "boxes": boxes,
        "connectors": connectors,
    }


__all__ = [
    "_build_flow_diagram",
    "_build_mermaid_source",
]
