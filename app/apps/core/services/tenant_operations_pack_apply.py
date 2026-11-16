from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from django.conf import settings

from config import runtime_paths

from . import (
    database_transfer_postgresql,
    handoff_repository_snapshot,
    runtime_role,
    tenant_operations_pack_verification,
)
from .tenant_operations_pack_contract import (
    GENERATED_REFERENCE_ARCHIVE_ROOT,
    PRIVATE_PAYLOAD_ARCHIVE_ROOT,
    SOURCE_ENV_PATH,
    SOURCE_REGISTRY_ARCHIVE_PATH,
    TENANT_POLICY_ARCHIVE_ROOT,
    TENANT_PREFERENCES_ARCHIVE_ROOT,
)

APPLY_RECEIPT_NAME = "tenant-pack-apply.json"
APPLY_COMPLETION_MARKER_NAME = ".complete"
APPLY_RECEIPT_VERSION = 2
_STAGING_NAME_PREFIX = ".templedb-candidate-applying-"
_AT_FDCWD = -100
_LINUX_RENAME_NOREPLACE = 1
_DARWIN_RENAME_EXCL = 0x00000004


class TenantOperationsPackApplyError(RuntimeError):
    """Raised when an isolated tenant-pack candidate cannot be created safely."""


@dataclass(frozen=True)
class TenantOperationsPackApplyResult:
    candidate_root: Path
    database_name: str
    database_oid: int
    receipt_path: Path
    completion_marker_path: Path
    archive_sha256: str
    backup_run_id: int
    verification_run_id: int
    source_postgresql_major: int
    target_postgresql_major: int
    connections_allowed: bool


@dataclass
class _OpenMappedFile:
    source_path: str
    destination_path: str | None
    category: str
    expected_size: int
    expected_sha256: str
    descriptor: int | None
    digest: Any
    written_size: int = 0


