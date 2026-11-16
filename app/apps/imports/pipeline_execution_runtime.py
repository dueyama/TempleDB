from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings

from .legacy_reimport_guard import LEGACY_REIMPORT_ACTIONS, evaluate_legacy_reimport


def _runtime_module():
    from . import pipeline_runtime

    return pipeline_runtime


@dataclass
class CommandResult:
    action: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    stages: list[CommandResult] | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def summary(self) -> str:
        if self.stages:
            if self.ok:
                return " -> ".join(f"{stage.action}: {stage.summary}" for stage in self.stages)
            failed_stage = next((stage for stage in self.stages if not stage.ok), self.stages[-1])
            return f"{failed_stage.action}: {failed_stage.summary}"
        output = (self.stdout or self.stderr).strip()
        if not output:
            return "No output"
        return output.splitlines()[-1][:280]


def _python_executable() -> str:
    return sys.executable or "python"


def action_commands(source: dict) -> dict[str, list[str]]:
    runtime = _runtime_module()
    python_executable = _python_executable()
    active_source_id = source["source_id"]
    return {
        "export": [
            python_executable,
            "scripts/export_mdb_snapshot.py",
            "--source",
            str(source["resolved_path"]),
            "--source-id",
            active_source_id,
            "--output-root",
            str(runtime.source_runtime.runtime_exports_root()),
        ],
        "profile": [
            python_executable,
            "scripts/profile_export_snapshot.py",
            "--source-id",
            active_source_id,
            "--output-root",
            str(runtime.source_runtime.runtime_exports_root()),
            "--analysis-dir",
            str(runtime.source_runtime.runtime_analysis_root()),
        ],
        "raw-layer": [
            python_executable,
            "scripts/prepare_raw_layer.py",
            "--source-id",
            active_source_id,
            "--output-root",
            str(runtime.source_runtime.runtime_exports_root()),
            "--prepared-root",
            str(runtime.source_runtime.runtime_prepared_root()),
            "--force",
        ],
        "import-households-persons": [
            python_executable,
            "manage.py",
            "import_households_persons",
            "--source-id",
            active_source_id,
        ],
    }


def _run_command(action: str, command: list[str]) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=Path(settings.BASE_DIR),
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        action=action,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def execute_import_pipeline(source_id: str | None = None, *, actor: str = "") -> dict:
    runtime = _runtime_module()
    authorization = evaluate_legacy_reimport(source_id)
    if not authorization.allowed:
        return {
            "status": "blocked",
            "summary": authorization.message,
            "source_id": authorization.source_id,
        }
    source_id = authorization.source_id
    source = {
        "source_id": source_id,
        "resolved_path": authorization.source_path,
    }
    active_source_id = source["source_id"]
    commands = action_commands(source)
    before_status = runtime.read_pipeline_status(active_source_id) or {}
    payload = runtime.initial_pipeline_status(
        source_id=active_source_id,
        source_path=source["resolved_path"],
        pid=os.getpid(),
        actor=actor,
    )
    payload["status"] = "running"
    runtime.write_pipeline_status(active_source_id, payload)
    runtime.source_runtime.log_source_operation(
        source_id=active_source_id,
        operation_kind=runtime.SourceOperationLog.OperationKind.IMPORT_PIPELINE_STARTED,
        before_payload=before_status,
        after_payload=payload,
        editor_label=actor,
    )

    for index, definition in enumerate(runtime.PIPELINE_STEP_DEFINITIONS):
        stage = payload["stages"][index]
        stage["status"] = "running"
        stage["started_at"] = datetime.now().isoformat(timespec="seconds")
        stage["command"] = " ".join(commands[definition["key"]])
        payload["current_stage_key"] = definition["key"]
        payload["current_stage_label"] = definition["label"]
        payload["summary"] = f"{definition['label']} を実行中です。"
        runtime.write_pipeline_status(active_source_id, payload)

        result = _run_command(definition["key"], commands[definition["key"]])
        stage["finished_at"] = datetime.now().isoformat(timespec="seconds")
        stage["summary"] = result.summary
        stage["stdout_tail"] = result.stdout.strip().splitlines()[-10:]
        stage["stderr_tail"] = result.stderr.strip().splitlines()[-10:]
        if result.ok:
            stage["status"] = "succeeded"
            payload["summary"] = f"{definition['label']} が完了しました。"
        else:
            stage["status"] = "failed"
            payload["status"] = "failed"
            payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
            payload["summary"] = f"{definition['label']} で失敗しました。"
            payload["latest_import"] = runtime.source_runtime.latest_import_batch_summary(active_source_id)
            runtime.write_pipeline_status(active_source_id, payload)
            latest_batch = runtime.source_runtime.latest_import_batch(active_source_id)
            runtime.source_runtime.log_source_operation(
                source_id=active_source_id,
                operation_kind=runtime.SourceOperationLog.OperationKind.IMPORT_PIPELINE_FAILED,
                target_batch=latest_batch,
                before_payload=before_status,
                after_payload=payload,
                editor_label=actor,
            )
            return payload

    payload["status"] = "succeeded"
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["current_stage_key"] = None
    payload["current_stage_label"] = None
    payload["summary"] = "現在の source からの再取込が完了しました。"
    payload["latest_import"] = runtime.source_runtime.latest_import_batch_summary(active_source_id)
    runtime.write_pipeline_status(active_source_id, payload)
    latest_batch = runtime.source_runtime.latest_import_batch(active_source_id)
    runtime.source_runtime.log_source_operation(
        source_id=active_source_id,
        operation_kind=runtime.SourceOperationLog.OperationKind.IMPORT_PIPELINE_SUCCEEDED,
        target_batch=latest_batch,
        before_payload=before_status,
        after_payload=payload,
        editor_label=actor,
    )
    return payload


