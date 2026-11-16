from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from django.conf import settings
from django.db import connection as default_database_connection

from . import (
    backup_restore_contract,
    database_transfer_postgresql,
    runtime_role,
    tenant_operations_pack_apply,
)

ACTIVATION_RECEIPT_NAME = "tenant-pack-activation.json"
ACTIVATION_PENDING_NAME = ".tenant-pack-activation.pending"
DEACTIVATION_RECEIPT_NAME = "tenant-pack-deactivation.json"
DEACTIVATION_PENDING_NAME = ".tenant-pack-deactivation.pending"
ACTIVATION_RECEIPT_VERSION = 1
_MAX_CONTROL_FILE_SIZE = 8 * 1024 * 1024
_GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_MATPLOTLIB_FONT_CACHE_PATTERN = re.compile(
    r"fontlist-v[0-9]+(?:\.[0-9]+)*\.json"
)
_IMMUTABLE_BASELINE_CATEGORIES = frozenset(
    {"runtime_env_sentinel", "tenant_policy", "source_registry"}
)
_MUTABLE_POSTAL_SCAN_ROOT = PurePosixPath(
    "data/private/auxiliary/annual_membership_fee_postal_scans"
)
_ACTIVATED_BACKUP_CONTROL_FILES = frozenset(
    {
        "data/runtime/database_backup.lock",
        "data/runtime/database_backup.lock.guard",
        "data/runtime/database_backup.lock.active.guard",
    }
)
_ACTIVATED_GOOGLE_SYNC_LOCK_ROOT = "data/runtime/google_calendar_sync_locks"
_GOOGLE_SYNC_LOCK_NAME = re.compile(r"[0-9a-f]{64}\.lock")


class TenantOperationsCandidateActivationError(RuntimeError):
    """Raised when a frozen product candidate cannot be activated safely."""


@dataclass(frozen=True)
class TenantOperationsCandidateVerificationResult:
    candidate_root: Path
    database_name: str
    database_oid: int
    archive_sha256: str
    platform_commit: str
    runtime_platform_commit: str
    installation_id: str
    apply_receipt_sha256: str
    mapping_file_count: int
    connections_allowed: bool
    activated: bool