class _CandidateRootConsumer:
    """Writes only allowlisted tenant payload into a new private staging root."""

    def __init__(self, candidate_root: Path) -> None:
        self.candidate_root = candidate_root
        self.parent = candidate_root.parent
        self.staging_root = self.parent / (
            f"{_STAGING_NAME_PREFIX}{uuid.uuid4().hex}"
        )
        os.mkdir(self.staging_root, mode=0o700)
        os.chmod(self.staging_root, 0o700)
        self._root_descriptor: int | None = _open_private_directory(
            self.staging_root
        )
        self._current: _OpenMappedFile | None = None
        self._mapped_destinations: set[str] = set()
        self._mapping_rows: list[dict[str, object]] = []
        self._category_counts: Counter[str] = Counter()
        self._database_backup_path: Path | None = None
        self._database_manifest_path: Path | None = None
        self._stream_completed = False
        self._published = False
        self._aborted = False

    @property
    def database_backup_path(self) -> Path:
        if self._database_backup_path is None:
            raise TenantOperationsPackApplyError(
                "運用パックのPostgreSQL backupを一意に配置できませんでした。"
            )
        return self._database_backup_path

    @property
    def database_manifest_path(self) -> Path:
        if self._database_manifest_path is None:
            raise TenantOperationsPackApplyError(
                "運用パックのbackup manifestを一意に配置できませんでした。"
            )
        return self._database_manifest_path

    def directory(self, path: str, *, category: str) -> None:
        del path, category
        self._require_streaming()
        if self._current is not None:
            raise TenantOperationsPackApplyError(
                "file書込み中にdirectory memberを受信しました。"
            )

    def start_file(
        self,
        path: str,
        *,
        category: str,
        size: int,
        sha256: str,
    ) -> None:
        self._require_streaming()
        if self._current is not None:
            raise TenantOperationsPackApplyError(
                "前のfile書込みが完了する前に次のfileを受信しました。"
            )
        destination_path = _mapped_candidate_path(path, category=category)
        descriptor: int | None = None
        if destination_path is not None:
            if destination_path in self._mapped_destinations:
                raise TenantOperationsPackApplyError(
                    "運用packの配置先pathが重複しています。"
                )
            self._mapped_destinations.add(destination_path)
            descriptor = _create_private_file_at(
                self._root_descriptor,
                destination_path,
            )
        self._current = _OpenMappedFile(
            source_path=path,
            destination_path=destination_path,
            category=category,
            expected_size=size,
            expected_sha256=sha256,
            descriptor=descriptor,
            digest=hashlib.sha256(),
        )

    def write_file_chunk(self, path: str, chunk: bytes) -> None:
        current = self._required_current(path)
        if current.descriptor is None:
            return
        current.digest.update(chunk)
        current.written_size += len(chunk)
        offset = 0
        while offset < len(chunk):
            written = os.write(current.descriptor, chunk[offset:])
            if written <= 0:
                raise TenantOperationsPackApplyError(
                    "candidate fileへ完全に書き込めませんでした。"
                )
            offset += written

    def finish_file(self, path: str, *, sha256: str) -> None:
        current = self._required_current(path)
        self._current = None
        if current.descriptor is None:
            return
        descriptor = current.descriptor
        try:
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            digest = current.digest.hexdigest()
            if (
                current.written_size != current.expected_size
                or metadata.st_size != current.expected_size
                or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or digest != current.expected_sha256
                or sha256 != current.expected_sha256
            ):
                raise TenantOperationsPackApplyError(
                    "candidate fileのsize、modeまたはSHA256が一致しません。"
                )
        finally:
            os.close(descriptor)

        assert current.destination_path is not None
        self._mapping_rows.append(
            {
                "destination": current.destination_path,
                "category": current.category,
                "size": current.expected_size,
                "sha256": current.expected_sha256,
            }
        )
        self._category_counts[current.category] += 1
        destination = self.staging_root / current.destination_path
        if current.category == "database_backup":
            if self._database_backup_path is not None:
                raise TenantOperationsPackApplyError(
                    "運用パックに複数のdatabase backupがあります。"
                )
            self._database_backup_path = destination
        elif current.category == "database_backup_manifest":
            if self._database_manifest_path is not None:
                raise TenantOperationsPackApplyError(
                    "運用パックに複数のbackup manifestがあります。"
                )
            self._database_manifest_path = destination

    def complete(self) -> None:
        self._require_streaming()
        if self._current is not None:
            raise TenantOperationsPackApplyError(
                "未完了のcandidate fileがあります。"
            )
        _ = self.database_backup_path
        _ = self.database_manifest_path
        _fsync_directory_tree(self.staging_root)
        self._stream_completed = True

    def abort(self) -> None:
        if self._published or self._aborted:
            return
        current = self._current
        self._current = None
        if current is not None and current.descriptor is not None:
            os.close(current.descriptor)
        self._close_root_descriptor()
        if self.staging_root.exists():
            shutil.rmtree(self.staging_root)
        self._aborted = True

    @property
    def published(self) -> bool:
        return self._published

    def finalize(
        self,
        *,
        pack_result: dict[str, object],
        platform_commit: str,
        source_env_sha256: str,
        database_result,
    ) -> TenantOperationsPackApplyResult:
        if (
            not self._stream_completed
            or self._published
            or self._aborted
            or self._current is not None
        ):
            raise TenantOperationsPackApplyError(
                "candidate rootを確定できる状態ではありません。"
            )
        if database_result.connections_allowed is not False:
            raise TenantOperationsPackApplyError(
                "PostgreSQL candidateが凍結されていないため公開できません。"
            )
        apply_root = self.staging_root / ".apply"
        if not apply_root.is_dir() or apply_root.is_symlink():
            raise TenantOperationsPackApplyError(
                "candidateの一時database payloadを確認できません。"
            )
        shutil.rmtree(apply_root)
        assert self._root_descriptor is not None
        for relative_directory in (
            "config/tenant_preferences",
            "data/generated",
            "data/private",
            "data/runtime",
        ):
            _ensure_private_directory_at(
                self._root_descriptor,
                relative_directory,
            )
        env_sentinel_content = b""
        _write_private_file(
            self.staging_root / ".env",
            env_sentinel_content,
        )
        self._mapping_rows.append(
            {
                "destination": ".env",
                "category": "runtime_env_sentinel",
                "size": 0,
                "sha256": hashlib.sha256(env_sentinel_content).hexdigest(),
            }
        )
        self._category_counts["runtime_env_sentinel"] += 1
        mapping_hash = _mapping_sha256(self._mapping_rows)
        candidate_mapping_rows = [
            row
            for row in self._mapping_rows
            if row["category"]
            not in {"database_backup", "database_backup_manifest"}
        ]
        candidate_category_counts = Counter(
            str(row["category"]) for row in candidate_mapping_rows
        )
        receipt = {
            "format": "templedb-tenant-pack-apply",
            "version": APPLY_RECEIPT_VERSION,
            "status": "frozen-staging-candidate",
            "created_at": datetime.now(UTC).isoformat(),
            "candidate_root": str(self.candidate_root),
            "runtime_role": "staging",
            "external_effects_enabled": False,
            "primary_cutover_completed": False,
            "source_env_applied": False,
            "source_env_sha256": source_env_sha256,
            "package_kind": pack_result["package_kind"],
            "package_root": pack_result["package_root"],
            "archive_sha256": pack_result["archive_sha256"],
            "platform_commit": platform_commit,
            "installation_id": pack_result["installation_id"],
            "backup_run_id": pack_result["backup_run_id"],
            "verification_run_id": pack_result["verification_run_id"],
            "database_engine": pack_result["database_engine"],
            "database_version": pack_result["database_version"],
            "database": {
                "name": database_result.database_name,
                "oid": database_result.database_oid,
                "connections_allowed": database_result.connections_allowed,
                "ownership_token_sha256": database_result.ownership_token_sha256,
                "source_postgresql_major": database_result.validation_summary[
                    "source_postgresql_major"
                ],
                "target_postgresql_major": database_result.validation_summary[
                    "target_postgresql_major"
                ],
            },
            "database_validation": database_result.validation_summary,
            "mapping": {
                "file_count": len(self._mapping_rows),
                "sha256": mapping_hash,
                "category_counts": dict(sorted(self._category_counts.items())),
            },
            "candidate_mapping": {
                "file_count": len(candidate_mapping_rows),
                "sha256": _mapping_sha256(candidate_mapping_rows),
                "category_counts": dict(sorted(candidate_category_counts.items())),
            },
        }
        receipt_content = _json_bytes(receipt)
        _write_private_file(
            self.staging_root / APPLY_RECEIPT_NAME,
            receipt_content,
        )
        receipt_sha256 = hashlib.sha256(receipt_content).hexdigest()
        marker_content = _json_bytes(
            {
                "format": "templedb-tenant-pack-apply-complete",
                "version": 1,
                "receipt_sha256": receipt_sha256,
                "database_name": database_result.database_name,
                "connections_allowed": False,
            }
        )
        _write_private_file(
            self.staging_root / APPLY_COMPLETION_MARKER_NAME,
            marker_content,
        )
        _fsync_directory_tree(self.staging_root)
        _rename_directory_noreplace(
            self.staging_root,
            self.candidate_root,
        )
        self._published = True
        _fsync_directory(self.parent)
        self._close_root_descriptor()
        return TenantOperationsPackApplyResult(
            candidate_root=self.candidate_root,
            database_name=database_result.database_name,
            database_oid=database_result.database_oid,
            receipt_path=self.candidate_root / APPLY_RECEIPT_NAME,
            completion_marker_path=(
                self.candidate_root / APPLY_COMPLETION_MARKER_NAME
            ),
            archive_sha256=str(pack_result["archive_sha256"]),
            backup_run_id=int(pack_result["backup_run_id"]),
            verification_run_id=int(pack_result["verification_run_id"]),
            source_postgresql_major=int(
                database_result.validation_summary[
                    "source_postgresql_major"
                ]
            ),
            target_postgresql_major=int(
                database_result.validation_summary[
                    "target_postgresql_major"
                ]
            ),
            connections_allowed=False,
        )

    def _require_streaming(self) -> None:
        if self._stream_completed or self._published or self._aborted:
            raise TenantOperationsPackApplyError(
                "candidate consumerは再利用できません。"
            )

    def _required_current(self, path: str) -> _OpenMappedFile:
        current = self._current
        if current is None or current.source_path != path:
            raise TenantOperationsPackApplyError(
                "candidate fileのstream順序が一致しません。"
            )
        return current

    def _close_root_descriptor(self) -> None:
        if self._root_descriptor is not None:
            os.close(self._root_descriptor)
            self._root_descriptor = None


