from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.core.models import (
    DatabaseBackupRun,
    DatabaseBackupVerificationRun,
    DatabaseRuntimeIdentity,
)
from config import instance_runtime, runtime_paths

from . import (
    backup,
    backup_restore_contract,
    handoff_archive,
    runtime_role,
    tenant_policy,
    ui_appearance,
)
from . import (
    backup_migration_archive as _archive,
)
from .tenant_operations_pack_contract import (
    GENERATED_REFERENCE_ARCHIVE_ROOT,
    OPERATIONS_MANIFEST_PATH,
    PACKAGE_KIND,
    PACKAGE_VERSION,
    PRIVACY_CLASSIFICATION,
    PRIVATE_PAYLOAD_ARCHIVE_ROOT,
    README_PATH,
    SAFETY_CONTRACT,
    SOURCE_ENV_PATH,
    SOURCE_REGISTRY_ARCHIVE_PATH,
    TENANT_POLICY_ARCHIVE_ROOT,
    TENANT_PREFERENCES_ARCHIVE_ROOT,
    VERIFICATION_SUMMARY_PATH,
)

_ENV_KEY_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")
_SECRET_KEY_MARKERS = (
    "API_KEY",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_TUNING_KEY_MARKERS = (
    "CACHE",
    "LIMIT",
    "THREAD",
    "TIMEOUT",
    "WORKER",
)


class TenantOperationsPackError(RuntimeError):
    """Raised when an operations pack cannot be created safely."""


@dataclass(frozen=True)
class _TenantPayloadPaths:
    root: Path
    policy_root: Path
    preferences_root: Path
    private_root: Path
    source_registry_path: Path
    generated_root: Path


def create_tenant_operations_pack(
    backup_run,
    *,
    confirm_installation_id: str,
    include_restricted_payload: bool = False,
    workspace_root: str | Path | None = None,
) -> tuple[BinaryIO, str]:
    if not include_restricted_payload:
        raise TenantOperationsPackError(
            "[TENANT_PACK_CONFIRMATION_REQUIRED] "
            "DB、credential、個人情報を含む運用パックであることを確認してください。"
        )
    if runtime_role.current_runtime_role() != runtime_role.RUNTIME_ROLE_PRIMARY:
        raise TenantOperationsPackError(
            "[TENANT_PACK_PRIMARY_REQUIRED] "
            "テナント運用パックはPrimaryからだけ作成できます。"
        )
    if backup_run is None:
        raise TenantOperationsPackError(
            "[TENANT_PACK_BACKUP_REQUIRED] 対象バックアップが見つかりません。"
        )

    resolved_platform_root = _validated_workspace_root(
        Path(workspace_root) if workspace_root is not None else Path(backup.BASE_DIR)
    )
    tenant_payload_paths = _tenant_payload_paths(resolved_platform_root)
    (
        platform_runtime_database_exclusions,
        tenant_runtime_database_exclusions,
    ) = _archive._runtime_database_exclusions_for_roots(
        backup,
        resolved_platform_root,
        tenant_payload_paths.root,
    )
    git_snapshot_before = _archive._capture_git_snapshot(resolved_platform_root)
    if git_snapshot_before.get("status_entry_count") != 0:
        raise TenantOperationsPackError(
            "[TENANT_PACK_CLEAN_SOURCE_REQUIRED] "
            "未コミット変更があるため、Platform commitを確定してから作成してください。"
        )

    source_state_before = _validated_source_database_state(
        backup_run,
        confirm_installation_id=confirm_installation_id,
    )
    artifact_path = backup.validate_backup_artifact(backup_run)
    backup_manifest_path, backup_manifest_sha256 = (
        _archive._validate_backup_manifest_for_bundle(
            backup,
            backup_run,
            artifact_path,
        )
    )
    source_members, source_selection, env_keys = _collect_operations_source_members(
        resolved_platform_root,
        tenant_payload_paths=tenant_payload_paths,
        platform_runtime_database_exclusions=platform_runtime_database_exclusions,
        tenant_runtime_database_exclusions=tenant_runtime_database_exclusions,
    )
    backup_members = [
        _archive._source_file_archive_member(
            artifact_path,
            f"database/{artifact_path.name}",
            category="database_backup",
            private=True,
        ),
        _archive._source_file_archive_member(
            backup_manifest_path,
            f"database/{backup_manifest_path.name}",
            category="database_backup_manifest",
            private=True,
        ),
    ]
    backup_database_member, backup_manifest_member = backup_members
    if (
        backup_database_member.size
        != source_state_before["backup"]["backup_file_size"]
        or backup_database_member.sha256
        != source_state_before["backup"]["backup_sha256"]
        or backup_manifest_member.sha256 != backup_manifest_sha256
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_BACKUP_CHANGED] "
            "検証後にbackupまたはbackup manifestが変更されました。"
        )
    all_source_members = sorted(
        [*source_members, *backup_members],
        key=lambda member: member.archive_path,
    )

    created_at = timezone.now()
    root_dir = _build_package_root(backup_run, created_at=created_at)
    filename = f"{root_dir}.tar.gz"
    verification_content = _render_verification_summary(source_state_before)
    operations_manifest = _build_operations_manifest(
        source_state=source_state_before,
        source_members=source_members,
        backup_database_member=backup_database_member,
        backup_manifest_member=backup_manifest_member,
        source_selection=source_selection,
        env_keys=env_keys,
        verification_content=verification_content,
        git_snapshot=git_snapshot_before,
        root_dir=root_dir,
        created_at=created_at,
    )
    generated_members = [
        _archive._bytes_archive_member(
            OPERATIONS_MANIFEST_PATH,
            _json_bytes(operations_manifest),
            "tenant_operations_manifest",
        ),
        _archive._bytes_archive_member(
            VERIFICATION_SUMMARY_PATH,
            verification_content,
            "restore_verification",
        ),
        _archive._bytes_archive_member(
            README_PATH,
            _render_readme().encode("utf-8"),
            "operator_guide",
        ),
    ]

    payload_members = _archive._with_archive_parent_directories(
        [*all_source_members, *generated_members]
    )
    _archive._validate_archive_member_set(payload_members)
    archive_manifest_content, checksums_content = (
        _archive._render_archive_integrity_files(
            payload_members,
            root_dir=root_dir,
            git_snapshot=git_snapshot_before,
        )
    )
    integrity_members = [
        _archive._bytes_archive_member(
            _archive.ARCHIVE_MANIFEST_PATH.as_posix(),
            archive_manifest_content,
            "archive_manifest",
        ),
        _archive._bytes_archive_member(
            _archive.ARCHIVE_CHECKSUMS_PATH.as_posix(),
            checksums_content,
            "archive_checksums",
        ),
    ]
    all_members = _archive._with_archive_parent_directories(
        [*payload_members, *integrity_members]
    )
    _archive._validate_archive_member_set(all_members)

    package_file = tempfile.TemporaryFile(mode="w+b")
    os.fchmod(package_file.fileno(), 0o600)
    try:
        with tarfile.open(
            fileobj=package_file,
            mode="w:gz",
            format=tarfile.GNU_FORMAT,
        ) as archive_file:
            _archive._write_archive_root_directory(archive_file, root_dir)
            for member in sorted(all_members, key=lambda item: item.archive_path):
                _archive._write_archive_member(archive_file, root_dir, member)

        source_members_after, source_selection_after, env_keys_after = (
            _collect_operations_source_members(
                resolved_platform_root,
                tenant_payload_paths=tenant_payload_paths,
                platform_runtime_database_exclusions=platform_runtime_database_exclusions,
                tenant_runtime_database_exclusions=tenant_runtime_database_exclusions,
            )
        )
        backup_members_after = [
            _archive._source_file_archive_member(
                artifact_path,
                f"database/{artifact_path.name}",
                category="database_backup",
                private=True,
            ),
            _archive._source_file_archive_member(
                backup_manifest_path,
                f"database/{backup_manifest_path.name}",
                category="database_backup_manifest",
                private=True,
            ),
        ]
        all_source_members_after = sorted(
            [*source_members_after, *backup_members_after],
            key=lambda member: member.archive_path,
        )
        source_state_after = _validated_source_database_state(
            DatabaseBackupRun.objects.get(pk=backup_run.pk),
            confirm_installation_id=confirm_installation_id,
        )
        if (
            _archive._source_inventory_fingerprint(all_source_members_after)
            != _archive._source_inventory_fingerprint(all_source_members)
            or source_selection_after != source_selection
            or env_keys_after != env_keys
            or source_state_after != source_state_before
            or _archive._capture_git_snapshot(resolved_platform_root)
            != git_snapshot_before
        ):
            raise TenantOperationsPackError(
                "[TENANT_PACK_SOURCE_CHANGED] "
                "作成中にbackup、設定、private資産、DB契約またはGit状態が変わりました。"
            )
    except BaseException:
        package_file.close()
        raise

    package_file.seek(0)
    return package_file, filename