def verify_tenant_operations_candidate(
    *,
    candidate_tenant_root: str | Path,
    expected_git_commit: str,
    expected_runtime_git_commit: str | None = None,
    expected_archive_sha256: str,
    expected_installation_id: str,
    expected_database_name: str,
    require_activated: bool,
    platform_root: str | Path | None = None,
    expected_candidate_owner_uid: int | None = None,
    _allow_activation_pending: bool = False,
) -> TenantOperationsCandidateVerificationResult:
    _require_staging_role()
    candidate_owner_uid = _validated_candidate_owner_uid(
        expected_candidate_owner_uid
    )
    candidate_root = _validated_candidate_root(
        candidate_tenant_root,
        expected_owner_uid=candidate_owner_uid,
    )
    platform_commit = _validated_git_commit(expected_git_commit)
    runtime_platform_commit = _validated_git_commit(
        expected_runtime_git_commit or platform_commit
    )
    archive_sha256 = _validated_sha256(
        expected_archive_sha256,
        label="運用pack SHA256",
    )
    installation_id = _validated_installation_id(expected_installation_id)
    database_name = _validated_database_name(expected_database_name)
    resolved_platform_root = Path(
        platform_root if platform_root is not None else settings.BASE_DIR
    ).expanduser()
    tenant_operations_pack_apply._assert_platform_commit(
        resolved_platform_root.resolve(strict=True),
        expected_git_commit=runtime_platform_commit,
    )

    apply_path = candidate_root / tenant_operations_pack_apply.APPLY_RECEIPT_NAME
    marker_path = (
        candidate_root / tenant_operations_pack_apply.APPLY_COMPLETION_MARKER_NAME
    )
    activation_path = candidate_root / ACTIVATION_RECEIPT_NAME
    pending_path = candidate_root / ACTIVATION_PENDING_NAME
    deactivation_path = candidate_root / DEACTIVATION_RECEIPT_NAME
    deactivation_pending_path = candidate_root / DEACTIVATION_PENDING_NAME
    activation_pending_exists = pending_path.exists() or pending_path.is_symlink()
    deactivation_pending_exists = (
        deactivation_pending_path.exists() or deactivation_pending_path.is_symlink()
    )
    if (
        deactivation_pending_exists
        or (activation_pending_exists and not (_allow_activation_pending and require_activated))
        or (_allow_activation_pending and not activation_pending_exists)
    ):
        raise TenantOperationsCandidateActivationError(
            "candidateに未完了のactivation/deactivation記録があります。"
            "DB状態を個別確認してください。"
        )
    apply_bytes, apply_receipt = _read_private_json(
        apply_path,
        expected_owner_uid=candidate_owner_uid,
    )
    _marker_bytes, marker = _read_private_json(
        marker_path,
        expected_owner_uid=candidate_owner_uid,
    )
    apply_sha256 = hashlib.sha256(apply_bytes).hexdigest()
    database = _validated_apply_receipt(
        apply_receipt,
        marker=marker,
        apply_sha256=apply_sha256,
        candidate_root=candidate_root,
        expected_git_commit=platform_commit,
        expected_archive_sha256=archive_sha256,
        expected_installation_id=installation_id,
        expected_database_name=database_name,
    )
    _validated_expected_candidate_contract(
        apply_receipt,
        expected_installation_id=installation_id,
    )
    database_oid = int(database["oid"])
    token_sha256 = str(database["ownership_token_sha256"])

    if require_activated:
        if deactivation_path.exists() or deactivation_path.is_symlink():
            raise TenantOperationsCandidateActivationError(
                "candidateはdeactivation済みです。serviceを起動できません。"
            )
        _activation_bytes, activation = _read_private_json(
            activation_path,
            expected_owner_uid=candidate_owner_uid,
        )
        immutable_rows = _validated_activation_receipt(
            activation,
            apply_sha256=apply_sha256,
            candidate_root=candidate_root,
            expected_git_commit=platform_commit,
            expected_archive_sha256=archive_sha256,
            expected_installation_id=installation_id,
            expected_database_name=database_name,
            expected_database_oid=database_oid,
            expected_ownership_token_sha256=token_sha256,
        )
        _assert_candidate_tree_safe(
            candidate_root,
            expected_owner_uid=candidate_owner_uid,
        )
        _verify_immutable_baseline(
            candidate_root,
            immutable_rows,
            expected_owner_uid=candidate_owner_uid,
        )
        expected_connections_allowed = True
        activated = True
    else:
        if activation_path.exists() or activation_path.is_symlink():
            raise TenantOperationsCandidateActivationError(
                "candidateは既にactivation済みです。起動時verifyを使用してください。"
            )
        mapping_rows = _mapped_candidate_rows(
            candidate_root,
            exact=True,
            expected_owner_uid=candidate_owner_uid,
        )
        _assert_apply_mapping(apply_receipt, mapping_rows)
        expected_connections_allowed = False
        activated = False

    try:
        if require_activated:
            state = database_transfer_postgresql.inspect_connected_postgresql_candidate(
                database_name=database_name,
                expected_database_oid=database_oid,
                expected_ownership_token_sha256=token_sha256,
            )
            _assert_live_candidate_contract(
                apply_receipt,
                expected_installation_id=installation_id,
            )
        else:
            state = database_transfer_postgresql.inspect_postgresql_candidate(
                database_name=database_name,
                expected_database_oid=database_oid,
                expected_ownership_token_sha256=token_sha256,
                expected_connections_allowed=expected_connections_allowed,
            )
    except database_transfer_postgresql.DatabaseTransferError as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate PostgreSQL DBをreceiptどおりに確認できません。"
        ) from exc
    return TenantOperationsCandidateVerificationResult(
        candidate_root=candidate_root,
        database_name=database_name,
        database_oid=database_oid,
        archive_sha256=archive_sha256,
        platform_commit=platform_commit,
        runtime_platform_commit=runtime_platform_commit,
        installation_id=installation_id,
        apply_receipt_sha256=apply_sha256,
        mapping_file_count=int(apply_receipt["candidate_mapping"]["file_count"]),
        connections_allowed=state.connections_allowed,
        activated=activated,
    )