def apply_tenant_operations_pack(
    archive_path: str | Path,
    *,
    expected_archive_sha256: str,
    expected_git_commit: str,
    expected_installation_id: str,
    candidate_tenant_root: str | Path,
    confirm_candidate_tenant_root: str,
    target_database_name: str,
    confirm_target_database_name: str,
    expected_target_postgresql_major: int,
    platform_root: str | Path | None = None,
    active_tenant_root: str | Path | None = None,
) -> TenantOperationsPackApplyResult:
    if runtime_role.current_runtime_role() != runtime_role.RUNTIME_ROLE_STAGING:
        raise TenantOperationsPackApplyError(
            "tenant operations packの隔離applyは"
            "TEMPLEDB_RUNTIME_ROLE=stagingでだけ実行できます。"
        )
    target_postgresql_major = _validated_postgresql_major(
        expected_target_postgresql_major
    )
    resolved_platform_root = _resolved_existing_directory(
        Path(platform_root) if platform_root is not None else Path(settings.BASE_DIR),
        label="Platform root",
    )
    resolved_active_tenant_root = _resolved_existing_directory(
        (
            Path(active_tenant_root)
            if active_tenant_root is not None
            else runtime_paths.tenant_root()
        ),
        label="active tenant root",
    )
    candidate_root = _validated_candidate_root(
        Path(candidate_tenant_root),
        confirmation=confirm_candidate_tenant_root,
        protected_roots=(
            resolved_platform_root,
            resolved_active_tenant_root,
        ),
        archive_path=Path(archive_path),
    )
    try:
        target_name = (
            database_transfer_postgresql.validate_postgresql_clone_database_name(
                target_database_name
            )
        )
    except database_transfer_postgresql.DatabaseTransferError as exc:
        raise TenantOperationsPackApplyError(
            "target PostgreSQL DB名がcandidate規則に一致しません。"
        ) from exc
    if confirm_target_database_name.strip() != target_name:
        raise TenantOperationsPackApplyError(
            "target PostgreSQL DB名の確認値が一致しません。"
        )
    _assert_platform_commit(
        resolved_platform_root,
        expected_git_commit=expected_git_commit,
    )

    consumer: _CandidateRootConsumer | None = None
    frozen_database_created = False
    try:
        with (
            tenant_operations_pack_verification.open_verified_tenant_operations_pack(
                archive_path,
                expected_archive_sha256=expected_archive_sha256,
                expected_git_commit=expected_git_commit,
                expected_installation_id=expected_installation_id,
            )
        ) as session:
            pack_result = session.result
            if pack_result["database_engine"] != "postgresql":
                raise TenantOperationsPackApplyError(
                    "工程5の隔離applyはPostgreSQL運用packだけを受け付けます。"
                )
            source_env_row = session.archive_inventory.get(SOURCE_ENV_PATH)
            if (
                not isinstance(source_env_row, dict)
                or not isinstance(source_env_row.get("sha256"), str)
            ):
                raise TenantOperationsPackApplyError(
                    "source.envの監査SHA256を確認できません。"
                )
            database_backup_row = _required_inventory_member(
                session.archive_inventory,
                category="database_backup",
            )
            consumer = _CandidateRootConsumer(candidate_root)
            session.stream_verified_members(consumer)
            if (
                consumer.database_backup_path.stat().st_size
                != database_backup_row["size"]
                or _sha256_file(consumer.database_backup_path)
                != database_backup_row["sha256"]
            ):
                raise TenantOperationsPackApplyError(
                    "配置後のPostgreSQL backupがpack inventoryと一致しません。"
                )
            database_result = (
                database_transfer_postgresql.create_frozen_postgresql_candidate_from_dump(
                    backup_file_path=consumer.database_backup_path,
                    expected_backup_size=int(database_backup_row["size"]),
                    expected_backup_sha256=str(database_backup_row["sha256"]),
                    backup_run_id=int(pack_result["backup_run_id"]),
                    target_database_name=target_name,
                    expected_restore_summary=session.restore_summary,
                    expected_installation_id=expected_installation_id,
                    expected_target_postgresql_major=target_postgresql_major,
                )
            )
            frozen_database_created = True
            return consumer.finalize(
                pack_result=pack_result,
                platform_commit=expected_git_commit,
                source_env_sha256=str(source_env_row["sha256"]),
                database_result=database_result,
            )
    except TenantOperationsPackApplyError as exc:
        cleanup_error, root_note = _abort_candidate_without_masking(
            consumer,
            failure=exc,
        )
        suffix = _candidate_failure_suffix(
            target_name=target_name,
            frozen_database_created=frozen_database_created,
            cleanup_error=cleanup_error,
            root_note=root_note,
        )
        if suffix:
            raise TenantOperationsPackApplyError(f"{exc}{suffix}") from exc
        raise
    except (
        tenant_operations_pack_verification.TenantOperationsPackVerificationError
    ) as exc:
        cleanup_error, root_note = _abort_candidate_without_masking(
            consumer,
            failure=exc,
        )
        suffix = _candidate_failure_suffix(
            target_name=target_name,
            frozen_database_created=False,
            cleanup_error=cleanup_error,
            root_note=root_note,
        )
        raise TenantOperationsPackApplyError(
            "tenant operations packの検証または安全配置に失敗しました。"
            f"{suffix}"
        ) from exc
    except database_transfer_postgresql.DatabaseTransferError as exc:
        cleanup_error, root_note = _abort_candidate_without_masking(
            consumer,
            failure=exc,
        )
        suffix = _candidate_failure_suffix(
            target_name=target_name,
            frozen_database_created=False,
            cleanup_error=cleanup_error,
            root_note=root_note,
        )
        raise TenantOperationsPackApplyError(
            "PostgreSQL candidateの作成に失敗しました。"
            f" target {target_name} とtoken付き一時DBの状態を確認してから"
            "再実行してください。所有不明DBは自動削除しません。"
            f"{suffix}"
        ) from exc
    except BaseException as exc:
        cleanup_error, root_note = _abort_candidate_without_masking(
            consumer,
            failure=exc,
        )
        suffix = _candidate_failure_suffix(
            target_name=target_name,
            frozen_database_created=frozen_database_created,
            cleanup_error=cleanup_error,
            root_note=root_note,
        )
        if suffix:
            raise TenantOperationsPackApplyError(
                f"tenant rootの確定に失敗しました。{suffix.lstrip()}"
            ) from exc
        raise


