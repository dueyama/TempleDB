from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config.platform_process import pid_is_alive
from config.runtime_paths import import_runs_root as runtime_import_runs_root


def _runtime_module():
    from . import pipeline_runtime

    return pipeline_runtime


def pipeline_status_root() -> Path:
    return runtime_import_runs_root()


def pipeline_status_path(source_id: str) -> Path:
    return pipeline_status_root() / f"{source_id}.json"


def _pipeline_stage_rows() -> list[dict]:
    runtime = _runtime_module()
    return [
        {
            "number": definition["number"],
            "key": definition["key"],
            "label": definition["label"],
            "status": "pending",
            "summary": "",
            "started_at": None,
            "finished_at": None,
            "command": "",
            "stdout_tail": [],
            "stderr_tail": [],
        }
        for definition in runtime.PIPELINE_STEP_DEFINITIONS
    ]


def initial_pipeline_status(
    source_id: str,
    source_path: Path,
    pid: int | None = None,
    actor: str = "",
) -> dict:
    runtime = _runtime_module()
    return {
        "source_id": source_id,
        "source_path": str(source_path),
        "actor": actor,
        "status": "starting",
        "pid": pid,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "current_stage_key": None,
        "current_stage_label": None,
        "summary": "Pipeline is starting.",
        "stages": _pipeline_stage_rows(),
        "latest_import": runtime.source_runtime.latest_import_batch_summary(source_id),
    }


def write_pipeline_status(source_id: str, payload: dict) -> None:
    path = pipeline_status_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_pipeline_status(source_id: str) -> dict | None:
    runtime = _runtime_module()
    path = pipeline_status_path(source_id)
    payload = runtime.source_runtime._json(path)
    if payload is None:
        return None
    payload["updated_at"] = runtime.source_runtime._timestamp(path)
    payload["running"] = _pipeline_process_running(payload)
    if payload.get("status") == "starting" and not payload["running"]:
        payload["status"] = "failed"
        payload["summary"] = "Pipeline start record was left behind, but no running process was found."
    return payload


def _pipeline_process_running(payload: dict | None) -> bool:
    if not payload or payload.get("status") not in {"starting", "running"}:
        return False
    pid = payload.get("pid")
    if not pid:
        return True
    try:
        return pid_is_alive(int(pid))
    except (ValueError, TypeError):
        return False