def activate_tenant_operations_candidate(
    *,
    candidate_tenant_root: str | Path,
    confirm_candidate_tenant_root: str,
    expected_git_commit: str,
    expected_archive_sha256: str,
    expected_installation_id: str,
    expected_database_name: str,
    confirm_database_name: str,
    platform_root: str | Path | None = None,
    expected_candidate_owner_uid: int | None = None,
) -> TenantOperationsCandidateVerificationResult:
    candidate_owner_uid = _validated_candidate_owner_uid(
        expected_candidate_owner_uid
    )
    candidate_root = _validated_candidate_root(
        candidate_tenant_root,
        expected_owner_uid=candidate_owner_uid,
    )
    if confirm_candidate_tenant_root.strip() != str(candidate_root):
        raise TenantOperationsCandidateActivationError(
            "candidate rootの確認値が一致しません。"
        )
    database_name = _validated_database_name(expected_database_name)
    if confirm_database_name.strip() != database_name:
        raise TenantOperationsCandidateActivationError(
            "candidate DB名の確認値が一致しません。"
        )
    frozen = verify_tenant_operations_candidate(
        candidate_tenant_root=candidate_root,
        expected_git_commit=expected_git_commit,
        expected_archive_sha256=expected_archive_sha256,
        expected_installation_id=expected_installation_id,
        expected_database_name=database_name,
        require_activated=False,
        platform_root=platform_root,
        expected_candidate_owner_uid=candidate_owner_uid,
    )
    apply_bytes, apply_receipt = _read_private_json(
        candidate_root / tenant_operations_pack_apply.APPLY_RECEIPT_NAME,
        expected_owner_uid=candidate_owner_uid,
    )
    if hashlib.sha256(apply_bytes).hexdigest() != frozen.apply_receipt_sha256:
        raise TenantOperationsCandidateActivationError(
            "candidate apply receiptがactivation準備中に変化しました。"
        )
    database = apply_receipt["database"]
    token_sha256 = str(database["ownership_token_sha256"])
    mapping_rows = _mapped_candidate_rows(
        candidate_root,
        exact=True,
        expected_owner_uid=candidate_owner_uid,
    )
    _assert_apply_mapping(apply_receipt, mapping_rows)
    immutable_rows = [row for row in mapping_rows if _is_immutable_baseline_row(row)]
    activation_receipt = {
        "format": "templedb-tenant-pack-activation",
        "version": ACTIVATION_RECEIPT_VERSION,
        "status": "active-staging-candidate",
        "activated_at": datetime.now(UTC).isoformat(),
        "candidate_root": str(candidate_root),
        "runtime_role": "staging",
        "external_effects_enabled": False,
        "primary_cutover_completed": False,
        "apply_receipt_sha256": hashlib.sha256(apply_bytes).hexdigest(),
        "archive_sha256": frozen.archive_sha256,
        "platform_commit": frozen.platform_commit,
        "installation_id": frozen.installation_id,
        "database": {
            "name": frozen.database_name,
            "oid": frozen.database_oid,
            "connections_allowed": True,
            "ownership_token_sha256": token_sha256,
        },
        "apply_mapping": {
            "file_count": len(mapping_rows),
            "sha256": _mapping_sha256(mapping_rows),
        },
        "immutable_baseline": {
            "file_count": len(immutable_rows),
            "sha256": _mapping_sha256(immutable_rows),
            "files": immutable_rows,
        },
    }
    receipt_content = _json_bytes(activation_receipt)
    pending_content = _json_bytes(
        {
            "format": "templedb-tenant-pack-activation-pending",
            "version": 1,
            "candidate_root": str(candidate_root),
            "database_name": frozen.database_name,
            "database_oid": frozen.database_oid,
            "activation_receipt_sha256": hashlib.sha256(
                receipt_content
            ).hexdigest(),
        }
    )
    pending_path = candidate_root / ACTIVATION_PENDING_NAME
    activation_path = candidate_root / ACTIVATION_RECEIPT_NAME
    _write_private_file_exclusive(
        pending_path,
        pending_content,
        owner_uid=candidate_owner_uid,
    )
    database_thawed = False
    try:
        database_transfer_postgresql.set_postgresql_candidate_connections_allowed(
            database_name=frozen.database_name,
            expected_database_oid=frozen.database_oid,
            expected_ownership_token_sha256=token_sha256,
            current_connections_allowed=False,
            new_connections_allowed=True,
        )
        database_thawed = True
        _write_private_file_exclusive(
            activation_path,
            receipt_content,
            owner_uid=candidate_owner_uid,
        )
        result = verify_tenant_operations_candidate(
            candidate_tenant_root=candidate_root,
            expected_git_commit=frozen.platform_commit,
            expected_archive_sha256=frozen.archive_sha256,
            expected_installation_id=frozen.installation_id,
            expected_database_name=frozen.database_name,
            require_activated=True,
            platform_root=platform_root,
            expected_candidate_owner_uid=candidate_owner_uid,
            _allow_activation_pending=True,
        )
        _unlink_private_file(
            pending_path,
            expected_content=pending_content,
            expected_owner_uid=candidate_owner_uid,
        )
        return result
    except BaseException as exc:
        rollback_error: BaseException | None = None
        state_unknown = False
        if not database_thawed:
            observed_connections_allowed = _best_effort_candidate_connection_state(
                database_name=frozen.database_name,
                database_oid=frozen.database_oid,
                ownership_token_sha256=token_sha256,
            )
            if observed_connections_allowed is True:
                database_thawed = True
            elif observed_connections_allowed is None:
                state_unknown = True
        if database_thawed:
            default_database_connection.close()
            try:
                database_transfer_postgresql.set_postgresql_candidate_connections_allowed(
                    database_name=frozen.database_name,
                    expected_database_oid=frozen.database_oid,
                    expected_ownership_token_sha256=token_sha256,
                    current_connections_allowed=True,
                    new_connections_allowed=False,
                )
            except BaseException as rollback_exc:
                rollback_error = rollback_exc
        if rollback_error is None and not state_unknown:
            cleanup_errors: list[BaseException] = []
            if activation_path.exists() or activation_path.is_symlink():
                try:
                    _unlink_private_file(
                        activation_path,
                        expected_content=receipt_content,
                        expected_owner_uid=candidate_owner_uid,
                    )
                except BaseException as cleanup_exc:
                    cleanup_errors.append(cleanup_exc)
            if pending_path.exists():
                try:
                    _unlink_private_file(
                        pending_path,
                        expected_content=pending_content,
                        expected_owner_uid=candidate_owner_uid,
                    )
                except BaseException as cleanup_exc:
                    cleanup_errors.append(cleanup_exc)
            if cleanup_errors:
                exc.add_note(
                    "candidate DBは再凍結しましたが、activation control fileを"
                    "安全に清掃できませんでした。"
                )
                raise TenantOperationsCandidateActivationError(
                    "candidate activationに失敗し、再凍結後のcontrol file清掃も"
                    "完了できませんでした。"
                ) from exc
        if rollback_error is not None or state_unknown:
            exc.add_note(
                "candidate DBの状態を安全に確定できません。activation pendingを残しています。"
            )
            raise TenantOperationsCandidateActivationError(
                "candidate activationに失敗し、DBの再凍結を証明できませんでした。"
            ) from exc
        if isinstance(exc, TenantOperationsCandidateActivationError):
            raise
        raise TenantOperationsCandidateActivationError(
            "candidate activationを完了できなかったためDBを再凍結しました。"
        ) from exc


