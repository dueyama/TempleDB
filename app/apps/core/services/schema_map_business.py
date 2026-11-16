from __future__ import annotations

from . import schema_map_mermaid

BUSINESS_SCHEMA_GROUPS = (
    {
        "key": "import_pipeline",
        "title": "取込の主系",
        "description": "外部 source から snapshot と batch を作り、issue を残しながら canonical data へ入る流れです。",
        "models": ("imports.LegacySource", "imports.ExportSnapshot", "imports.ImportBatch", "imports.ImportIssue"),
    },
    {
        "key": "office_runtime",
        "title": "寺務運用の主系",
        "description": "戸主・人物・故人詳細・法要予定が、日常運用で最もよく辿る中心線です。",
        "models": (
            "imports.Household",
            "imports.Person",
            "imports.DeceasedProfile",
            "imports.ServiceSchedule",
            "imports.OfferingPayment",
            "imports.VisitNote",
        ),
    },
    {
        "key": "delivery_and_overrides",
        "title": "地区・送付・補助設定",
        "description": "送付区分、地区、翌年回忌案内の年別 override、Google 同期などの周辺構造です。",
        "models": (
            "imports.District",
            "imports.HouseholdProfile",
            "imports.MemorialNoticeTemplate",
            "imports.GoogleCalendarSyncBinding",
            "imports.AnnualMembershipFeeSetting",
            "imports.AnnualMembershipFeePayment",
        ),
    },
)
BUSINESS_SCHEMA_FLOWS = (
    {
        "title": "取込から運用データまで",
        "description": "外部データが TempleDB の日常運用データへ入る主線です。",
        "steps": (
            "imports.LegacySource",
            "imports.ExportSnapshot",
            "imports.ImportBatch",
            "imports.Household",
            "imports.Person",
            "imports.DeceasedProfile",
        ),
    },
    {
        "title": "法要とその周辺",
        "description": "戸主・人物から法要予定、Google 同期、入金、訪問記録へ繋がる主線です。",
        "steps": (
            "imports.Household",
            "imports.Person",
            "imports.ServiceSchedule",
            "imports.GoogleCalendarSyncBinding",
            "imports.OfferingPayment",
            "imports.VisitNote",
        ),
    },
    {
        "title": "地区・送付・案内文面",
        "description": "戸主ごとの送付・地区設定と、翌年回忌案内の年別 override の関係です。",
        "steps": (
            "imports.LegacySource",
            "imports.HouseholdProfile",
            "imports.District",
            "imports.MemorialNoticeTemplate",
        ),
    },
)
BUSINESS_MODEL_METADATA = {
    "imports.LegacySource": {
        "label": "取込 source",
        "summary": "元DB・CSV・export などの入力元",
        "key_fields": ("source_id", "label", "is_primary"),
    },
    "imports.ExportSnapshot": {
        "label": "ExportSnapshot",
        "summary": "source から取った時点保存",
        "key_fields": ("source", "snapshot_id"),
    },
    "imports.ImportBatch": {
        "label": "ImportBatch",
        "summary": "TempleDB への投入履歴",
        "key_fields": ("source", "export_snapshot", "status"),
    },
    "imports.ImportIssue": {
        "label": "ImportIssue",
        "summary": "投入時の warning / error",
        "key_fields": ("batch", "severity", "code"),
    },
    "imports.Household": {
        "label": "戸主・家",
        "summary": "日常運用の中心単位",
        "key_fields": ("batch", "household_uid", "head_person"),
    },
    "imports.Person": {
        "label": "人物",
        "summary": "現在帳 / 過去帳を含む人物",
        "key_fields": ("household", "person_uid", "is_deceased"),
    },
    "imports.DeceasedProfile": {
        "label": "故人詳細",
        "summary": "故人情報の補助詳細",
        "key_fields": ("person", "death_date", "kaimyo"),
    },
    "imports.ServiceSchedule": {
        "label": "法要予定",
        "summary": "年忌・葬儀・訪問などの予定",
        "key_fields": ("household", "person", "scheduled_date"),
    },
    "imports.OfferingPayment": {
        "label": "お布施等",
        "summary": "法要関連の入金記録",
        "key_fields": ("service_schedule", "amount", "received_on"),
    },
    "imports.VisitNote": {
        "label": "訪問メモ",
        "summary": "訪問・応対の記録",
        "key_fields": ("household", "person", "visited_on"),
    },
    "imports.District": {
        "label": "地区",
        "summary": "地区マスタ",
        "key_fields": ("name", "sort_order"),
    },
    "imports.HouseholdProfile": {
        "label": "送付・地区設定",
        "summary": "戸主ごとの送付区分や地区",
        "key_fields": ("source", "household_uid", "district"),
    },
    "imports.MemorialNoticeTemplate": {
        "label": "案内文面 override",
        "summary": "翌年回忌案内の年別保存",
        "key_fields": ("source", "target_year"),
    },
    "imports.GoogleCalendarSyncBinding": {
        "label": "Google 同期",
        "summary": "法要予定と Google event の対応",
        "key_fields": ("primary_schedule", "sync_status"),
    },
    "imports.AnnualMembershipFeeSetting": {
        "label": "護持会費設定",
        "summary": "年ごとの既定額",
        "key_fields": ("source", "year", "default_amount"),
    },
    "imports.AnnualMembershipFeePayment": {
        "label": "護持会費支払",
        "summary": "戸主ごとの入金記録",
        "key_fields": ("source", "household_uid", "year"),
    },
}


