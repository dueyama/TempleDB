from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.db import connections
from django.db.utils import OperationalError, ProgrammingError

# Keep model bindings initialized before source runtime when ImportsConfig.ready()
# imports this module to register Django system checks.
# isort: off
from . import canonical_population
from .models import LegacySource, SourceOperationLog
from . import source_runtime
# isort: on


def _imports_tables_ready() -> bool:
    connection = connections["default"]
    try:
        table_names = set(connection.introspection.table_names())
    except (OperationalError, ProgrammingError):
        return False
    required_tables = {
        LegacySource._meta.db_table,
        SourceOperationLog._meta.db_table,
    }
    return required_tables.issubset(table_names)


@register()
def operational_source_configuration_checks(app_configs, **kwargs):
    del app_configs, kwargs
    if getattr(settings, "TEMPLEDB_DEMO_MODE", False):
        return []
    if not _imports_tables_ready():
        return []
    warnings = []
    status = source_runtime.operational_source_status()
    if status.get("resolution_kind") == "db_unavailable":
        return []
    warning_message = (
        status.get("warning_message")
        or "通常運用 source の解決に registry bootstrap fallback が関与しています。"
    )
    if status.get("resolution_kind") in {
        "registry_bootstrap_required",
        "operational_source_unavailable",
    }:
        warnings.append(
            Warning(
                warning_message,
                hint="LegacySource.is_primary=True の source を整備してください。",
                id="imports.W001",
            )
        )
    elif status.get("has_bootstrap_warning"):
        warnings.append(
            Warning(
                warning_message,
                hint="LegacySource.is_primary の整備状況を確認してください。",
                id="imports.W002",
            )
        )
    warnings.extend(_primary_source_uniqueness_checks())
    warnings.extend(_legacy_source_path_sync_checks())
    warnings.extend(_canonical_population_checks())
    return warnings


def _canonical_population_checks() -> list[Error]:
    state = canonical_population.safe_canonical_population_state()
    if state is None:
        return []
    errors = []
    if len(state.batch_ids) > 1:
        labels = ", ".join(str(batch_id) for batch_id in sorted(state.batch_ids))
        errors.append(
            Error(
                f"Canonical business data spans multiple import batches: {labels}",
                hint=(
                    "通常業務では複数batchを表示境界として切り替えません。"
                    "取込を停止し、canonical dataの退役または明示的mergeを実施してください。"
                ),
                id="imports.E001",
            )
        )
    if state.missing_provenance_models:
        labels = ", ".join(state.missing_provenance_models)
        errors.append(
            Error(
                f"Canonical operational data is missing related_batch provenance: {labels}",
                hint=(
                    "由来batchを確認して related_batch を補完するまで、"
                    "通常業務画面へ公開しないでください。"
                ),
                id="imports.E002",
            )
        )
    if state.has_invalid_batch_status:
        errors.append(
            Error(
                "Canonical business data belongs to an import batch that has not succeeded.",
                hint=(
                    "data-bearing batch の状態を確認し、正当な取込完了を確認できる場合だけ "
                    "SUCCEEDED にしてください。"
                ),
                id="imports.E003",
            )
        )
    if state.has_running_import:
        errors.append(
            Error(
                "A canonical import is currently running; normal ledger access is paused.",
                hint=(
                    "取込が完了または失敗状態へ確定するまで通常入力を再開せず、"
                    "長時間RUNNINGのままなら取込logを確認してください。"
                ),
                id="imports.E004",
            )
        )
    return errors


def _primary_source_uniqueness_checks() -> list[Warning]:
    try:
        primary_ids = list(
            LegacySource.objects.filter(is_primary=True)
            .order_by("source_id")
            .values_list("source_id", flat=True)
        )
    except (OperationalError, ProgrammingError):
        return []
    if len(primary_ids) <= 1:
        return []
    labels = ", ".join(primary_ids[:5])
    if len(primary_ids) > 5:
        labels = f"{labels}, …"
    return [
        Warning(
            f"LegacySource.is_primary=True の source が複数あります: {labels}",
            hint=(
                "通常運用 source は1件だけ primary にしてください。"
                "履歴・比較用 source は is_primary=False に下げて provenance として残します。"
            ),
            id="imports.W004",
        )
    ]


def _legacy_source_path_sync_checks() -> list[Warning]:
    stale_sources: list[str] = []
    try:
        source_records = LegacySource.objects.order_by("source_id")
    except (OperationalError, ProgrammingError):
        return []
    for source in source_records:
        try:
            summary = source_runtime.source_summary(source.source_id)
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            continue
        resolved_path = Path(summary["resolved_path"])
        expected_file_path = str(resolved_path)
        expected_file_name = resolved_path.name
        if source.file_path == expected_file_path and source.file_name == expected_file_name:
            continue
        stale_sources.append(source.source_id)
    if not stale_sources:
        return []
    labels = ", ".join(stale_sources[:3])
    if len(stale_sources) > 3:
        labels = f"{labels}, …"
    return [
        Warning(
            f"LegacySource.file_path (legacy mirror) が runtime registry と不一致です: {labels}",
            hint=(
                "current source authority は registry / source_id 側です。"
                " mirror を同期するには python manage.py normalize_legacy_source_paths --execute を実行してください。"
            ),
            id="imports.W003",
        )
    ]