def deactivate_tenant_operations_candidate(
    *,
    candidate_tenant_root: str | Path,
    confirm_candidate_tenant_root: str,
    expected_git_commit: str,
    expected_runtime_git_commit: str | None = None,
    expected_archive_sha256: str,
    expected_installation_id: str,
    expected_database_name: str,
    confirm_database_name: str,
    platform_root: str | Path | None = None,
    expected_candidate_owner_uid: int | None = None,
) -> TenantOperationsCandidateVerificationResult:
    candidate_owner_uid = _validated_candidate_owner_uid(
        expected_candidate_owner_uid
    )
    candidate_root = _validated_candidate_root(
        candidate_tenant_root,
        expected_owner_uid=candidate_owner_uid,
    )
    if confirm_candidate_tenant_root.strip() != str(candidate_root):
        raise TenantOperationsCandidateActivationError(
            "candidate rootの確認値が一致しません。"
        )
    database_name = _validated_database_name(expected_database_name)
    if confirm_database_name.strip() != database_name:
        raise TenantOperationsCandidateActivationError(
            "candidate DB名の確認値が一致しません。"
        )
    active = verify_tenant_operations_candidate(
        candidate_tenant_root=candidate_root,
        expected_git_commit=expected_git_commit,
        expected_runtime_git_commit=expected_runtime_git_commit,
        expected_archive_sha256=expected_archive_sha256,
        expected_installation_id=expected_installation_id,
        expected_database_name=database_name,
        require_activated=True,
        platform_root=platform_root,
        expected_candidate_owner_uid=candidate_owner_uid,
    )
    default_database_connection.close()
    activation_bytes, activation_receipt = _read_private_json(
        candidate_root / ACTIVATION_RECEIPT_NAME,
        expected_owner_uid=candidate_owner_uid,
    )
    database = activation_receipt["database"]
    token_sha256 = str(database["ownership_token_sha256"])
    deactivation_receipt = {
        "format": "templedb-tenant-pack-deactivation",
        "version": 1,
        "status": "frozen-staging-candidate",
        "deactivated_at": datetime.now(UTC).isoformat(),
        "candidate_root": str(candidate_root),
        "runtime_role": "staging",
        "activation_receipt_sha256": hashlib.sha256(
            activation_bytes
        ).hexdigest(),
        "archive_sha256": active.archive_sha256,
        "platform_commit": active.platform_commit,
        "runtime_platform_commit": active.runtime_platform_commit,
        "installation_id": active.installation_id,
        "database": {
            "name": active.database_name,
            "oid": active.database_oid,
            "connections_allowed": False,
            "ownership_token_sha256": token_sha256,
        },
    }
    receipt_content = _json_bytes(deactivation_receipt)
    pending_content = _json_bytes(
        {
            "format": "templedb-tenant-pack-deactivation-pending",
            "version": 1,
            "candidate_root": str(candidate_root),
            "database_name": active.database_name,
            "database_oid": active.database_oid,
            "deactivation_receipt_sha256": hashlib.sha256(
                receipt_content
            ).hexdigest(),
        }
    )
    pending_path = candidate_root / DEACTIVATION_PENDING_NAME
    receipt_path = candidate_root / DEACTIVATION_RECEIPT_NAME
    _write_private_file_exclusive(
        pending_path,
        pending_content,
        owner_uid=candidate_owner_uid,
    )
    try:
        state = database_transfer_postgresql.set_postgresql_candidate_connections_allowed(
            database_name=active.database_name,
            expected_database_oid=active.database_oid,
            expected_ownership_token_sha256=token_sha256,
            current_connections_allowed=True,
            new_connections_allowed=False,
        )
        _write_private_file_exclusive(
            receipt_path,
            receipt_content,
            owner_uid=candidate_owner_uid,
        )
        _unlink_private_file(
            pending_path,
            expected_content=pending_content,
            expected_owner_uid=candidate_owner_uid,
        )
    except BaseException as exc:
        safe_pre_mutation_failure = False
        try:
            database_transfer_postgresql.inspect_postgresql_candidate(
                database_name=active.database_name,
                expected_database_oid=active.database_oid,
                expected_ownership_token_sha256=token_sha256,
                expected_connections_allowed=True,
            )
            safe_pre_mutation_failure = True
        except BaseException:
            pass
        if safe_pre_mutation_failure:
            try:
                _unlink_private_file(
                    pending_path,
                    expected_content=pending_content,
                    expected_owner_uid=candidate_owner_uid,
                )
            except BaseException:
                exc.add_note(
                    "DBは接続許可のままですが、deactivation pendingを"
                    "安全に清掃できませんでした。"
                )
                raise TenantOperationsCandidateActivationError(
                    "candidate deactivationはDB変更前に停止しましたが、"
                    "pending記録を清掃できませんでした。"
                ) from exc
            raise TenantOperationsCandidateActivationError(
                "candidate deactivationはDB変更前に停止しました。"
                "service接続を終了してから再実行してください。"
            ) from exc
        raise TenantOperationsCandidateActivationError(
            "candidate deactivationを完了できませんでした。"
            "serviceを起動せず、pending記録とDB状態を確認してください。"
        ) from exc
    return TenantOperationsCandidateVerificationResult(
        candidate_root=candidate_root,
        database_name=active.database_name,
        database_oid=active.database_oid,
        archive_sha256=active.archive_sha256,
        platform_commit=active.platform_commit,
        runtime_platform_commit=active.runtime_platform_commit,
        installation_id=active.installation_id,
        apply_receipt_sha256=active.apply_receipt_sha256,
        mapping_file_count=active.mapping_file_count,
        connections_allowed=state.connections_allowed,
        activated=False,
    )


