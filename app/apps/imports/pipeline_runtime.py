from __future__ import annotations

# Owner modules resolve these dependencies through the facade at call time.
from . import (
    kana_cleanup_runtime as kana_cleanup_runtime,
)
from . import (
    pipeline_console_runtime,
    pipeline_execution_runtime,
    pipeline_status_runtime,
)
from . import (
    source_runtime as source_runtime,
)
from .models import ImportBatch as ImportBatch
from .models import SourceOperationLog as SourceOperationLog

PIPELINE_STEP_DEFINITIONS = [
    {
        "number": 1,
        "key": "export",
        "label": "Export Snapshot",
        "description": "Access MDB から UTF-8 CSV / schema / log を作成します。",
        "outputs": "data/generated/legacy_exports/<source_id>/<snapshot_id>/",
    },
    {
        "number": 2,
        "key": "profile",
        "label": "Profile Snapshot",
        "description": "latest export を集計して table summary / column profiles を更新します。",
        "outputs": "data/generated/analysis_outputs/<source_id>/schema_report.md ほか",
    },
    {
        "number": 3,
        "key": "raw-layer",
        "label": "Prepare Raw Layer",
        "description": "latest export を provenance 付き JSONL に変換します。",
        "outputs": "data/generated/prepared_exports/<source_id>/<snapshot_id>/raw_jsonl/",
    },
    {
        "number": 4,
        "key": "import-households-persons",
        "label": "Import Households / Persons / Services",
        "description": (
            "raw JSONL から households / persons / deceased profiles / service schedules "
            "を canonical DB へ取り込みます。"
        ),
        "outputs": "canonical DB import tables",
    },
]

CommandResult = pipeline_execution_runtime.CommandResult
pipeline_status_root = pipeline_status_runtime.pipeline_status_root
pipeline_status_path = pipeline_status_runtime.pipeline_status_path
_pipeline_stage_rows = pipeline_status_runtime._pipeline_stage_rows
initial_pipeline_status = pipeline_status_runtime.initial_pipeline_status
write_pipeline_status = pipeline_status_runtime.write_pipeline_status
read_pipeline_status = pipeline_status_runtime.read_pipeline_status
_pipeline_process_running = pipeline_status_runtime._pipeline_process_running
_python_executable = pipeline_execution_runtime._python_executable
action_commands = pipeline_execution_runtime.action_commands
_run_command = pipeline_execution_runtime._run_command
execute_import_pipeline = pipeline_execution_runtime.execute_import_pipeline
build_console_context = pipeline_console_runtime.build_console_context
run_action = pipeline_execution_runtime.run_action
build_comparison_summary = pipeline_console_runtime.build_comparison_summary
build_row_preview = pipeline_console_runtime.build_row_preview