def export_tenant_operations_pack(
    backup_run,
    *,
    output_root: str | Path,
    confirm_installation_id: str,
    include_restricted_payload: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, object]:
    resolved_platform_root = _validated_workspace_root(
        Path(workspace_root) if workspace_root is not None else Path(backup.BASE_DIR)
    )
    tenant_payload_paths = _tenant_payload_paths(resolved_platform_root)
    resolved_output_root = _validated_output_root(
        Path(output_root),
        workspace_root=resolved_platform_root,
        tenant_root=tenant_payload_paths.root,
    )
    package_file, filename = create_tenant_operations_pack(
        backup_run,
        confirm_installation_id=confirm_installation_id,
        include_restricted_payload=include_restricted_payload,
        workspace_root=resolved_platform_root,
    )
    try:
        result = handoff_archive.write_archive_atomic(
            package_file,
            filename=filename,
            output_root=resolved_output_root,
        )
    finally:
        package_file.close()
    return {
        "package_kind": PACKAGE_KIND,
        "backup_run_id": backup_run.pk,
        **result,
    }


def _validated_source_database_state(
    backup_run,
    *,
    confirm_installation_id: str,
) -> dict[str, object]:
    if getattr(backup_run, "status", "") != "succeeded":
        raise TenantOperationsPackError(
            "[TENANT_PACK_BACKUP_NOT_SUCCEEDED] 成功したバックアップだけを利用できます。"
        )
    if (
        backup_run.finished_at is None
        or isinstance(backup_run.backup_file_size, bool)
        or not isinstance(backup_run.backup_file_size, int)
        or backup_run.backup_file_size <= 0
        or not re.fullmatch(r"[0-9a-f]{64}", str(backup_run.backup_sha256 or "").lower())
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_BACKUP_METADATA_INCOMPLETE] "
            "完了時刻、size、SHA256が揃ったバックアップだけを利用できます。"
        )
    current_engine = backup.current_database_engine()
    if backup_run.database_engine != current_engine:
        raise TenantOperationsPackError(
            "[TENANT_PACK_ENGINE_MISMATCH] 現在のDB種別とバックアップが一致しません。"
        )

    verification = backup.latest_verification_for_backup_run(backup_run)
    if (
        verification is None
        or verification.status != "succeeded"
        or verification.finished_at is None
        or not isinstance(verification.verification_summary, dict)
        or not verification.verification_summary
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_VERIFICATION_REQUIRED] "
            "同じバックアップの最新テスト復元を成功させてください。"
        )
    try:
        restored_contract = backup_restore_contract.validated_restore_contract(
            verification.verification_summary,
            expected_database_engine=current_engine,
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_RESTORE_CONTRACT_REQUIRED] "
            "製品DB識別子・migration・DB版を記録するテスト復元をやり直してください。"
        ) from exc

    try:
        identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
    except DatabaseRuntimeIdentity.DoesNotExist as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_IDENTITY_REQUIRED] 現在のDBに製品識別情報がありません。"
        ) from exc
    current_identity = _normalized_product_identity(identity)
    try:
        confirmed_installation_id = str(uuid.UUID(str(confirm_installation_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_INSTALLATION_CONFIRMATION_INVALID] "
            "確認用installation IDが不正です。"
        ) from exc
    if confirmed_installation_id != current_identity["installation_id"]:
        raise TenantOperationsPackError(
            "[TENANT_PACK_INSTALLATION_CONFIRMATION_MISMATCH] "
            "確認用installation IDが現在の製品DBと一致しません。"
        )

    current_contract = _current_database_contract(
        current_engine=current_engine,
        identity=current_identity,
    )
    if restored_contract != current_contract:
        raise TenantOperationsPackError(
            "[TENANT_PACK_RESTORE_CONTRACT_MISMATCH] "
            "テスト復元したDB識別子、migrationまたはDB版が現在の製品DBと一致しません。"
        )

    return {
        "backup": _backup_run_snapshot(backup_run),
        "verification": _verification_run_snapshot(verification),
        "runtime_identity": current_identity,
        "restore_contract": restored_contract,
    }


def _current_database_contract(
    *,
    current_engine: str,
    identity: dict[str, str],
) -> dict[str, object]:
    migration_rows = MigrationRecorder(connection).applied_migrations().keys()
    if current_engine == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            server_version_num = int(cursor.fetchone()[0])
        database_version = str(server_version_num // 10_000)
        database_version_scope = "server_major"
    elif current_engine == "sqlite":
        database_version = sqlite3.sqlite_version
        database_version_scope = "library"
    else:
        raise TenantOperationsPackError(
            "[TENANT_PACK_ENGINE_UNSUPPORTED] このDB種別には対応していません。"
        )
    try:
        return backup_restore_contract.build_restore_contract(
            database_engine=current_engine,
            database_version=database_version,
            database_version_scope=database_version_scope,
            installation_id=identity["installation_id"],
            runtime_kind=identity["runtime_kind"],
            migration_rows=migration_rows,
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_CURRENT_CONTRACT_INVALID] 現在の製品DB契約を確認できません。"
        ) from exc


def _collect_operations_source_members(
    platform_root: Path,
    *,
    tenant_payload_paths: _TenantPayloadPaths,
    platform_runtime_database_exclusions: set[str],
    tenant_runtime_database_exclusions: set[str],
) -> tuple[list[object], list[dict[str, str]], list[dict[str, str]]]:
    del platform_root, platform_runtime_database_exclusions
    members = []
    selection: list[dict[str, str]] = []

    env_path = tenant_payload_paths.root / ".env"
    if ".env" in tenant_runtime_database_exclusions:
        raise TenantOperationsPackError(
            "[TENANT_PACK_ENV_IS_LIVE_DATABASE] "
            ".envが稼働中SQLite DBとして設定されているため収録できません。"
        )
    if not os.path.lexists(env_path):
        raise TenantOperationsPackError(
            "[TENANT_PACK_ENV_REQUIRED] active tenant rootの.envが見つかりません。"
        )
    members.append(
        _archive._source_file_archive_member(
            env_path,
            SOURCE_ENV_PATH,
            category="source_env_reference",
            private=True,
        )
    )
    env_content = _archive._read_stable_regular_file(
        env_path,
        max_bytes=1024 * 1024,
    )
    env_keys = _classified_env_keys(env_content)
    selection.append(_selection_row(".env", SOURCE_ENV_PATH, included=True))

    policy_root = tenant_payload_paths.policy_root
    if not os.path.lexists(policy_root):
        raise TenantOperationsPackError(
            "[TENANT_PACK_POLICY_REQUIRED] tenant policy directoryが見つかりません。"
        )
    policy_members = _archive._collect_tree_archive_members(
        policy_root,
        TENANT_POLICY_ARCHIVE_ROOT,
        category="tenant_policy",
        excluded=lambda path, is_dir: (
            _archive._is_workspace_relative_file_excluded(
                Path("config/tenant_policy/default") / path,
                is_dir=is_dir,
                excluded_relative_files=tenant_runtime_database_exclusions,
            )
        ),
        private=True,
    )
    policy_files = [
        member
        for member in policy_members
        if member.member_type == "file"
    ]
    if not policy_files or any(
        Path(member.archive_path).suffix.casefold() != ".json"
        for member in policy_files
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_POLICY_INVALID] tenant policyはJSON fileだけを収録できます。"
        )
    for member in policy_files:
        try:
            policy_payload = json.loads(
                _archive._read_stable_regular_file(
                    member.source_path,
                    max_bytes=4 * 1024 * 1024,
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TenantOperationsPackError(
                "[TENANT_PACK_POLICY_INVALID] tenant policyをJSONとして検証できません。"
            ) from exc
        if not isinstance(policy_payload, (dict, list)):
            raise TenantOperationsPackError(
                "[TENANT_PACK_POLICY_INVALID] tenant policyのJSON構造が不正です。"
            )
    members.extend(policy_members)
    selection.append(
        _selection_row(
            "config/tenant_policy/default",
            TENANT_POLICY_ARCHIVE_ROOT.as_posix(),
            included=True,
        )
    )

    preferences_root = tenant_payload_paths.preferences_root
    preferences_exist = os.path.lexists(preferences_root)
    if preferences_exist:
        preference_members = _archive._collect_tree_archive_members(
            preferences_root,
            TENANT_PREFERENCES_ARCHIVE_ROOT,
            category="tenant_preferences",
            excluded=lambda path, is_dir: (
                _archive._is_workspace_relative_file_excluded(
                    Path("config/tenant_preferences") / path,
                    is_dir=is_dir,
                    excluded_relative_files=tenant_runtime_database_exclusions,
                )
            ),
            private=True,
        )
        preference_files = [
            member
            for member in preference_members
            if member.member_type == "file"
        ]
        if any(
            Path(member.archive_path).suffix.casefold() != ".json"
            for member in preference_files
        ):
            raise TenantOperationsPackError(
                "[TENANT_PACK_PREFERENCES_INVALID] "
                "tenant preferencesはJSON fileだけを収録できます。"
            )
        for member in preference_files:
            if member.source_path.name == ui_appearance.UI_APPEARANCE_FILENAME:
                try:
                    ui_appearance.load_ui_appearance(path=member.source_path)
                except ui_appearance.UiAppearanceError as exc:
                    raise TenantOperationsPackError(
                        "[TENANT_PACK_PREFERENCES_INVALID] "
                        "表示設定JSONを検証できません。"
                    ) from exc
        members.extend(preference_members)
    selection.append(
        _selection_row(
            "config/tenant_preferences",
            TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix(),
            included=preferences_exist,
        )
    )

    private_root = tenant_payload_paths.private_root
    private_exists = os.path.lexists(private_root)
    if private_exists:
        members.extend(
            _archive._collect_tree_archive_members(
                private_root,
                PRIVATE_PAYLOAD_ARCHIVE_ROOT,
                category="private_payload",
                excluded=lambda path, is_dir: (
                    _archive._is_workspace_relative_file_excluded(
                        Path("data/private") / path,
                        is_dir=is_dir,
                        excluded_relative_files=tenant_runtime_database_exclusions,
                    )
                ),
                private=True,
            )
        )
    selection.append(
        _selection_row(
            "data/private",
            PRIVATE_PAYLOAD_ARCHIVE_ROOT.as_posix(),
            included=private_exists,
        )
    )

    registry_path = tenant_payload_paths.source_registry_path
    registry_exists = os.path.lexists(registry_path)
    if (
        registry_exists
        and "data/runtime/source_registry.json"
        in tenant_runtime_database_exclusions
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_SOURCE_REGISTRY_IS_LIVE_DATABASE] "
            "source registryが稼働中SQLite DBとして設定されているため収録できません。"
        )
    if registry_exists:
        members.append(
            _archive._source_file_archive_member(
                registry_path,
                SOURCE_REGISTRY_ARCHIVE_PATH.as_posix(),
                category="source_registry",
                private=True,
            )
        )
    selection.append(
        _selection_row(
            "data/runtime/source_registry.json",
            SOURCE_REGISTRY_ARCHIVE_PATH.as_posix(),
            included=registry_exists,
        )
    )

    generated_root = tenant_payload_paths.generated_root
    generated_exists = os.path.lexists(generated_root)
    if generated_exists:
        members.extend(
            _archive._collect_tree_archive_members(
                generated_root,
                GENERATED_REFERENCE_ARCHIVE_ROOT,
                category="generated_reference",
                excluded=lambda path, is_dir: (
                    _is_generated_reference_excluded(path, is_dir)
                    or _archive._is_workspace_relative_file_excluded(
                        Path("data/generated") / path,
                        is_dir=is_dir,
                        excluded_relative_files=tenant_runtime_database_exclusions,
                    )
                ),
                private=True,
            )
        )
    selection.append(
        _selection_row(
            "data/generated",
            GENERATED_REFERENCE_ARCHIVE_ROOT.as_posix(),
            included=generated_exists,
        )
    )

    _archive._validate_runtime_source_registry_snapshot(
        tenant_payload_paths.root,
        members,
        selection,
    )
    members = sorted(members, key=lambda member: member.archive_path)
    _archive._validate_archive_member_set(
        _archive._with_archive_parent_directories(members)
    )
    return members, selection, env_keys


def _build_operations_manifest(
    *,
    source_state: dict[str, object],
    source_members: list[object],
    backup_database_member,
    backup_manifest_member,
    source_selection: list[dict[str, str]],
    env_keys: list[dict[str, str]],
    verification_content: bytes,
    git_snapshot: dict[str, object],
    root_dir: str,
    created_at,
) -> dict[str, object]:
    policy_members = [
        member.manifest_row()
        for member in source_members
        if member.category == "tenant_policy" and member.member_type == "file"
    ]
    private_file_count = sum(
        1
        for member in source_members
        if member.category == "private_payload" and member.member_type == "file"
    )
    generated_file_count = sum(
        1
        for member in source_members
        if member.category == "generated_reference" and member.member_type == "file"
    )
    backup_state = source_state["backup"]
    return {
        "package_kind": PACKAGE_KIND,
        "package_version": PACKAGE_VERSION,
        "package_root": root_dir,
        "created_at": timezone.localtime(created_at).isoformat(),
        "privacy_classification": PRIVACY_CLASSIFICATION,
        "required_application": {
            "git_commit": git_snapshot["head"],
            "git_branch": git_snapshot["branch"],
            "source_tree_clean": True,
        },
        "database_backup": {
            "backup_run_id": backup_state["backup_run_id"],
            "database_engine": backup_state["database_engine"],
            "status": backup_state["status"],
            "trigger_kind": backup_state["trigger_kind"],
            "backup_file_name": Path(backup_database_member.archive_path).name,
            "archive_path": backup_database_member.archive_path,
            "backup_file_size": backup_database_member.size,
            "backup_sha256": backup_database_member.sha256,
            "manifest_file_name": Path(backup_manifest_member.archive_path).name,
            "manifest_archive_path": backup_manifest_member.archive_path,
            "manifest_sha256": backup_manifest_member.sha256,
            "finished_at": backup_state["finished_at"],
            "updated_at": backup_state["updated_at"],
        },
        "restore_verification": {
            **source_state["verification"],
            "summary_path": VERIFICATION_SUMMARY_PATH,
            "summary_sha256": _sha256_bytes(verification_content),
        },
        "database_contract": source_state["restore_contract"],
        "runtime_identity": source_state["runtime_identity"],
        "tenant_policy": {
            "archive_root": TENANT_POLICY_ARCHIVE_ROOT.as_posix(),
            "file_count": len(policy_members),
            "sha256": backup_restore_contract.canonical_json_sha256(policy_members),
        },
        "payload": {
            "selection": source_selection,
            "private_file_count": private_file_count,
            "generated_reference_file_count": generated_file_count,
            "source_inventory_sha256": backup_restore_contract.canonical_json_sha256(
                [member.manifest_row() for member in source_members]
            ),
        },
        "environment_reference": {
            "path": SOURCE_ENV_PATH,
            "keys": env_keys,
            "raw_env_auto_apply": False,
        },
        "safety_contract": SAFETY_CONTRACT,
    }


def _render_verification_summary(source_state: dict[str, object]) -> bytes:
    verification = source_state["verification"]
    return _json_bytes(
        {
            "backup_run_id": verification["backup_run_id"],
            "verification_run_id": verification["verification_run_id"],
            "status": verification["status"],
            "finished_at": verification["finished_at"],
            "summary": verification["summary"],
        }
    )


def _render_readme() -> str:
    return """# TempleDB テナント運用パック

このarchiveは、検証済みDB backup、寺院方針、private資産、source registry、
UIから変更するtenant preferences、元machineの`.env`参照、
再生成可能な由来資料をまとめた極秘の移送物です。

- demo DBを製品DBへ昇格するものではありません。
- `reference/source.env`は値を確認する資料であり、移行先へ自動適用しません。
- 移行先では別のproduct workspace、DB、machine profileを新規作成します。
- 独立verifyと隔離applyが完了するまで、外部同期と自動処理を有効にしません。
- Primary切替、Tailscale変更、systemd/Caddy有効化はこのpack作成に含みません。
- SHA256は破損検知用であり暗号化・署名ではありません。暗号化済み媒体で扱ってください。
"""


def _classified_env_keys(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_ENV_INVALID] .envはUTF-8で読み取れる必要があります。"
        ) from exc
    keys: set[str] = set()
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, _value = stripped.partition("=")
        key = key.strip()
        if not separator or not _ENV_KEY_RE.fullmatch(key):
            raise TenantOperationsPackError(
                "[TENANT_PACK_ENV_INVALID] .envに解釈できない設定行があります。"
            )
        if key in keys:
            raise TenantOperationsPackError(
                "[TENANT_PACK_ENV_DUPLICATE_KEY] .envに重複した設定keyがあります。"
            )
        keys.add(key)
    return [
        {
            "key": key,
            "classification": _classify_env_key(key),
        }
        for key in sorted(keys)
    ]