def _require_staging_role() -> None:
    if runtime_role.current_runtime_role() != runtime_role.RUNTIME_ROLE_STAGING:
        raise TenantOperationsCandidateActivationError(
            "candidateの検証・activationはstaging roleでだけ実行できます。"
        )


def _best_effort_candidate_connection_state(
    *,
    database_name: str,
    database_oid: int,
    ownership_token_sha256: str,
) -> bool | None:
    for expected in (True, False):
        try:
            database_transfer_postgresql.inspect_postgresql_candidate(
                database_name=database_name,
                expected_database_oid=database_oid,
                expected_ownership_token_sha256=ownership_token_sha256,
                expected_connections_allowed=expected,
            )
        except BaseException:
            continue
        return expected
    return None


def _validated_candidate_owner_uid(raw_uid: int | None) -> int:
    current_uid = os.getuid()
    if raw_uid is None:
        if current_uid == 0:
            raise TenantOperationsCandidateActivationError(
                "root operatorは非root candidate owner UIDを明示してください。"
            )
        return current_uid
    if isinstance(raw_uid, bool) or not isinstance(raw_uid, int) or raw_uid <= 0:
        raise TenantOperationsCandidateActivationError(
            "candidate owner UIDが不正です。"
        )
    if current_uid != 0 and raw_uid != current_uid:
        raise TenantOperationsCandidateActivationError(
            "root以外は別user所有candidateを操作できません。"
        )
    return raw_uid


def _validated_candidate_root(
    raw_root: str | Path,
    *,
    expected_owner_uid: int,
) -> Path:
    path = Path(os.path.abspath(Path(raw_root).expanduser()))
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate rootを確認できません。"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or resolved != path
        or metadata.st_uid != expected_owner_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate rootは現在user所有のsymlinkでない0700 directoryにしてください。"
        )
    return path


def _validated_git_commit(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if not _GIT_COMMIT_PATTERN.fullmatch(value):
        raise TenantOperationsCandidateActivationError(
            "Platform Git commitは完全hashで指定してください。"
        )
    return value


def _validated_sha256(raw_value: object, *, label: str) -> str:
    value = str(raw_value or "").strip().lower()
    if not _SHA256_PATTERN.fullmatch(value):
        raise TenantOperationsCandidateActivationError(f"{label}が不正です。")
    return value


def _validated_installation_id(raw_value: object) -> str:
    try:
        return str(uuid.UUID(str(raw_value or "").strip()))
    except (ValueError, AttributeError) as exc:
        raise TenantOperationsCandidateActivationError(
            "installation IDが不正です。"
        ) from exc


def _validated_database_name(raw_value: object) -> str:
    try:
        return database_transfer_postgresql.validate_postgresql_clone_database_name(
            str(raw_value or "")
        )
    except database_transfer_postgresql.DatabaseTransferError as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate DB名が不正です。"
        ) from exc


def _validated_apply_receipt(
    receipt: dict[str, object],
    *,
    marker: dict[str, object],
    apply_sha256: str,
    candidate_root: Path,
    expected_git_commit: str,
    expected_archive_sha256: str,
    expected_installation_id: str,
    expected_database_name: str,
) -> dict[str, object]:
    database = receipt.get("database")
    mapping = receipt.get("mapping")
    candidate_mapping = receipt.get("candidate_mapping")
    if (
        receipt.get("format") != "templedb-tenant-pack-apply"
        or receipt.get("version") != tenant_operations_pack_apply.APPLY_RECEIPT_VERSION
        or receipt.get("status") != "frozen-staging-candidate"
        or receipt.get("candidate_root") != str(candidate_root)
        or receipt.get("runtime_role") != "staging"
        or receipt.get("external_effects_enabled") is not False
        or receipt.get("primary_cutover_completed") is not False
        or receipt.get("source_env_applied") is not False
        or receipt.get("platform_commit") != expected_git_commit
        or receipt.get("archive_sha256") != expected_archive_sha256
        or receipt.get("installation_id") != expected_installation_id
        or receipt.get("database_engine") != "postgresql"
        or not isinstance(database, dict)
        or not isinstance(mapping, dict)
        or not isinstance(candidate_mapping, dict)
        or database.get("name") != expected_database_name
        or database.get("connections_allowed") is not False
        or isinstance(database.get("oid"), bool)
        or not isinstance(database.get("oid"), int)
        or int(database["oid"]) <= 0
        or not _SHA256_PATTERN.fullmatch(
            str(database.get("ownership_token_sha256") or "")
        )
        or marker.get("format") != "templedb-tenant-pack-apply-complete"
        or marker.get("version") != 1
        or marker.get("receipt_sha256") != apply_sha256
        or marker.get("database_name") != expected_database_name
        or marker.get("connections_allowed") is not False
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate apply receiptまたは完了印が安全契約と一致しません。"
        )
    return database