def _abort_candidate_without_masking(
    consumer: _CandidateRootConsumer | None,
    *,
    failure: BaseException,
) -> tuple[BaseException | None, str]:
    if consumer is None:
        return None, ""
    if consumer.published:
        return (
            None,
            f" candidate root {consumer.candidate_root} は既に公開済みです。"
            " 完了証跡を確認するまで再実行しないでください。",
        )
    try:
        consumer.abort()
    except BaseException as cleanup_error:
        failure.add_note(
            "candidate一時rootの中止処理にも失敗しました: "
            f"{cleanup_error.__class__.__name__}"
        )
        return (
            cleanup_error,
            f" candidate一時root {consumer.staging_root} が残っている"
            "可能性があります。",
        )
    return None, ""


def _candidate_failure_suffix(
    *,
    target_name: str,
    frozen_database_created: bool,
    cleanup_error: BaseException | None,
    root_note: str,
) -> str:
    notes: list[str] = []
    if frozen_database_created:
        notes.append(f"凍結DB {target_name} は自動削除していません。")
    if root_note:
        notes.append(root_note.strip())
    if cleanup_error is not None:
        notes.append("candidate一時rootの清掃にも失敗しました。")
    if not notes:
        return ""
    return " " + " ".join(notes)


def _mapped_candidate_path(path: str, *, category: str) -> str | None:
    pure_path = PurePosixPath(path)
    mapped: PurePosixPath | None
    if category == "tenant_policy":
        relative = pure_path.relative_to(TENANT_POLICY_ARCHIVE_ROOT)
        mapped = PurePosixPath("config/tenant_policy/default") / relative
    elif category == "tenant_preferences":
        relative = pure_path.relative_to(TENANT_PREFERENCES_ARCHIVE_ROOT)
        mapped = PurePosixPath("config/tenant_preferences") / relative
    elif category == "private_payload":
        relative = pure_path.relative_to(PRIVATE_PAYLOAD_ARCHIVE_ROOT)
        mapped = PurePosixPath("data/private") / relative
    elif category == "source_registry":
        if pure_path != SOURCE_REGISTRY_ARCHIVE_PATH:
            raise TenantOperationsPackApplyError(
                "source registryの配置元pathが不正です。"
            )
        mapped = PurePosixPath("data/runtime/source_registry.json")
    elif category == "generated_reference":
        relative = pure_path.relative_to(GENERATED_REFERENCE_ARCHIVE_ROOT)
        mapped = PurePosixPath("data/generated") / relative
    elif category in {"database_backup", "database_backup_manifest"}:
        if pure_path.parent != PurePosixPath("database"):
            raise TenantOperationsPackApplyError(
                "database payloadの配置元pathが不正です。"
            )
        mapped = PurePosixPath(".apply/database") / pure_path.name
    else:
        return None
    if (
        mapped.is_absolute()
        or any(part in {"", ".", ".."} for part in mapped.parts)
        or "\\" in mapped.as_posix()
    ):
        raise TenantOperationsPackApplyError(
            "candidateへの配置先pathが安全ではありません。"
        )
    return mapped.as_posix()


