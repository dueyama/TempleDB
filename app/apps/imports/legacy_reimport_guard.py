from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population
from .models import ImportBatch, LegacySource

LEGACY_REIMPORT_ACTIONS = frozenset(
    {
        "export",
        "import-households-persons",
        "profile",
        "raw-layer",
        "start-import-pipeline",
    }
)

_REGISTRY_ERRORS = (
    AssertionError,
    FileNotFoundError,
    KeyError,
    OSError,
    ValueError,
    json.JSONDecodeError,
)


@dataclass(frozen=True)
class LegacyReimportAuthorization:
    allowed: bool
    code: str
    message: str
    source_id: str = ""
    registry_source_id: str = ""
    source_path: Path | None = None
    registry_source_path: Path | None = None


class LegacyReimportBlocked(RuntimeError):
    pass


def _source_runtime_module():
    from . import source_runtime

    return source_runtime


def evaluate_legacy_reimport(
    requested_source_id: str | None = None,
) -> LegacyReimportAuthorization:
    """Fail closed unless one DB primary and the registry default agree."""

    requested_source_id = (requested_source_id or "").strip()
    try:
        primary_sources = list(
            LegacySource.objects.filter(is_primary=True)
            .order_by("source_id")
            .only("source_id", "file_path")
        )
    except (OperationalError, ProgrammingError):
        return LegacyReimportAuthorization(
            allowed=False,
            code="db_primary_unavailable",
            message="DB primary sourceを確認できないため、旧データの再取込を実行できません。",
        )

    if len(primary_sources) != 1:
        return LegacyReimportAuthorization(
            allowed=False,
            code="db_primary_not_unique",
            message=(
                "DB primary sourceが一意に確定していないため、旧データの再取込を実行できません。"
            ),
        )

    primary_source = primary_sources[0]
    primary_source_id = primary_source.source_id
    try:
        runtime = _source_runtime_module()
        registry_source_id = runtime.runtime_source_id()
        registry_source = runtime.resolve_source_entry(registry_source_id)
    except _REGISTRY_ERRORS:
        return LegacyReimportAuthorization(
            allowed=False,
            code="registry_source_unavailable",
            message=(
                "runtime source registryのdefault sourceを確認できないため、"
                "旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
        )

    raw_primary_path = (primary_source.file_path or "").strip()
    if not raw_primary_path:
        return LegacyReimportAuthorization(
            allowed=False,
            code="db_primary_path_unavailable",
            message=(
                "DB primary sourceの実体pathが未設定のため、旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
        )
    primary_path = Path(raw_primary_path)
    if not primary_path.is_absolute():
        primary_path = runtime.base_dir() / primary_path
    primary_path = primary_path.resolve(strict=False)
    registry_path = Path(registry_source["resolved_path"]).resolve(strict=False)

    if registry_source_id != primary_source_id:
        return LegacyReimportAuthorization(
            allowed=False,
            code="source_authority_mismatch",
            message=(
                "DB primary sourceとruntime registry defaultが一致しないため、"
                "旧データの再取込を拒否しました。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    if registry_path != primary_path:
        return LegacyReimportAuthorization(
            allowed=False,
            code="source_path_mismatch",
            message=(
                "DB primary sourceとruntime registry defaultの実体pathが一致しないため、"
                "旧データの再取込を拒否しました。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    if requested_source_id and requested_source_id != primary_source_id:
        return LegacyReimportAuthorization(
            allowed=False,
            code="requested_source_mismatch",
            message=(
                "指定sourceがDB primary sourceと一致しないため、旧データの再取込を拒否しました。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    if not primary_path.is_file():
        return LegacyReimportAuthorization(
            allowed=False,
            code="source_file_unavailable",
            message=(
                "確定した旧データsource fileを読み取れないため、旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    if not bool(getattr(settings, "TEMPLEDB_LEGACY_REIMPORT_ENABLED", False)):
        return LegacyReimportAuthorization(
            allowed=False,
            code="disabled",
            message=(
                "旧データの再取込は通常運用では無効です。"
                "明示的に許可した保守作業でだけ実行できます。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    try:
        import_running = ImportBatch.objects.filter(status=ImportBatch.Status.RUNNING).exists()
    except (OperationalError, ProgrammingError):
        return LegacyReimportAuthorization(
            allowed=False,
            code="canonical_state_unavailable",
            message=(
                "TempleDBの現行データ状態を確認できないため、旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )
    if import_running:
        return LegacyReimportAuthorization(
            allowed=False,
            code="import_already_running",
            message="実行中の取込があるため、旧データの再取込を開始できません。",
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    try:
        canonical_records_exist = canonical_population.canonical_business_records_exist()
    except canonical_population.CanonicalPopulationConflict:
        return LegacyReimportAuthorization(
            allowed=False,
            code="canonical_state_invalid",
            message=(
                "TempleDBの現行データの由来が不整合なため、"
                "旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )
    except (OperationalError, ProgrammingError):
        return LegacyReimportAuthorization(
            allowed=False,
            code="canonical_state_unavailable",
            message=(
                "TempleDBの現行データ状態を確認できないため、旧データの再取込を実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )
    if canonical_records_exist:
        return LegacyReimportAuthorization(
            allowed=False,
            code="canonical_data_present",
            message=(
                "TempleDBに現行の業務データがあるため、"
                "新しいbatchを追加する旧データ再取込は実行できません。"
            ),
            source_id=primary_source_id,
            registry_source_id=registry_source_id,
            source_path=primary_path,
            registry_source_path=registry_path,
        )

    return LegacyReimportAuthorization(
        allowed=True,
        code="allowed",
        message="旧データの再取込が明示的に許可されています。",
        source_id=primary_source_id,
        registry_source_id=registry_source_id,
        source_path=primary_path,
        registry_source_path=registry_path,
    )


def require_legacy_reimport(
    requested_source_id: str | None = None,
    *,
    resolved_source_path: str | Path | None = None,
) -> LegacyReimportAuthorization:
    authorization = evaluate_legacy_reimport(requested_source_id)
    if not authorization.allowed:
        raise LegacyReimportBlocked(authorization.message)
    if resolved_source_path is not None:
        actual_path = Path(resolved_source_path).resolve(strict=False)
        if actual_path != authorization.source_path:
            raise LegacyReimportBlocked(
                "Source authority changed after legacy reimport authorization; import refused."
            )
    return authorization


__all__ = [
    "LEGACY_REIMPORT_ACTIONS",
    "LegacyReimportAuthorization",
    "LegacyReimportBlocked",
    "evaluate_legacy_reimport",
    "require_legacy_reimport",
]