def _assert_apply_mapping(
    receipt: dict[str, object],
    mapping_rows: list[dict[str, object]],
) -> None:
    mapping = receipt.get("candidate_mapping")
    assert isinstance(mapping, dict)
    category_counts = dict(
        sorted(Counter(str(row["category"]) for row in mapping_rows).items())
    )
    if (
        mapping.get("file_count") != len(mapping_rows)
        or mapping.get("sha256") != _mapping_sha256(mapping_rows)
        or mapping.get("category_counts") != category_counts
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate tenant資産がapply時のmappingと一致しません。"
        )


def _assert_live_candidate_contract(
    receipt: dict[str, object],
    *,
    expected_installation_id: str,
    database_connection=None,
) -> None:
    expected_contract, target_major = _validated_expected_candidate_contract(
        receipt,
        expected_installation_id=expected_installation_id,
    )

    connection = database_connection or default_database_connection
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT installation_id::text, runtime_kind "
                "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
            )
            identity_rows = cursor.fetchall()
            cursor.execute("SELECT app, name FROM django_migrations")
            migration_rows = cursor.fetchall()
            cursor.execute("SHOW server_version_num")
            version_row = cursor.fetchone()
    except Exception as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate DBのidentityとmigrationを読み取り専用で確認できません。"
        ) from exc
    if (
        len(identity_rows) != 1
        or tuple(identity_rows[0]) != (expected_installation_id, "product")
        or not version_row
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate DBのidentityが復元契約と一致しません。"
        )
    try:
        live_major = int(version_row[0]) // 10_000
        live_migrations = backup_restore_contract.build_migration_inventory(
            migration_rows
        )
    except (TypeError, ValueError, IndexError) as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate DBのmajorまたはmigration情報が不正です。"
        ) from exc
    if (
        live_major != target_major
        or live_migrations != expected_contract["applied_migrations"]
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate DBのmajorまたはmigrationが復元契約と一致しません。"
        )