def _required_inventory_member(
    inventory: dict[str, dict[str, object]],
    *,
    category: str,
) -> dict[str, object]:
    matches = [
        row
        for row in inventory.values()
        if row.get("category") == category
    ]
    if len(matches) != 1:
        raise TenantOperationsPackApplyError(
            f"運用packの{category} memberを一意に確認できません。"
        )
    row = matches[0]
    size = row.get("size")
    sha256 = row.get("sha256")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or not isinstance(sha256, str)
        or len(sha256) != 64
    ):
        raise TenantOperationsPackApplyError(
            f"運用packの{category} metadataが不正です。"
        )
    return row


def _validated_postgresql_major(raw_major: object) -> int:
    if (
        isinstance(raw_major, bool)
        or not isinstance(raw_major, int)
        or not 10 <= raw_major <= 99
    ):
        raise TenantOperationsPackApplyError(
            "target PostgreSQL majorは10から99の整数で明示してください。"
        )
    return raw_major


def _validated_candidate_root(
    raw_root: Path,
    *,
    confirmation: str,
    protected_roots: tuple[Path, ...],
    archive_path: Path,
) -> Path:
    root = Path(os.path.abspath(raw_root.expanduser()))
    if not root.is_absolute() or confirmation.strip() != str(root):
        raise TenantOperationsPackApplyError(
            "candidate tenant rootは絶対pathと同じ確認値を指定してください。"
        )
    parent = _resolved_existing_directory(root.parent, label="candidate parent")
    metadata = parent.stat()
    if (
        metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or not os.access(parent, os.W_OK)
    ):
        raise TenantOperationsPackApplyError(
            "candidate parentは現在user所有の書込可能な0700 directoryにしてください。"
        )
    if root.exists() or root.is_symlink():
        raise TenantOperationsPackApplyError(
            "candidate tenant rootは存在しない新規pathを指定してください。"
        )
    for protected_root in protected_roots:
        if _paths_overlap(root, protected_root):
            raise TenantOperationsPackApplyError(
                "candidate tenant rootはPlatformまたはactive tenant rootと"
                "重ねられません。"
            )
    try:
        resolved_archive = archive_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise TenantOperationsPackApplyError(
            "tenant operations packを確認できません。"
        ) from exc
    if resolved_archive == root or resolved_archive.is_relative_to(root):
        raise TenantOperationsPackApplyError(
            "入力archiveをcandidate tenant root配下には置けません。"
        )
    return root