def run_action(action: str, source_id: str | None = None, *, actor: str = "") -> CommandResult:
    runtime = _runtime_module()
    source = None
    if action in LEGACY_REIMPORT_ACTIONS:
        authorization = evaluate_legacy_reimport(source_id)
        if not authorization.allowed:
            return CommandResult(
                action=action,
                command=[],
                returncode=1,
                stdout="",
                stderr=authorization.message,
            )
        source_id = authorization.source_id
        source = {
            "source_id": source_id,
            "resolved_path": authorization.source_path,
        }
    if source is None:
        source = runtime.source_runtime.resolve_source_entry(source_id)
    active_source_id = source["source_id"]
    if action == "start-import-pipeline":
        status = runtime.read_pipeline_status(active_source_id)
        if status and status.get("running"):
            return CommandResult(
                action=action,
                command=[],
                returncode=0,
                stdout="A pipeline is already running for this source.",
                stderr="",
            )

        command = [
            _python_executable(),
            "manage.py",
            "run_import_pipeline",
            "--source-id",
            active_source_id,
        ]
        if actor:
            command.extend(["--actor", actor])
        process = subprocess.Popen(
            command,
            cwd=Path(settings.BASE_DIR),
            text=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        payload = runtime.initial_pipeline_status(
            source_id=active_source_id,
            source_path=source["resolved_path"],
            pid=process.pid,
            actor=actor,
        )
        payload["summary"] = "Pipeline process was started from the migration console."
        runtime.write_pipeline_status(active_source_id, payload)
        return CommandResult(
            action=action,
            command=command,
            returncode=0,
            stdout=f"Started latest import pipeline (pid={process.pid}).",
            stderr="",
        )
    if action == "normalize-kana-preview":
        summary = runtime.kana_cleanup_runtime.normalize_runtime_kana_storage(
            source_id=active_source_id,
            dry_run=True,
        )
        return CommandResult(
            action=action,
            command=[
                _python_executable(),
                "manage.py",
                "normalize_kana_storage",
            ],
            returncode=0,
            stdout=runtime.kana_cleanup_runtime._format_kana_normalization_summary(summary),
            stderr="",
        )
    if action == "normalize-kana-execute":
        summary = runtime.kana_cleanup_runtime.normalize_runtime_kana_storage(
            source_id=active_source_id,
            dry_run=False,
        )
        return CommandResult(
            action=action,
            command=[
                _python_executable(),
                "manage.py",
                "normalize_kana_storage",
                "--execute",
            ],
            returncode=0,
            stdout=runtime.kana_cleanup_runtime._format_kana_normalization_summary(summary),
            stderr="",
        )
    if action == "cleanup-manual-candidates-preview":
        summary = runtime.kana_cleanup_runtime.cleanup_runtime_manual_candidate_schedules(
            source_id=active_source_id,
            dry_run=True,
            actor=actor,
        )
        return CommandResult(
            action=action,
            command=[
                _python_executable(),
                "manage.py",
                "cleanup_manual_candidates",
            ],
            returncode=0,
            stdout=runtime.kana_cleanup_runtime._format_manual_candidate_cleanup_summary(summary),
            stderr="",
        )
    if action == "cleanup-manual-candidates-execute":
        summary = runtime.kana_cleanup_runtime.cleanup_runtime_manual_candidate_schedules(
            source_id=active_source_id,
            dry_run=False,
            actor=actor,
        )
        return CommandResult(
            action=action,
            command=[
                _python_executable(),
                "manage.py",
                "cleanup_manual_candidates",
                "--execute",
            ],
            returncode=0,
            stdout=runtime.kana_cleanup_runtime._format_manual_candidate_cleanup_summary(summary),
            stderr="",
        )

    commands = action_commands(source)
    if action not in commands:
        raise ValueError(f"Unknown action: {action}")
    return _run_command(action, commands[action])