def _classify_env_key(key: str) -> str:
    upper_key = key.upper()
    if any(marker in upper_key for marker in _SECRET_KEY_MARKERS):
        return "secret"
    if any(marker in upper_key for marker in _TUNING_KEY_MARKERS):
        return "tuning"
    if upper_key.startswith(("DATABASE_", "DJANGO_", "TEMPLEDB_")):
        return "machine"
    return "review-required"


def _is_generated_reference_excluded(relative_path: Path, is_dir: bool) -> bool:
    return _archive._is_generated_snapshot_excluded(
        relative_path,
        is_dir,
    ) or _archive._is_runtime_snapshot_excluded(relative_path, is_dir)


def _backup_run_snapshot(backup_run) -> dict[str, object]:
    return {
        "backup_run_id": backup_run.pk,
        "database_engine": backup_run.database_engine,
        "status": backup_run.status,
        "trigger_kind": backup_run.trigger_kind,
        "backup_file_name": backup_run.backup_file_name,
        "backup_file_size": backup_run.backup_file_size,
        "backup_sha256": str(backup_run.backup_sha256 or "").lower(),
        "finished_at": _isoformat_or_none(backup_run.finished_at),
        "updated_at": _isoformat_or_none(backup_run.updated_at),
    }


def _verification_run_snapshot(
    verification: DatabaseBackupVerificationRun,
) -> dict[str, object]:
    return {
        "backup_run_id": verification.backup_run_id,
        "verification_run_id": verification.pk,
        "status": verification.status,
        "trigger_kind": verification.trigger_kind,
        "finished_at": _isoformat_or_none(verification.finished_at),
        "updated_at": _isoformat_or_none(verification.updated_at),
        "summary": verification.verification_summary,
        "summary_sha256": backup_restore_contract.canonical_json_sha256(
            verification.verification_summary
        ),
    }