def _assert_platform_commit(
    platform_root: Path,
    *,
    expected_git_commit: str,
) -> None:
    try:
        snapshot = handoff_repository_snapshot.build_repository_snapshot(
            platform_root
        )
    except handoff_repository_snapshot.RepositorySnapshotError as exc:
        raise TenantOperationsPackApplyError(
            "Platform source snapshotを安全に確認できません。"
        ) from exc
    git = snapshot.get("git")
    summary = snapshot.get("summary")
    if not isinstance(git, dict) or not isinstance(summary, dict):
        raise TenantOperationsPackApplyError(
            "Platform source snapshotを確認できません。"
        )
    if (
        str(git.get("commit") or "").lower() != expected_git_commit.lower()
        or bool(git.get("tracked_dirty"))
        or int(git.get("untracked_omitted") or 0) != 0
        or int(summary.get("modified_count") or 0) != 0
        or int(summary.get("missing_count") or 0) != 0
    ):
        raise TenantOperationsPackApplyError(
            "Platformがpackのrequired commitと一致するcleanなsourceではありません。"
        )
    if not bool(git.get("available")):
        release_manifest = snapshot.get("release_manifest")
        if (
            not isinstance(release_manifest, dict)
            or not bool(git.get("unlisted_files_inspected"))
        ):
            raise TenantOperationsPackApplyError(
                "release Platformのsource manifest検証が完了していません。"
            )