def _build_business_groups(model_lookup: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for group in BUSINESS_SCHEMA_GROUPS:
        group_models: list[dict[str, object]] = []
        mermaid_lines: list[str] = ["erDiagram"]
        included_model_labels = [label for label in group["models"] if label in model_lookup]
        included_model_set = set(included_model_labels)

        for model_label in included_model_labels:
            model = model_lookup[model_label]
            meta = BUSINESS_MODEL_METADATA.get(model_label, {})
            group_models.append(
                {
                    "label": model_label,
                    "name": model["name"],
                    "display_label": meta.get("label") or model["name"],
                    "summary": meta.get("summary") or "",
                    "relation_count": model["relation_count"],
                }
            )
            mermaid_lines.append(f"  {model['name']} {{")
            mermaid_lines.append(f"    string {meta.get('label') or model['name']}")
            mermaid_lines.append("  }")

        relation_summaries: list[dict[str, str]] = []
        added_relation_lines: set[str] = set()
        for model_label in included_model_labels:
            model = model_lookup[model_label]
            for relation in model["relations"]:
                related_label = str(relation["related_model_label"])
                if related_label not in included_model_set:
                    continue
                relation_line = str(relation["mermaid_line"])
                if relation_line not in added_relation_lines:
                    mermaid_lines.append(f"  {relation_line}")
                    added_relation_lines.add(relation_line)
                relation_summaries.append(
                    {
                        "from_label": str(
                            BUSINESS_MODEL_METADATA.get(model_label, {}).get("label") or model["name"]
                        ),
                        "to_label": str(
                            BUSINESS_MODEL_METADATA.get(related_label, {}).get("label")
                            or model_lookup[related_label]["name"]
                        ),
                        "field_name": str(relation["field_name"]),
                        "relation_type": str(relation["relation_type"]),
                    }
                )

        groups.append(
            {
                "key": group["key"],
                "title": group["title"],
                "description": group["description"],
                "models": group_models,
                "relations": relation_summaries,
                "mermaid_source": "\n".join(mermaid_lines),
            }
        )
    return groups


def _build_business_flows(model_lookup: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    flows: list[dict[str, object]] = []
    for flow in BUSINESS_SCHEMA_FLOWS:
        steps: list[dict[str, str]] = []
        for model_label in flow["steps"]:
            model = model_lookup.get(model_label)
            if model is None:
                continue
            meta = BUSINESS_MODEL_METADATA.get(model_label, {})
            steps.append(
                {
                    "label": str(meta.get("label") or model["name"]),
                    "model_name": str(model["name"]),
                    "summary": str(meta.get("summary") or ""),
                }
            )
        flows.append(
            {
                "title": flow["title"],
                "description": flow["description"],
                "steps": steps,
                "diagram": schema_map_mermaid._build_flow_diagram(
                    steps,
                    model_lookup,
                    business_model_metadata=BUSINESS_MODEL_METADATA,
                    find_model_label=_find_model_label,
                    find_relation_label_between=_find_relation_label_between,
                ),
            }
        )
    return flows


def _find_model_label(model_name: str, model_lookup: dict[str, dict[str, object]]) -> str:
    for label, model in model_lookup.items():
        if model["name"] == model_name:
            return label
    return model_name


def _find_relation_label_between(
    current_label: str,
    next_label: str,
    model_lookup: dict[str, dict[str, object]],
) -> str:
    current_model = model_lookup.get(current_label)
    next_model = model_lookup.get(next_label)
    if current_model:
        for relation in current_model["relations"]:
            if relation["related_model_label"] == next_label:
                return str(relation["field_name"])
    if next_model:
        for relation in next_model["relations"]:
            if relation["related_model_label"] == current_label:
                return str(relation["field_name"])
    return "related"


__all__ = [
    "BUSINESS_MODEL_METADATA",
    "BUSINESS_SCHEMA_FLOWS",
    "BUSINESS_SCHEMA_GROUPS",
    "_build_business_flows",
    "_build_business_groups",
    "_find_model_label",
    "_find_relation_label_between",
]