def _normalized_product_identity(identity: DatabaseRuntimeIdentity) -> dict[str, str]:
    try:
        installation_id = uuid.UUID(str(identity.installation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_IDENTITY_INVALID] 現在のDB識別子が不正です。"
        ) from exc
    if installation_id.int == 0 or identity.runtime_kind != "product":
        raise TenantOperationsPackError(
            "[TENANT_PACK_PRODUCT_REQUIRED] 製品DBだけを運用パックにできます。"
        )
    return {
        "installation_id": str(installation_id),
        "runtime_kind": "product",
    }


def _tenant_payload_paths(platform_root: Path) -> _TenantPayloadPaths:
    canonical_tenant_root = _validated_tenant_root(runtime_paths.tenant_root())
    canonical_paths = {
        "policy_root": tenant_policy.tenant_policy_root(),
        "preferences_root": runtime_paths.tenant_preferences_root(),
        "private_root": runtime_paths.private_root(),
        "source_registry_path": runtime_paths.runtime_source_registry_path(),
        "generated_root": runtime_paths.generated_root(),
    }
    normalized_paths = {
        name: _validated_path_within_tenant_root(
            raw_path,
            tenant_root=canonical_tenant_root,
        )
        for name, raw_path in canonical_paths.items()
    }

    if canonical_tenant_root != _validated_tenant_root(runtime_paths.BASE_DIR):
        payload_paths = _TenantPayloadPaths(
            root=canonical_tenant_root,
            **normalized_paths,
        )
    else:
        # ``workspace_root`` is a long-standing public test/packaging seam. When no
        # tenant root is configured, retain its old meaning by rebasing the
        # canonical tenant layout below the caller-provided Platform root.
        rebased_paths = {
            name: platform_root / path.relative_to(canonical_tenant_root)
            for name, path in normalized_paths.items()
        }
        payload_paths = _TenantPayloadPaths(
            root=platform_root,
            **rebased_paths,
        )

    try:
        _archive._validate_migration_source_roots(
            platform_root,
            payload_paths.root,
        )
    except _archive._UnsafeArchiveSourceError as exc:
        # Operations packs contain only the explicitly enumerated tenant
        # payload (the Platform source tree is represented by its clean commit),
        # so the active, validated product instance may live at the canonical
        # Platform/instances/product path. Arbitrary nested roots remain
        # forbidden because they do not have the current-pointer contract.
        try:
            selection = instance_runtime.selected_instance(
                platform_root=platform_root,
            )
        except instance_runtime.InstanceSelectionError as selection_exc:
            raise TenantOperationsPackError(
                f"[TENANT_PACK_SOURCE_ROOT_INVALID] {exc}"
            ) from selection_exc
        if (
            selection is None
            or selection.name != "product"
            or selection.root != payload_paths.root
        ):
            raise TenantOperationsPackError(
                f"[TENANT_PACK_SOURCE_ROOT_INVALID] {exc}"
            ) from exc
    return payload_paths