def _resolved_existing_directory(raw_path: Path, *, label: str) -> Path:
    path = Path(os.path.abspath(raw_path.expanduser()))
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TenantOperationsPackApplyError(
            f"{label}を確認できません。"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or resolved != path
    ):
        raise TenantOperationsPackApplyError(
            f"{label}はsymlinkを含まない通常directoryにしてください。"
        )
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second
        or first.is_relative_to(second)
        or second.is_relative_to(first)
    )


def _open_private_directory(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise TenantOperationsPackApplyError(
            "candidate staging directoryがowner-onlyではありません。"
        )
    return descriptor


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    if source.parent != destination.parent:
        raise TenantOperationsPackApplyError(
            "candidate rootの公開元と確定先は同じ親directoryにしてください。"
        )
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        try:
            rename_function = library.renameat2
        except AttributeError as exc:
            raise TenantOperationsPackApplyError(
                "このLinuxではatomic no-clobber renameを利用できません。"
            ) from exc
        rename_function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_function.restype = ctypes.c_int
        arguments = (
            _AT_FDCWD,
            source_bytes,
            _AT_FDCWD,
            destination_bytes,
            _LINUX_RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":
        try:
            rename_function = library.renamex_np
        except AttributeError as exc:
            raise TenantOperationsPackApplyError(
                "このmacOSではatomic no-clobber renameを利用できません。"
            ) from exc
        rename_function.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_function.restype = ctypes.c_int
        arguments = (
            source_bytes,
            destination_bytes,
            _DARWIN_RENAME_EXCL,
        )
    else:
        raise TenantOperationsPackApplyError(
            "このOSではcandidate rootのatomic no-clobber公開を利用できません。"
        )
    ctypes.set_errno(0)
    result = rename_function(*arguments)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise TenantOperationsPackApplyError(
            "確定直前にcandidate rootが作成されたため上書きせず停止しました。"
        )
    raise OSError(
        error_number,
        os.strerror(error_number),
        str(destination),
    )


def _create_private_file_at(root_descriptor: int, relative_path: str) -> int:
    parts = PurePosixPath(relative_path).parts
    if not parts:
        raise TenantOperationsPackApplyError("candidate file pathが空です。")
    parent_descriptor = os.dup(root_descriptor)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_descriptor,
            )
            metadata = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                os.close(next_descriptor)
                raise TenantOperationsPackApplyError(
                    "candidate parent directoryが安全ではありません。"
                )
            os.fchmod(next_descriptor, 0o700)
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor
        return os.open(
            parts[-1],
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
    finally:
        os.close(parent_descriptor)


def _ensure_private_directory_at(root_descriptor: int, relative_path: str) -> None:
    parts = PurePosixPath(relative_path).parts
    if not parts:
        raise TenantOperationsPackApplyError("candidate directory pathが空です。")
    parent_descriptor = os.dup(root_descriptor)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_descriptor,
            )
            metadata = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                os.close(next_descriptor)
                raise TenantOperationsPackApplyError(
                    "candidate runtime directoryが安全ではありません。"
                )
            os.fchmod(next_descriptor, 0o700)
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _write_private_file(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise TenantOperationsPackApplyError(
                    "candidate receiptを書き込めませんでした。"
                )
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory_tree(root: Path) -> None:
    directories = [root]
    for current_root, directory_names, _file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        for directory_name in directory_names:
            child = current / directory_name
            if child.is_symlink():
                raise TenantOperationsPackApplyError(
                    "candidate rootにsymlinkが作成されました。"
                )
            directories.append(child)
    for directory in reversed(directories):
        _fsync_directory(directory)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_object:
        while chunk := file_object.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping_sha256(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        json.dumps(
            sorted(rows, key=lambda row: str(row["destination"])),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


__all__ = [
    "APPLY_COMPLETION_MARKER_NAME",
    "APPLY_RECEIPT_NAME",
    "TenantOperationsPackApplyError",
    "TenantOperationsPackApplyResult",
    "apply_tenant_operations_pack",
]
