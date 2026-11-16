from __future__ import annotations

import csv
import json

from .legacy_reimport_guard import evaluate_legacy_reimport


def _runtime_module():
    from . import pipeline_runtime

    return pipeline_runtime


def build_console_context(
    source_id: str | None = None,
    *,
    operator_is_superuser: bool = False,
) -> dict:
    del source_id
    runtime = _runtime_module()
    source = runtime.source_runtime.operational_source_status()
    if not source.get("source_id"):
        source = runtime.source_runtime.resolve_source_entry()
    active_source_id = source["source_id"]
    reimport_authorization = evaluate_legacy_reimport(active_source_id)
    latest_export = runtime.source_runtime.latest_export_snapshot(active_source_id)
    latest_prepared = runtime.source_runtime.latest_prepared_snapshot(active_source_id)
    analysis = runtime.source_runtime.analysis_summary(active_source_id)
    latest_import = runtime.source_runtime.latest_import_batch_summary(active_source_id)
    current_import_batch = runtime.source_runtime.latest_succeeded_import_batch(active_source_id)
    current_import = (
        runtime.source_runtime.import_batch_summary(current_import_batch)
        if current_import_batch
        else None
    )
    pipeline_status = runtime.read_pipeline_status(active_source_id)
    export_current = latest_export is not None
    profile_current = (
        latest_export is not None
        and analysis["has_outputs"]
        and analysis["snapshot_id"] == latest_export["snapshot_id"]
    )
    raw_current = (
        latest_export is not None
        and latest_prepared is not None
        and latest_prepared["snapshot_id"] == latest_export["snapshot_id"]
    )
    import_current = (
        latest_export is not None
        and latest_import is not None
        and latest_import["status"] == runtime.ImportBatch.Status.SUCCEEDED
        and latest_import["prepared_snapshot_id"] == latest_export["snapshot_id"]
    )

    pipeline_steps = []
    for definition in runtime.PIPELINE_STEP_DEFINITIONS:
        if definition["key"] == "export":
            current = export_current
            detail = (
                f"{latest_export['snapshot_id']} ({latest_export['table_count']} tables)"
                if latest_export
                else "まだ export snapshot はありません。"
            )
            status = "Current" if current else "Pending"
        elif definition["key"] == "profile":
            current = profile_current
            detail = (
                f"analysis snapshot: {analysis['snapshot_id']}"
                if analysis["snapshot_id"]
                else "analysis_outputs がまだありません。"
            )
            status = "Current" if current else ("Waiting" if not export_current else "Pending")
        elif definition["key"] == "raw-layer":
            current = raw_current
            detail = (
                f"prepared snapshot: {latest_prepared['snapshot_id']}"
                if latest_prepared
                else "prepared_exports がまだありません。"
            )
            status = "Current" if current else ("Waiting" if not export_current else "Pending")
        else:
            current = import_current
            detail = (
                "batch "
                f"{latest_import['batch_uuid'][:8]} / "
                f"households {latest_import['households_imported']} / "
                f"persons {latest_import['persons_imported']} / "
                f"services {latest_import['service_schedules_imported']} / "
                f"issues {latest_import['issues_count']}"
                if latest_import
                else "まだ DB import は実行されていません。"
            )
            status = "Current" if current else ("Waiting" if not raw_current else "Pending")

        live_stage = None
        if pipeline_status:
            live_stage = next(
                (row for row in pipeline_status.get("stages", []) if row["key"] == definition["key"]),
                None,
            )
            if live_stage and live_stage.get("status") in {"running", "failed", "succeeded"}:
                status = live_stage["status"].capitalize()
                if live_stage.get("summary"):
                    detail = live_stage["summary"]

        pipeline_steps.append(
            {
                "number": definition["number"],
                "key": definition["key"],
                "label": definition["label"],
                "description": definition["description"],
                "outputs": definition["outputs"],
                "current": current,
                "status": status,
                "detail": detail,
                "live_stage": live_stage,
            }
        )

    comparison = build_comparison_summary(latest_export, latest_prepared)
    return {
        "selected_source_id": active_source_id,
        "default_source_id": runtime.source_runtime.runtime_source_id(),
        "source": runtime.source_runtime.source_summary(active_source_id),
        "latest_export": latest_export,
        "recent_exports": runtime.source_runtime.recent_export_snapshots(active_source_id),
        "latest_prepared": latest_prepared,
        "latest_import": latest_import,
        "current_import": current_import,
        "recent_import_batches": runtime.source_runtime.recent_import_batches(active_source_id),
        "analysis": analysis,
        "pipeline_steps": pipeline_steps,
        "pipeline_status": pipeline_status,
        "pipeline_running": bool(pipeline_status and pipeline_status.get("running")),
        "primary_action_enabled": (
            operator_is_superuser
            and reimport_authorization.allowed
            and source["resolved_path"].exists()
            and not (pipeline_status and pipeline_status.get("running"))
        ),
        "legacy_reimport_authorization": reimport_authorization,
        "legacy_reimport_operator_is_superuser": operator_is_superuser,
        "comparison": comparison,
        "recent_source_operations": runtime.source_runtime.recent_source_operation_entries(
            active_source_id,
            limit=8,
        ),
    }