def _validated_workspace_root(raw_root: Path) -> Path:
    root = Path(os.path.abspath(raw_root.expanduser()))
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_WORKSPACE_INVALID] workspace rootを確認できません。"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise TenantOperationsPackError(
            "[TENANT_PACK_WORKSPACE_INVALID] workspace rootが通常directoryではありません。"
        )
    return root


def _validated_tenant_root(raw_root: Path) -> Path:
    root = Path(os.path.abspath(Path(raw_root).expanduser()))
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_TENANT_ROOT_INVALID] tenant rootを確認できません。"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise TenantOperationsPackError(
            "[TENANT_PACK_TENANT_ROOT_INVALID] "
            "tenant rootが通常directoryではありません。"
        )
    return root


def _validated_path_within_tenant_root(
    raw_path: Path,
    *,
    tenant_root: Path,
) -> Path:
    path = Path(os.path.abspath(Path(raw_path).expanduser()))
    if path == tenant_root or not path.is_relative_to(tenant_root):
        raise TenantOperationsPackError(
            "[TENANT_PACK_TENANT_PATH_INVALID] "
            "tenant payload pathがtenant root配下ではありません。"
        )
    return path


def _validated_output_root(
    raw_root: Path,
    *,
    workspace_root: Path,
    tenant_root: Path,
) -> Path:
    root = Path(os.path.abspath(raw_root.expanduser()))
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise TenantOperationsPackError(
            "[TENANT_PACK_OUTPUT_ROOT_REQUIRED] "
            "既存のowner-only出力directoryを指定してください。"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_OUTPUT_ROOT_UNSAFE] "
            "出力directoryは現在user所有の0700である必要があります。"
        )
    resolved_root = root.resolve(strict=True)
    resolved_workspace = workspace_root.resolve(strict=True)
    resolved_tenant_root = tenant_root.resolve(strict=True)
    protected_roots = {resolved_workspace, resolved_tenant_root}
    if any(
        resolved_root == protected_root
        or resolved_root.is_relative_to(protected_root)
        or protected_root.is_relative_to(resolved_root)
        for protected_root in protected_roots
    ):
        raise TenantOperationsPackError(
            "[TENANT_PACK_OUTPUT_ROOT_INSIDE_WORKSPACE] "
            "出力directoryはPlatform workspaceおよびtenant rootと"
            "重ならない場所を指定してください。"
        )
    return resolved_root


def _build_package_root(backup_run, *, created_at) -> str:
    timestamp = timezone.localtime(created_at).strftime("%Y%m%d_%H%M%S")
    root = f"templedb_tenant_operations_{timestamp}_run{int(backup_run.pk)}"
    _archive._validated_archive_path(root)
    return root


def _selection_row(
    source_path: str,
    archive_path: str,
    *,
    included: bool,
) -> dict[str, str]:
    return {
        "source_path": source_path,
        "archive_path": archive_path,
        "status": "included" if included else "absent",
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _isoformat_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "PACKAGE_KIND",
    "PACKAGE_VERSION",
    "TenantOperationsPackError",
    "create_tenant_operations_pack",
    "export_tenant_operations_pack",
]