def _validated_expected_candidate_contract(
    receipt: dict[str, object],
    *,
    expected_installation_id: str,
) -> tuple[dict[str, object], int]:
    validation = receipt.get("database_validation")
    restore_summary = (
        validation.get("restore_summary") if isinstance(validation, dict) else None
    )
    target_major = (
        validation.get("target_postgresql_major")
        if isinstance(validation, dict)
        else None
    )
    try:
        expected_contract = backup_restore_contract.validated_restore_contract(
            restore_summary,
            expected_database_engine="postgresql",
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise TenantOperationsCandidateActivationError(
            "candidate apply receiptのDB復元契約が不正です。"
        ) from exc
    if (
        isinstance(target_major, bool)
        or not isinstance(target_major, int)
        or not 10 <= target_major <= 99
        or expected_contract["database_version"] != str(target_major)
        or expected_contract["database_version_scope"] != "server_major"
        or expected_contract["runtime_identity"]["installation_id"]
        != expected_installation_id
        or expected_contract["runtime_identity"]["runtime_kind"] != "product"
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate apply receiptのDB復元契約が確認値と一致しません。"
        )
    return expected_contract, target_major


def _validated_activation_receipt(
    receipt: dict[str, object],
    *,
    apply_sha256: str,
    candidate_root: Path,
    expected_git_commit: str,
    expected_archive_sha256: str,
    expected_installation_id: str,
    expected_database_name: str,
    expected_database_oid: int,
    expected_ownership_token_sha256: str,
) -> list[dict[str, object]]:
    database = receipt.get("database")
    baseline = receipt.get("immutable_baseline")
    files = baseline.get("files") if isinstance(baseline, dict) else None
    if (
        receipt.get("format") != "templedb-tenant-pack-activation"
        or receipt.get("version") != ACTIVATION_RECEIPT_VERSION
        or receipt.get("status") != "active-staging-candidate"
        or receipt.get("candidate_root") != str(candidate_root)
        or receipt.get("runtime_role") != "staging"
        or receipt.get("external_effects_enabled") is not False
        or receipt.get("primary_cutover_completed") is not False
        or receipt.get("apply_receipt_sha256") != apply_sha256
        or receipt.get("platform_commit") != expected_git_commit
        or receipt.get("archive_sha256") != expected_archive_sha256
        or receipt.get("installation_id") != expected_installation_id
        or not isinstance(database, dict)
        or database.get("name") != expected_database_name
        or database.get("oid") != expected_database_oid
        or database.get("connections_allowed") is not True
        or database.get("ownership_token_sha256")
        != expected_ownership_token_sha256
        or not isinstance(baseline, dict)
        or not isinstance(files, list)
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate activation receiptが安全契約と一致しません。"
        )
    normalized_rows = [_validated_baseline_row(row) for row in files]
    if (
        baseline.get("file_count") != len(normalized_rows)
        or baseline.get("sha256") != _mapping_sha256(normalized_rows)
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate immutable baselineのdigestが一致しません。"
        )
    return normalized_rows


def _validated_baseline_row(raw_row: object) -> dict[str, object]:
    if not isinstance(raw_row, dict) or set(raw_row) != {
        "destination",
        "category",
        "size",
        "sha256",
    }:
        raise TenantOperationsCandidateActivationError(
            "candidate baseline file情報が不正です。"
        )
    destination = str(raw_row["destination"])
    category = str(raw_row["category"])
    size = raw_row["size"]
    sha256 = str(raw_row["sha256"])
    pure_path = PurePosixPath(destination)
    if (
        pure_path.is_absolute()
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or "\\" in destination
        or not _is_immutable_baseline_destination(
            destination=destination,
            category=category,
        )
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not _SHA256_PATTERN.fullmatch(sha256)
    ):
        raise TenantOperationsCandidateActivationError(
            "candidate baseline file情報が不正です。"
        )
    return {
        "destination": destination,
        "category": category,
        "size": size,
        "sha256": sha256,
    }


def _mapped_candidate_rows(
    candidate_root: Path,
    *,
    exact: bool,
    expected_owner_uid: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for relative_path, metadata in _walk_candidate_files(
        candidate_root,
        expected_owner_uid=expected_owner_uid,
    ):
        if relative_path in _control_file_names():
            continue
        category = _category_for_candidate_path(relative_path)
        if category is None:
            if exact:
                raise TenantOperationsCandidateActivationError(
                    f"candidateにallowlist外のfileがあります: {relative_path}"
                )
            continue
        size, sha256 = _safe_file_size_and_sha256(
            candidate_root / relative_path,
            expected_metadata=metadata,
            expected_owner_uid=expected_owner_uid,
        )
        rows.append(
            {
                "destination": relative_path,
                "category": category,
                "size": size,
                "sha256": sha256,
            }
        )
    return sorted(rows, key=lambda row: str(row["destination"]))


def _category_for_candidate_path(relative_path: str) -> str | None:
    pure_path = PurePosixPath(relative_path)
    if pure_path == PurePosixPath(".env"):
        return "runtime_env_sentinel"
    prefixes = (
        (PurePosixPath("config/tenant_policy/default"), "tenant_policy"),
        (PurePosixPath("config/tenant_preferences"), "tenant_preferences"),
        (PurePosixPath("data/private"), "private_payload"),
        (PurePosixPath("data/generated"), "generated_reference"),
    )
    for prefix, category in prefixes:
        if pure_path.is_relative_to(prefix) and pure_path != prefix:
            return category
    if pure_path == PurePosixPath("data/runtime/source_registry.json"):
        return "source_registry"
    if (
        pure_path.parent == PurePosixPath("data/runtime/matplotlib")
        and _MATPLOTLIB_FONT_CACHE_PATTERN.fullmatch(pure_path.name)
    ):
        return "runtime_cache"
    return None


def _mapping_sha256(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        json.dumps(
            sorted(rows, key=lambda row: str(row["destination"])),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _is_immutable_baseline_row(row: dict[str, object]) -> bool:
    return _is_immutable_baseline_destination(
        destination=str(row["destination"]),
        category=str(row["category"]),
    )


def _is_immutable_baseline_destination(*, destination: str, category: str) -> bool:
    if category in _IMMUTABLE_BASELINE_CATEGORIES:
        return True
    if category != "private_payload":
        return False
    pure_path = PurePosixPath(destination)
    private_root = PurePosixPath("data/private")
    if not pure_path.is_relative_to(private_root) or pure_path == private_root:
        return False
    return not pure_path.is_relative_to(_MUTABLE_POSTAL_SCAN_ROOT)


def _control_file_names() -> frozenset[str]:
    return frozenset(
        {
            tenant_operations_pack_apply.APPLY_RECEIPT_NAME,
            tenant_operations_pack_apply.APPLY_COMPLETION_MARKER_NAME,
            ACTIVATION_RECEIPT_NAME,
            ACTIVATION_PENDING_NAME,
            DEACTIVATION_RECEIPT_NAME,
            DEACTIVATION_PENDING_NAME,
        }
    )


def _assert_candidate_tree_safe(
    candidate_root: Path,
    *,
    expected_owner_uid: int,
) -> None:
    # These mutable process controls are valid only after activation.  Keep them
    # out of _category_for_candidate_path so frozen pack mappings still reject
    # them, and never unlink the persistent flock guard during startup.
    process_control_files = set(_ACTIVATED_BACKUP_CONTROL_FILES)
    sync_lock_root = candidate_root / _ACTIVATED_GOOGLE_SYNC_LOCK_ROOT
    if sync_lock_root.is_dir() and not sync_lock_root.is_symlink():
        for path in sync_lock_root.iterdir():
            if not _GOOGLE_SYNC_LOCK_NAME.fullmatch(path.name):
                raise TenantOperationsCandidateActivationError(
                    f"candidateにallowlist外のfileがあります: {path.relative_to(candidate_root)}"
                )
            process_control_files.add(path.relative_to(candidate_root).as_posix())
    for relative_path in process_control_files:
        try:
            metadata = (candidate_root / relative_path).lstat()
        except FileNotFoundError:
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_owner_uid
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidate backup control fileの安全条件が不正です: {relative_path}"
            )
    for relative_path, metadata in _walk_candidate_files(
        candidate_root,
        expected_owner_uid=expected_owner_uid,
    ):
        path = candidate_root / relative_path
        if metadata.st_uid != expected_owner_uid or metadata.st_nlink != 1:
            raise TenantOperationsCandidateActivationError(
                f"candidate fileのownerまたはlink数が不正です: {relative_path}"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise TenantOperationsCandidateActivationError(
                f"candidate fileがgroup/other書込可能です: {relative_path}"
            )
        if path.is_symlink():
            raise TenantOperationsCandidateActivationError(
                f"candidateにsymlinkがあります: {relative_path}"
            )
        if (
            relative_path not in _control_file_names()
            and relative_path not in process_control_files
            and _category_for_candidate_path(relative_path) is None
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidateにallowlist外のfileがあります: {relative_path}"
            )


def _walk_candidate_files(candidate_root: Path, *, expected_owner_uid: int):
    stack = [candidate_root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise TenantOperationsCandidateActivationError(
                "candidate tenant資産を列挙できません。"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise TenantOperationsCandidateActivationError(
                    "candidate tenant資産のmetadataを確認できません。"
                ) from exc
            relative_path = path.relative_to(candidate_root).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                raise TenantOperationsCandidateActivationError(
                    f"candidateにsymlinkがあります: {relative_path}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                if (
                    metadata.st_uid != expected_owner_uid
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                ):
                    raise TenantOperationsCandidateActivationError(
                        f"candidate directoryのownerまたはmodeが不正です: {relative_path}"
                    )
                stack.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                yield relative_path, metadata
            else:
                raise TenantOperationsCandidateActivationError(
                    f"candidateに特殊fileがあります: {relative_path}"
                )


def _verify_immutable_baseline(
    candidate_root: Path,
    rows: list[dict[str, object]],
    *,
    expected_owner_uid: int,
) -> None:
    for row in rows:
        path = candidate_root / str(row["destination"])
        size, sha256 = _safe_file_size_and_sha256(
            path,
            expected_owner_uid=expected_owner_uid,
        )
        if size != row["size"] or sha256 != row["sha256"]:
            raise TenantOperationsCandidateActivationError(
                f"candidateの基準fileが変更されています: {row['destination']}"
            )


def _safe_file_size_and_sha256(
    path: Path,
    *,
    expected_owner_uid: int,
    expected_metadata=None,
) -> tuple[int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TenantOperationsCandidateActivationError(
            f"candidate fileを安全に開けません: {path.name}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_owner_uid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or (
                expected_metadata is not None
                and (
                    before.st_dev != expected_metadata.st_dev
                    or before.st_ino != expected_metadata.st_ino
                    or before.st_size != expected_metadata.st_size
                )
            )
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidate fileの安全条件が一致しません: {path.name}"
            )
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or size != after.st_size
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidate fileが検証中に変更されました: {path.name}"
            )
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _read_private_json(
    path: Path,
    *,
    expected_owner_uid: int,
) -> tuple[bytes, dict[str, object]]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TenantOperationsCandidateActivationError(
            f"candidate control fileを安全に開けません: {path.name}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_owner_uid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > _MAX_CONTROL_FILE_SIZE
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidate control fileのowner、mode、link数またはsizeが不正です: {path.name}"
            )
        content = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            content += chunk
            if len(content) > _MAX_CONTROL_FILE_SIZE:
                raise TenantOperationsCandidateActivationError(
                    f"candidate control fileが大きすぎます: {path.name}"
                )
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
        ):
            raise TenantOperationsCandidateActivationError(
                f"candidate control fileが検証中に変更されました: {path.name}"
            )
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TenantOperationsCandidateActivationError(
            f"candidate control fileが正しいJSONではありません: {path.name}"
        ) from exc
    if not isinstance(parsed, dict):
        raise TenantOperationsCandidateActivationError(
            f"candidate control fileのrootがobjectではありません: {path.name}"
        )
    return content, parsed


def _unique_object(pairs):
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TenantOperationsCandidateActivationError(
                "candidate control JSONに重複keyがあります。"
            )
        result[key] = value
    return result


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_private_file_exclusive(
    path: Path,
    content: bytes,
    *,
    owner_uid: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.getuid() == 0 and owner_uid != 0:
            os.fchown(descriptor, owner_uid, -1)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise TenantOperationsCandidateActivationError(
                    "activation control fileを完全に書き込めませんでした。"
                )
            offset += written
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _unlink_private_file(
    path: Path,
    *,
    expected_content: bytes,
    expected_owner_uid: int,
) -> None:
    content, _parsed = _read_private_json(
        path,
        expected_owner_uid=expected_owner_uid,
    )
    if content != expected_content:
        raise TenantOperationsCandidateActivationError(
            f"activation control fileが変化したため削除しません: {path.name}"
        )
    path.unlink()
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