def build_comparison_summary(latest_export: dict | None, latest_prepared: dict | None) -> dict:
    runtime = _runtime_module()
    if latest_export is None or latest_prepared is None:
        return {
            "available": False,
            "reason": "Step 1 の export と Step 3 の raw layer が揃ってから比較できます。",
        }
    if latest_export["snapshot_id"] != latest_prepared["snapshot_id"]:
        return {
            "available": False,
            "reason": (
                "latest export と latest raw layer の snapshot_id が一致していません。"
                "Step 3 を再実行してください。"
            ),
        }

    raw_manifest = runtime.source_runtime._json(latest_prepared["raw_manifest_path"]) or {}
    raw_tables = {row["table_name"]: row for row in raw_manifest.get("tables", [])}
    rows = []
    for table in latest_export["manifest"].get("tables", []):
        raw_row = raw_tables.get(table["table_name"])
        raw_count = raw_row["row_count"] if raw_row else None
        rows.append(
            {
                "table_name": table["table_name"],
                "export_row_count": table["row_count"],
                "raw_row_count": raw_count,
                "match": raw_count == table["row_count"],
            }
        )
    rows.sort(key=lambda row: (row["match"], row["table_name"]))

    selected_table = rows[0]["table_name"] if rows else None
    preview = build_row_preview(latest_export, latest_prepared, selected_table, 1) if selected_table else None
    return {
        "available": True,
        "snapshot_id": latest_export["snapshot_id"],
        "total_tables": len(rows),
        "matching_tables": sum(1 for row in rows if row["match"]),
        "mismatched_tables": sum(1 for row in rows if not row["match"]),
        "rows": rows[:12],
        "preview": preview,
    }


def build_row_preview(
    latest_export: dict,
    latest_prepared: dict,
    table_name: str,
    row_number: int,
) -> dict | None:
    runtime = _runtime_module()
    export_manifest = latest_export["manifest"]
    export_table = next(
        (row for row in export_manifest.get("tables", []) if row["table_name"] == table_name),
        None,
    )
    raw_manifest = runtime.source_runtime._json(latest_prepared["raw_manifest_path"]) or {}
    raw_table = next(
        (row for row in raw_manifest.get("tables", []) if row["table_name"] == table_name),
        None,
    )
    if export_table is None or raw_table is None:
        return None

    export_csv = latest_export["snapshot_dir"] / export_table["csv_file"]
    raw_jsonl = latest_prepared["prepared_dir"] / raw_table["jsonl_file"]

    before_row = None
    with export_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index == row_number:
                before_row = row
                break

    after_row = None
    with raw_jsonl.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            if index == row_number:
                after_row = json.loads(line)
                break

    if before_row is None or after_row is None:
        return None

    comparisons = []
    for column in before_row.keys():
        before_value = before_row[column]
        after_value = after_row["values"].get(column)
        comparisons.append(
            {
                "column": column,
                "before": before_value,
                "after": "null" if after_value is None else str(after_value),
            }
        )

    return {
        "table_name": table_name,
        "row_number": row_number,
        "comparisons": comparisons[:24],
    }
