from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping

RESTORE_CONTRACT_KEY = "templedb_restore_contract"
RESTORE_CONTRACT_VERSION = 1
SUPPORTED_DATABASE_ENGINES = frozenset({"postgresql", "sqlite"})
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class BackupRestoreContractError(ValueError):
    """Raised when a restored database does not satisfy the pack contract."""


def build_restore_contract(
    *,
    database_engine: str,
    database_version: str,
    database_version_scope: str,
    installation_id: object,
    runtime_kind: object,
    migration_rows: Iterable[tuple[object, object]],
) -> dict[str, object]:
    identity = _normalized_runtime_identity(
        installation_id=installation_id,
        runtime_kind=runtime_kind,
    )
    migrations = build_migration_inventory(migration_rows)
    return {
        "contract_version": RESTORE_CONTRACT_VERSION,
        "database_engine": _normalized_database_engine(database_engine),
        "database_version": _nonempty_text(database_version, field="database_version"),
        "database_version_scope": _nonempty_text(
            database_version_scope,
            field="database_version_scope",
        ),
        "runtime_identity": identity,
        "applied_migrations": migrations,
    }


def build_migration_inventory(
    migration_rows: Iterable[tuple[object, object]],
) -> dict[str, object]:
    normalized_rows = sorted(
        {
            (
                _nonempty_text(app_label, field="migration app"),
                _nonempty_text(migration_name, field="migration name"),
            )
            for app_label, migration_name in migration_rows
        }
    )
    encoded = json.dumps(
        normalized_rows,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return {
        "count": len(normalized_rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def validated_restore_contract(
    summary: object,
    *,
    expected_database_engine: str | None = None,
) -> dict[str, object]:
    if not isinstance(summary, Mapping):
        raise BackupRestoreContractError("テスト復元結果の形式が不正です。")
    raw_contract = summary.get(RESTORE_CONTRACT_KEY)
    if not isinstance(raw_contract, Mapping):
        raise BackupRestoreContractError(
            "テスト復元結果に運用パック用の復元契約がありません。"
        )
    expected_fields = {
        "contract_version",
        "database_engine",
        "database_version",
        "database_version_scope",
        "runtime_identity",
        "applied_migrations",
    }
    if set(raw_contract) != expected_fields:
        raise BackupRestoreContractError("テスト復元契約の項目が不正です。")
    if raw_contract.get("contract_version") != RESTORE_CONTRACT_VERSION:
        raise BackupRestoreContractError("テスト復元契約の版が未対応です。")

    database_engine = _normalized_database_engine(raw_contract.get("database_engine"))
    if (
        expected_database_engine is not None
        and database_engine != _normalized_database_engine(expected_database_engine)
    ):
        raise BackupRestoreContractError("テスト復元契約のDB種別が一致しません。")

    raw_identity = raw_contract.get("runtime_identity")
    if not isinstance(raw_identity, Mapping) or set(raw_identity) != {
        "installation_id",
        "runtime_kind",
    }:
        raise BackupRestoreContractError("テスト復元契約のDB識別情報が不正です。")
    identity = _normalized_runtime_identity(
        installation_id=raw_identity.get("installation_id"),
        runtime_kind=raw_identity.get("runtime_kind"),
    )

    raw_migrations = raw_contract.get("applied_migrations")
    if not isinstance(raw_migrations, Mapping) or set(raw_migrations) != {
        "count",
        "sha256",
    }:
        raise BackupRestoreContractError("テスト復元契約のmigration情報が不正です。")
    migration_count = raw_migrations.get("count")
    migration_sha256 = str(raw_migrations.get("sha256") or "")
    if (
        isinstance(migration_count, bool)
        or not isinstance(migration_count, int)
        or migration_count < 0
        or not _SHA256_RE.fullmatch(migration_sha256)
    ):
        raise BackupRestoreContractError("テスト復元契約のmigration情報が不正です。")

    return {
        "contract_version": RESTORE_CONTRACT_VERSION,
        "database_engine": database_engine,
        "database_version": _nonempty_text(
            raw_contract.get("database_version"),
            field="database_version",
        ),
        "database_version_scope": _nonempty_text(
            raw_contract.get("database_version_scope"),
            field="database_version_scope",
        ),
        "runtime_identity": identity,
        "applied_migrations": {
            "count": migration_count,
            "sha256": migration_sha256,
        },
    }


def canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_database_engine(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if value not in SUPPORTED_DATABASE_ENGINES:
        raise BackupRestoreContractError("テスト復元契約のDB種別が不正です。")
    return value


def _normalized_runtime_identity(
    *,
    installation_id: object,
    runtime_kind: object,
) -> dict[str, str]:
    try:
        parsed_installation_id = uuid.UUID(str(installation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise BackupRestoreContractError("テスト復元契約のDB識別子が不正です。") from exc
    if parsed_installation_id.int == 0:
        raise BackupRestoreContractError("テスト復元契約のDB識別子が不正です。")
    normalized_runtime_kind = str(runtime_kind or "").strip()
    if normalized_runtime_kind != "product":
        raise BackupRestoreContractError("テスト復元契約は製品DBではありません。")
    return {
        "installation_id": str(parsed_installation_id),
        "runtime_kind": normalized_runtime_kind,
    }


def _nonempty_text(raw_value: object, *, field: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise BackupRestoreContractError(f"{field} が空です。")
    return value


__all__ = [
    "BackupRestoreContractError",
    "RESTORE_CONTRACT_KEY",
    "RESTORE_CONTRACT_VERSION",
    "build_migration_inventory",
    "build_restore_contract",
    "canonical_json_sha256",
    "validated_restore_contract",
]
