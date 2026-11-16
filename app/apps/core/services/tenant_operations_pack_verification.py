from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tarfile
import unicodedata
import uuid
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

from . import backup_restore_contract
from .tenant_operations_pack_contract import (
    ARCHIVE_CHECKSUMS_PATH,
    ARCHIVE_MANIFEST_PATH,
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

ARCHIVE_MANIFEST_VERSION = 1
MAX_ARCHIVE_MEMBERS = 20_000
MAX_ARCHIVE_COMPRESSED_BYTES = 32 * 1024**3
MAX_ARCHIVE_FILE_BYTES = 16 * 1024**3
MAX_ARCHIVE_TOTAL_BYTES = 32 * 1024**3
MAX_OPERATIONS_MANIFEST_BYTES = 2 * 1024**2
MAX_ARCHIVE_MANIFEST_BYTES = 16 * 1024**2
MAX_CHECKSUMS_BYTES = 4 * 1024**2
MAX_RESTORE_SUMMARY_BYTES = 4 * 1024**2
MAX_BACKUP_MANIFEST_BYTES = 4 * 1024**2
MAX_SOURCE_REGISTRY_BYTES = 4 * 1024**2
MAX_SOURCE_ENV_BYTES = 1024**2
MAX_TENANT_PREFERENCE_BYTES = 64 * 1024
READ_CHUNK_BYTES = 1024**2
TAR_BLOCK_BYTES = 512

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_GIT_OBJECT_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_PACKAGE_ROOT_RE = re.compile(
    r"\Atempledb_tenant_operations_[0-9]{8}_[0-9]{6}_run[1-9][0-9]*\Z"
)
_ENV_KEY_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")
_RUNTIME_TRANSIENT_FILE_SUFFIXES = (
    ".pid",
    ".lock",
    ".guard",
    ".part",
    ".tmp",
    ".temp",
    ".swp",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".sqlite3-journal",
)
_GENERATED_CACHE_DIR_NAMES = {
    ".cache",
    "cache",
    "caches",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
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
_SOURCE_CATEGORIES = {
    "generated_reference",
    "private_payload",
    "source_env_reference",
    "source_registry",
    "tenant_policy",
    "tenant_preferences",
}
_ALLOWED_CATEGORIES = _SOURCE_CATEGORIES | {
    "archive_checksums",
    "archive_directory",
    "archive_manifest",
    "bundle_root",
    "database_backup",
    "database_backup_manifest",
    "operator_guide",
    "restore_verification",
    "tenant_operations_manifest",
}
_REQUIRED_CAPTURE_PATHS = frozenset(
    {
        OPERATIONS_MANIFEST_PATH,
        ARCHIVE_MANIFEST_PATH,
        ARCHIVE_CHECKSUMS_PATH,
        VERIFICATION_SUMMARY_PATH,
        SOURCE_ENV_PATH,
    }
)
_CAPTURE_LIMITS = {
    OPERATIONS_MANIFEST_PATH: MAX_OPERATIONS_MANIFEST_BYTES,
    ARCHIVE_MANIFEST_PATH: MAX_ARCHIVE_MANIFEST_BYTES,
    ARCHIVE_CHECKSUMS_PATH: MAX_CHECKSUMS_BYTES,
    VERIFICATION_SUMMARY_PATH: MAX_RESTORE_SUMMARY_BYTES,
    SOURCE_ENV_PATH: MAX_SOURCE_ENV_BYTES,
    (
        TENANT_PREFERENCES_ARCHIVE_ROOT / "ui_appearance.json"
    ).as_posix(): MAX_TENANT_PREFERENCE_BYTES,
}


class TenantOperationsPackVerificationError(RuntimeError):
    """Raised when a tenant operations pack fails read-only verification."""


class TenantOperationsPackMemberConsumer(Protocol):
    """Stages one second pass and publishes only after complete()."""

    def directory(self, path: str, *, category: str) -> None: ...

    def start_file(
        self,
        path: str,
        *,
        category: str,
        size: int,
        sha256: str,
    ) -> None: ...

    def write_file_chunk(self, path: str, chunk: bytes) -> None: ...

    def finish_file(self, path: str, *, sha256: str) -> None: ...

    def complete(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True)
class _ObservedMember:
    path: str
    member_type: str
    mode: int
    size: int
    sha256: str | None


@dataclass(frozen=True)
class _VerifiedPackState:
    result: dict[str, object]
    observed: dict[str, _ObservedMember]
    captured: dict[str, bytes]
    archive_rows: dict[str, dict[str, object]]
    operations_manifest: dict[str, object]
    restore_summary: dict[str, object]
    root_name: str
    uncompressed_size: int


class _TarEnvelopeValidator:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._remaining_data_bytes = 0
        self._zero_header_blocks = 0
        self._end_of_archive = False
        self._total_bytes = 0

    def feed(self, content: bytes) -> None:
        self._total_bytes += len(content)
        envelope_limit = MAX_ARCHIVE_TOTAL_BYTES + (
            MAX_ARCHIVE_MEMBERS + 64
        ) * TAR_BLOCK_BYTES * 2
        if self._total_bytes > envelope_limit:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ENVELOPE_LIMIT] "
                "gzip展開streamが運用パック上限を超えています。"
            )
        self._buffer.extend(content)
        while len(self._buffer) >= TAR_BLOCK_BYTES:
            block = bytes(self._buffer[:TAR_BLOCK_BYTES])
            del self._buffer[:TAR_BLOCK_BYTES]
            self._consume_block(block)

    def finish(self) -> None:
        if (
            self._buffer
            or self._remaining_data_bytes
            or not self._end_of_archive
            or self._zero_header_blocks < 2
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_TAR_ENVELOPE_INVALID] "
                "tarの終端またはblock境界が不正です。"
            )

    def _consume_block(self, block: bytes) -> None:
        if self._end_of_archive:
            if any(block):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_TAR_TRAILING_DATA] "
                    "tar終端後に非zero payloadがあります。"
                )
            return
        if self._remaining_data_bytes:
            data_bytes = min(self._remaining_data_bytes, TAR_BLOCK_BYTES)
            self._remaining_data_bytes -= data_bytes
            if data_bytes < TAR_BLOCK_BYTES and any(block[data_bytes:]):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_TAR_PADDING_NONZERO] "
                    "tar memberのpaddingに非zero payloadがあります。"
                )
            return
        if not any(block):
            self._zero_header_blocks += 1
            if self._zero_header_blocks == 2:
                self._end_of_archive = True
            return
        if self._zero_header_blocks:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_TAR_TRAILING_DATA] "
                "tarのzero終端blockが途中で途切れています。"
            )
        try:
            header = tarfile.TarInfo.frombuf(
                block,
                encoding="utf-8",
                errors="surrogateescape",
            )
        except tarfile.HeaderError as exc:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_TAR_HEADER_INVALID] tar headerが不正です。"
            ) from exc
        if header.size < 0 or header.size > MAX_ARCHIVE_FILE_BYTES:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_FILE_LIMIT] tar headerのfile sizeが不正です。"
            )
        self._remaining_data_bytes = header.size


def verify_tenant_operations_pack(
    archive_path: str | Path,
    *,
    expected_archive_sha256: str,
    expected_git_commit: str,
    expected_installation_id: str,
) -> dict[str, object]:
    with open_verified_tenant_operations_pack(
        archive_path,
        expected_archive_sha256=expected_archive_sha256,
        expected_git_commit=expected_git_commit,
        expected_installation_id=expected_installation_id,
    ) as session:
        return session.result


class VerifiedTenantOperationsPackSession:
    """Holds one input descriptor from verification through a second safe scan."""

    def __init__(
        self,
        archive_path: str | Path,
        *,
        expected_archive_sha256: str,
        expected_git_commit: str,
        expected_installation_id: str,
    ) -> None:
        self._path = Path(os.path.abspath(Path(archive_path).expanduser()))
        self._expected_archive_sha256 = _validated_sha256(
            expected_archive_sha256,
            field="expected archive SHA256",
        )
        self._expected_git_commit = _validated_git_commit(expected_git_commit)
        self._expected_installation_id = _validated_uuid(
            expected_installation_id,
            field="expected installation ID",
        )
        self._archive_file: BinaryIO | None = None
        self._initial_stat: os.stat_result | None = None
        self._state: _VerifiedPackState | None = None
        self._lifecycle = "new"

    def __enter__(self) -> VerifiedTenantOperationsPackSession:
        if self._lifecycle != "new":
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SESSION_STATE] 検証sessionは再利用できません。"
            )
        self._lifecycle = "opening"
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor: int | None = None
        archive_file: BinaryIO | None = None
        opened = False
        try:
            descriptor = os.open(self._path, flags)
            archive_file = os.fdopen(descriptor, "rb", closefd=True)
            descriptor = None
            before = os.fstat(archive_file.fileno())
            _validate_input_archive_metadata(before)
            state = _verify_open_archive(
                archive_file,
                path=self._path,
                before=before,
                expected_archive_sha256=self._expected_archive_sha256,
                expected_git_commit=self._expected_git_commit,
                expected_installation_id=self._expected_installation_id,
            )
            opened = True
        except TenantOperationsPackVerificationError:
            raise
        except (OSError, EOFError, tarfile.TarError) as exc:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ARCHIVE_INVALID] "
                "運用パックをtar.gzとして最後まで検証できません。"
            ) from exc
        finally:
            if not opened:
                self._lifecycle = "failed"
                if archive_file is not None:
                    archive_file.close()
                elif descriptor is not None:
                    os.close(descriptor)
        assert archive_file is not None
        self._archive_file = archive_file
        self._initial_stat = before
        self._state = state
        self._lifecycle = "opened"
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        archive_file = self._archive_file
        self._archive_file = None
        self._initial_stat = None
        self._state = None
        self._lifecycle = "closed"
        if archive_file is not None:
            archive_file.close()

    @property
    def result(self) -> dict[str, object]:
        return copy.deepcopy(self._required_state().result)

    @property
    def operations_manifest(self) -> dict[str, object]:
        return copy.deepcopy(self._required_state().operations_manifest)

    @property
    def restore_summary(self) -> dict[str, object]:
        return copy.deepcopy(self._required_state().restore_summary)

    @property
    def archive_inventory(self) -> dict[str, dict[str, object]]:
        state = self._required_state()
        inventory = copy.deepcopy(state.archive_rows)
        for path, row in inventory.items():
            row["sha256"] = state.observed[path].sha256
        return inventory

    def stream_verified_members(
        self,
        consumer: TenantOperationsPackMemberConsumer,
    ) -> None:
        if self._lifecycle != "opened":
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SESSION_STATE] "
                "検証sessionの安全配置passは1回だけ実行できます。"
            )
        self._lifecycle = "streaming"
        archive_file = self._required_archive_file()
        state = self._required_state()
        initial_stat = self._required_initial_stat()
        try:
            if _stat_identity(os.fstat(archive_file.fileno())) != _stat_identity(
                initial_stat
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_ARCHIVE_CHANGED] "
                    "安全配置の開始前に運用パックが変更されました。"
                )
            archive_file.seek(0)
            observed, _captured, root_name, uncompressed_size = _scan_archive(
                archive_file,
                consumer=consumer,
                expected_observed=state.observed,
                expected_archive_rows=state.archive_rows,
            )
            if (
                observed != state.observed
                or root_name != state.root_name
                or uncompressed_size != state.uncompressed_size
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_SECOND_PASS_MISMATCH] "
                    "安全配置時のmember構成がread-only検証結果と一致しません。"
                )
            archive_file.seek(0)
            outer_sha256 = _hash_and_validate_gzip_tar_envelope(archive_file)
            after = os.fstat(archive_file.fileno())
            if (
                outer_sha256 != self._expected_archive_sha256
                or _stat_identity(initial_stat) != _stat_identity(after)
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_ARCHIVE_CHANGED] "
                    "安全配置中に運用パックが変更されました。"
                )
            _call_consumer(consumer.complete)
        except TenantOperationsPackVerificationError as exc:
            self._lifecycle = "failed"
            _abort_consumer_without_masking(consumer, failure=exc)
            raise
        except (OSError, EOFError, tarfile.TarError) as exc:
            self._lifecycle = "failed"
            failure = TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ARCHIVE_INVALID] "
                "安全配置時に運用パックを最後まで再検証できません。"
            )
            _abort_consumer_without_masking(consumer, failure=failure)
            raise failure from exc
        except BaseException as exc:
            self._lifecycle = "failed"
            _abort_consumer_without_masking(consumer, failure=exc)
            raise
        self._lifecycle = "streamed"

    def _required_archive_file(self) -> BinaryIO:
        if self._archive_file is None:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SESSION_STATE] 検証sessionが開いていません。"
            )
        return self._archive_file

    def _required_initial_stat(self) -> os.stat_result:
        if self._initial_stat is None:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SESSION_STATE] 検証sessionが開いていません。"
            )
        return self._initial_stat

    def _required_state(self) -> _VerifiedPackState:
        if self._state is None:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SESSION_STATE] 検証sessionが開いていません。"
            )
        return self._state


def open_verified_tenant_operations_pack(
    archive_path: str | Path,
    *,
    expected_archive_sha256: str,
    expected_git_commit: str,
    expected_installation_id: str,
) -> VerifiedTenantOperationsPackSession:
    return VerifiedTenantOperationsPackSession(
        archive_path,
        expected_archive_sha256=expected_archive_sha256,
        expected_git_commit=expected_git_commit,
        expected_installation_id=expected_installation_id,
    )


def _verify_open_archive(
    archive_file: BinaryIO,
    *,
    path: Path,
    before: os.stat_result,
    expected_archive_sha256: str,
    expected_git_commit: str,
    expected_installation_id: str,
) -> _VerifiedPackState:
    outer_sha256 = _hash_and_validate_gzip_tar_envelope(archive_file)
    if outer_sha256 != expected_archive_sha256:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_OUTER_SHA256_MISMATCH] "
            "運用パック全体のSHA256が期待値と一致しません。"
        )
    archive_file.seek(0)
    observed, captured, root_name, uncompressed_size = _scan_archive(archive_file)
    after = os.fstat(archive_file.fileno())
    if _stat_identity(before) != _stat_identity(after):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ARCHIVE_CHANGED] "
            "検証中に運用パックが変更されました。"
        )
    operations_manifest = _load_json_object(
        captured[OPERATIONS_MANIFEST_PATH],
        path=OPERATIONS_MANIFEST_PATH,
    )
    archive_manifest = _load_json_object(
        captured[ARCHIVE_MANIFEST_PATH],
        path=ARCHIVE_MANIFEST_PATH,
    )
    restore_summary = _load_json_object(
        captured[VERIFICATION_SUMMARY_PATH],
        path=VERIFICATION_SUMMARY_PATH,
    )
    archive_rows = _validate_archive_manifest(
        archive_manifest,
        observed=observed,
        root_name=root_name,
        expected_git_commit=expected_git_commit,
    )
    _validate_checksums(
        captured[ARCHIVE_CHECKSUMS_PATH],
        observed=observed,
    )
    operations_result = _validate_operations_manifest(
        operations_manifest,
        restore_summary=restore_summary,
        archive_rows=archive_rows,
        observed=observed,
        captured=captured,
        root_name=root_name,
        expected_git_commit=expected_git_commit,
        expected_installation_id=expected_installation_id,
    )
    result = {
        "package_kind": PACKAGE_KIND,
        "package_root": root_name,
        "archive_path": str(path),
        "archive_size": before.st_size,
        "archive_sha256": outer_sha256,
        "git_commit": expected_git_commit,
        "installation_id": expected_installation_id,
        "database_engine": operations_result["database_engine"],
        "database_version": operations_result["database_version"],
        "backup_run_id": operations_result["backup_run_id"],
        "verification_run_id": operations_result["verification_run_id"],
        "member_count": len(observed),
        "uncompressed_size": uncompressed_size,
    }
    final_stat = os.fstat(archive_file.fileno())
    if _stat_identity(before) != _stat_identity(final_stat):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ARCHIVE_CHANGED] "
            "manifest検証中に運用パックが変更されました。"
        )
    return _VerifiedPackState(
        result=result,
        observed=observed,
        captured=captured,
        archive_rows=archive_rows,
        operations_manifest=operations_manifest,
        restore_summary=restore_summary,
        root_name=root_name,
        uncompressed_size=uncompressed_size,
    )


def _scan_archive(
    archive_file: BinaryIO,
    *,
    consumer: TenantOperationsPackMemberConsumer | None = None,
    expected_observed: Mapping[str, _ObservedMember] | None = None,
    expected_archive_rows: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[
    dict[str, _ObservedMember],
    dict[str, bytes],
    str,
    int,
]:
    observed: dict[str, _ObservedMember] = {}
    captured: dict[str, bytes] = {}
    portable_paths: dict[str, str] = {}
    root_name = ""
    previous_relative_path: str | None = None
    uncompressed_size = 0
    root_seen = False

    try:
        archive = tarfile.open(fileobj=archive_file, mode="r|gz")
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ARCHIVE_INVALID] "
            "運用パックは読み取り可能なgzip tarではありません。"
        ) from exc

    with archive:
        if archive.pax_headers:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_PAX_REJECTED] PAX metadataは許可していません。"
            )
        for member_index, member in enumerate(archive, start=1):
            if member_index > MAX_ARCHIVE_MEMBERS:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_MEMBER_LIMIT] "
                    "運用パックのmember数が上限を超えています。"
                )
            _validate_tar_member_metadata(member)
            if archive.pax_headers or member.pax_headers:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_PAX_REJECTED] PAX metadataは許可していません。"
                )

            raw_parts = _validated_raw_member_parts(member.name)
            if not root_seen:
                if member.type != tarfile.DIRTYPE or len(raw_parts) != 1:
                    raise TenantOperationsPackVerificationError(
                        "[TENANT_PACK_VERIFY_ROOT_INVALID] "
                        "archiveの先頭memberは単一root directoryである必要があります。"
                    )
                root_name = raw_parts[0]
                if _PACKAGE_ROOT_RE.fullmatch(root_name) is None:
                    raise TenantOperationsPackVerificationError(
                        "[TENANT_PACK_VERIFY_ROOT_INVALID] "
                        "archive root名が運用パック規約と一致しません。"
                    )
                observed["."] = _ObservedMember(
                    path=".",
                    member_type="directory",
                    mode=member.mode,
                    size=0,
                    sha256=None,
                )
                portable_paths["."] = "."
                root_seen = True
                continue

            if raw_parts[0] != root_name or len(raw_parts) == 1:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_MULTIPLE_ROOTS] "
                    "archiveには単一root配下だけを収録できます。"
                )
            relative_path = "/".join(raw_parts[1:])
            if (
                previous_relative_path is not None
                and relative_path <= previous_relative_path
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_ORDER_INVALID] "
                    "archive memberは重複なくpath順である必要があります。"
                )
            previous_relative_path = relative_path
            portable_key = unicodedata.normalize("NFC", relative_path).casefold()
            previous_portable = portable_paths.get(portable_key)
            if previous_portable is not None:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_PORTABLE_COLLISION] "
                    f"Mac上で衝突するpathがあります: {previous_portable}, {relative_path}"
                )
            portable_paths[portable_key] = relative_path
            _validate_parent_directories(relative_path, observed=observed)

            member_type = (
                "directory" if member.type == tarfile.DIRTYPE else "file"
            )
            expected_member = (
                expected_observed.get(relative_path)
                if expected_observed is not None
                else None
            )
            expected_row = (
                expected_archive_rows.get(relative_path)
                if expected_archive_rows is not None
                else None
            )
            if consumer is not None:
                _validate_second_pass_member(
                    relative_path,
                    member_type=member_type,
                    mode=member.mode,
                    size=member.size,
                    expected_member=expected_member,
                    expected_row=expected_row,
                )
            if member_type == "directory":
                observed[relative_path] = _ObservedMember(
                    path=relative_path,
                    member_type=member_type,
                    mode=member.mode,
                    size=0,
                    sha256=None,
                )
                if consumer is not None and expected_row is not None:
                    _call_consumer(
                        consumer.directory,
                        relative_path,
                        category=str(expected_row["category"]),
                    )
                continue

            if member.size > MAX_ARCHIVE_FILE_BYTES:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_FILE_LIMIT] "
                    f"展開sizeが上限を超えるfileがあります: {relative_path}"
                )
            uncompressed_size += member.size
            if uncompressed_size > MAX_ARCHIVE_TOTAL_BYTES:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_TOTAL_LIMIT] "
                    "運用パックの展開size合計が上限を超えています。"
                )
            capture_limit = _capture_limit(relative_path)
            if consumer is not None and expected_member is not None and expected_row is not None:
                if expected_member.sha256 is None:
                    raise TenantOperationsPackVerificationError(
                        "[TENANT_PACK_VERIFY_SECOND_PASS_MISMATCH] "
                        "安全配置するfileの期待SHA256がありません。"
                    )
                _call_consumer(
                    consumer.start_file,
                    relative_path,
                    category=str(expected_row["category"]),
                    size=member.size,
                    sha256=expected_member.sha256,
                )
            digest, payload = _hash_tar_member(
                archive,
                member,
                path=relative_path,
                capture_limit=capture_limit,
                chunk_consumer=(
                    (
                        lambda chunk, relative_path=relative_path: (
                            _call_consumer(
                                consumer.write_file_chunk,
                                relative_path,
                                chunk,
                            )
                        )
                    )
                    if consumer is not None
                    else None
                ),
            )
            if (
                consumer is not None
                and expected_member is not None
                and digest != expected_member.sha256
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_SECOND_PASS_MISMATCH] "
                    "安全配置時のmember SHA256が検証結果と一致しません。"
                )
            if consumer is not None:
                _call_consumer(
                    consumer.finish_file,
                    relative_path,
                    sha256=digest,
                )
            observed[relative_path] = _ObservedMember(
                path=relative_path,
                member_type=member_type,
                mode=member.mode,
                size=member.size,
                sha256=digest,
            )
            if payload is not None:
                captured[relative_path] = payload

        if archive.pax_headers:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_PAX_REJECTED] PAX metadataは許可していません。"
            )

    if not root_seen:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ROOT_MISSING] archive rootがありません。"
        )
    missing = sorted(_REQUIRED_CAPTURE_PATHS - set(captured))
    if missing:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_REQUIRED_FILE_MISSING] "
            "運用パックの必須fileがありません: " + ", ".join(missing)
        )
    return observed, captured, root_name, uncompressed_size


def _validate_second_pass_member(
    path: str,
    *,
    member_type: str,
    mode: int,
    size: int,
    expected_member: _ObservedMember | None,
    expected_row: Mapping[str, object] | None,
) -> None:
    if (
        expected_member is None
        or expected_row is None
        or expected_member.member_type != member_type
        or expected_member.mode != mode
        or expected_member.size != size
        or expected_row.get("path") != path
        or expected_row.get("type") != member_type
        or expected_row.get("mode") != f"{mode:04o}"
        or expected_row.get("size") != size
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SECOND_PASS_MISMATCH] "
            "安全配置時のmember metadataが検証結果と一致しません。"
        )


def _call_consumer(
    callback: Callable[..., None],
    /,
    *args: object,
    **kwargs: object,
) -> None:
    try:
        callback(*args, **kwargs)
    except Exception as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_CONSUMER_FAILED] "
            "安全配置先の一時領域への書込みに失敗しました。"
        ) from exc


def _abort_consumer_without_masking(
    consumer: TenantOperationsPackMemberConsumer,
    *,
    failure: BaseException,
) -> None:
    try:
        consumer.abort()
    except BaseException as abort_error:
        failure.add_note(
            "安全配置consumerの中止処理にも失敗しました。"
            f" ({type(abort_error).__name__})"
        )


def _validate_tar_member_metadata(member: tarfile.TarInfo) -> None:
    if member.type not in {tarfile.REGTYPE, tarfile.DIRTYPE}:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_MEMBER_TYPE_REJECTED] "
            f"fileとdirectory以外は許可していません: {member.name}"
        )
    if member.issparse() or member.linkname:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_MEMBER_TYPE_REJECTED] "
            f"sparseまたはlink memberは許可していません: {member.name}"
        )
    expected_mode = 0o700 if member.type == tarfile.DIRTYPE else 0o600
    if (
        member.uid != 0
        or member.gid != 0
        or member.uname != ""
        or member.gname != ""
        or member.mtime != 0
        or member.mode != expected_mode
        or member.devmajor != 0
        or member.devminor != 0
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_METADATA_INVALID] "
            f"正規化されていないmetadataがあります: {member.name}"
        )
    if member.type == tarfile.DIRTYPE and member.size != 0:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_DIRECTORY_SIZE_INVALID] "
            f"directory sizeが0ではありません: {member.name}"
        )


def _validated_raw_member_parts(raw_name: str) -> list[str]:
    if (
        not raw_name
        or raw_name.startswith("/")
        or raw_name.endswith("/")
        or "\\" in raw_name
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_name)
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PATH_INVALID] 安全でないarchive pathがあります。"
        )
    parts = raw_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PATH_INVALID] 安全でないarchive pathがあります。"
        )
    if PurePosixPath(*parts).as_posix() != raw_name:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PATH_INVALID] archive pathを正規化できません。"
        )
    return parts


def _validate_parent_directories(
    relative_path: str,
    *,
    observed: Mapping[str, _ObservedMember],
) -> None:
    path = PurePosixPath(relative_path)
    for parent in reversed(path.parents):
        parent_path = parent.as_posix()
        if parent_path in {"", "."}:
            continue
        parent_member = observed.get(parent_path)
        if parent_member is None or parent_member.member_type != "directory":
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_PARENT_MISSING] "
                f"明示された親directoryがありません: {relative_path}"
            )


def _capture_limit(relative_path: str) -> int | None:
    fixed_limit = _CAPTURE_LIMITS.get(relative_path)
    if fixed_limit is not None:
        return fixed_limit
    path = PurePosixPath(relative_path)
    if (
        path.parent == PurePosixPath("database")
        and path.suffix.casefold() == ".json"
    ):
        return MAX_BACKUP_MANIFEST_BYTES
    if relative_path == SOURCE_REGISTRY_ARCHIVE_PATH.as_posix():
        return MAX_SOURCE_REGISTRY_BYTES
    return None


def _hash_tar_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    path: str,
    capture_limit: int | None,
    chunk_consumer: Callable[[bytes], None] | None = None,
) -> tuple[str, bytes | None]:
    if capture_limit is not None and member.size > capture_limit:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_METADATA_LIMIT] "
            f"metadata fileが上限を超えています: {path}"
        )
    extracted = archive.extractfile(member)
    if extracted is None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_MEMBER_UNREADABLE] "
            f"archive memberを読み取れません: {path}"
        )
    digest = hashlib.sha256()
    payload = bytearray() if capture_limit is not None else None
    byte_count = 0
    while True:
        chunk = extracted.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        byte_count += len(chunk)
        if byte_count > member.size:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_MEMBER_SIZE_MISMATCH] "
                f"archive member sizeがheaderと一致しません: {path}"
            )
        digest.update(chunk)
        if chunk_consumer is not None:
            chunk_consumer(chunk)
        if payload is not None:
            payload.extend(chunk)
    if byte_count != member.size:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_MEMBER_SIZE_MISMATCH] "
            f"archive member sizeがheaderと一致しません: {path}"
        )
    return digest.hexdigest(), bytes(payload) if payload is not None else None


def _validate_archive_manifest(
    manifest: dict[str, object],
    *,
    observed: Mapping[str, _ObservedMember],
    root_name: str,
    expected_git_commit: str,
) -> dict[str, dict[str, object]]:
    _require_exact_keys(
        manifest,
        {
            "manifest_version",
            "bundle_root_dir",
            "member_count",
            "git_snapshot",
            "members",
            "integrity_convention",
        },
        path=ARCHIVE_MANIFEST_PATH,
    )
    if (
        isinstance(manifest["manifest_version"], bool)
        or not isinstance(manifest["manifest_version"], int)
        or manifest["manifest_version"] != ARCHIVE_MANIFEST_VERSION
        or manifest["bundle_root_dir"] != root_name
        or isinstance(manifest["member_count"], bool)
        or not isinstance(manifest["member_count"], int)
        or manifest["member_count"] != len(observed)
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ARCHIVE_MANIFEST_INVALID] "
            "archive manifestの版、root、member数が一致しません。"
        )
    git_snapshot = _require_mapping(
        manifest["git_snapshot"],
        path=f"{ARCHIVE_MANIFEST_PATH}.git_snapshot",
    )
    _require_exact_keys(
        git_snapshot,
        {"head", "branch", "status_sha256", "status_entry_count"},
        path=f"{ARCHIVE_MANIFEST_PATH}.git_snapshot",
    )
    if (
        str(git_snapshot["head"]).lower() != expected_git_commit
        or not isinstance(git_snapshot["branch"], str)
        or isinstance(git_snapshot["status_entry_count"], bool)
        or not isinstance(git_snapshot["status_entry_count"], int)
        or git_snapshot["status_entry_count"] != 0
        or git_snapshot["status_sha256"] != hashlib.sha256(b"").hexdigest()
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_GIT_SNAPSHOT_MISMATCH] "
            "archiveのGit snapshotがcleanな期待commitではありません。"
        )

    expected_integrity_convention = {
        "archive_manifest_sha256": "recorded in docs/checksums.txt",
        "checksums_sha256": "self-hash intentionally omitted",
        "null_sha256_rows": [
            ARCHIVE_MANIFEST_PATH,
            ARCHIVE_CHECKSUMS_PATH,
        ],
    }
    if manifest["integrity_convention"] != expected_integrity_convention:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_INTEGRITY_CONVENTION_INVALID] "
            "archive manifestのintegrity規約が一致しません。"
        )

    raw_rows = manifest["members"]
    if not isinstance(raw_rows, list) or len(raw_rows) != len(observed):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ARCHIVE_INVENTORY_INVALID] "
            "archive manifestのmember inventoryが不正です。"
        )
    expected_order = ["."] + sorted(
        path
        for path in observed
        if path not in {".", ARCHIVE_MANIFEST_PATH, ARCHIVE_CHECKSUMS_PATH}
    ) + [ARCHIVE_MANIFEST_PATH, ARCHIVE_CHECKSUMS_PATH]
    rows_by_path: dict[str, dict[str, object]] = {}
    for index, (raw_row, expected_path) in enumerate(
        zip(raw_rows, expected_order, strict=True)
    ):
        row = _require_mapping(
            raw_row,
            path=f"{ARCHIVE_MANIFEST_PATH}.members[{index}]",
        )
        _require_exact_keys(
            row,
            {"path", "type", "mode", "size", "sha256", "category"},
            path=f"{ARCHIVE_MANIFEST_PATH}.members[{index}]",
        )
        if row["path"] != expected_path:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ARCHIVE_INVENTORY_ORDER] "
                "archive manifestのmember順またはpathが一致しません。"
            )
        category = row["category"]
        if not isinstance(category, str) or category not in _ALLOWED_CATEGORIES:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                f"archive categoryが不正です: {expected_path}"
            )
        actual = observed[expected_path]
        expected_sha256 = (
            None
            if actual.member_type == "directory"
            or expected_path in {ARCHIVE_MANIFEST_PATH, ARCHIVE_CHECKSUMS_PATH}
            else actual.sha256
        )
        if (
            isinstance(row["size"], bool)
            or not isinstance(row["size"], int)
            or row["type"] != actual.member_type
            or row["mode"] != f"{actual.mode:04o}"
            or row["size"] != actual.size
            or row["sha256"] != expected_sha256
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ARCHIVE_INVENTORY_MISMATCH] "
                f"archive manifestと実memberが一致しません: {expected_path}"
            )
        rows_by_path[expected_path] = dict(row)

    _validate_archive_categories(rows_by_path)
    return rows_by_path


def _validate_archive_categories(
    rows_by_path: Mapping[str, Mapping[str, object]],
) -> None:
    expected_fixed_categories = {
        ".": "bundle_root",
        OPERATIONS_MANIFEST_PATH: "tenant_operations_manifest",
        ARCHIVE_MANIFEST_PATH: "archive_manifest",
        ARCHIVE_CHECKSUMS_PATH: "archive_checksums",
        VERIFICATION_SUMMARY_PATH: "restore_verification",
        SOURCE_ENV_PATH: "source_env_reference",
        README_PATH: "operator_guide",
    }
    if SOURCE_REGISTRY_ARCHIVE_PATH.as_posix() in rows_by_path:
        expected_fixed_categories[
            SOURCE_REGISTRY_ARCHIVE_PATH.as_posix()
        ] = "source_registry"
    for path, category in expected_fixed_categories.items():
        row = rows_by_path.get(path)
        if (
            row is None
            or row["category"] != category
            or (row["type"] != "file" and path != ".")
            or (path == "." and row["type"] != "directory")
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                f"必須memberのcategoryが一致しません: {path}"
            )
    fixed_path_by_category = {
        category: path for path, category in expected_fixed_categories.items()
    }
    fixed_path_by_category["source_registry"] = (
        SOURCE_REGISTRY_ARCHIVE_PATH.as_posix()
    )
    source_roots = {
        TENANT_POLICY_ARCHIVE_ROOT.as_posix(): "tenant_policy",
        TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix(): "tenant_preferences",
        PRIVATE_PAYLOAD_ARCHIVE_ROOT.as_posix(): "private_payload",
        GENERATED_REFERENCE_ARCHIVE_ROOT.as_posix(): "generated_reference",
    }
    for path, row in rows_by_path.items():
        category = row["category"]
        member_type = row["type"]
        for source_root, expected_category in source_roots.items():
            if _path_is_within(path, source_root) and category != expected_category:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                    f"source root内のcategoryが一致しません: {path}"
                )
        fixed_path = fixed_path_by_category.get(str(category))
        if fixed_path is not None and path != fixed_path:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                f"固定categoryが別pathで使われています: {path}"
            )
        if category == "archive_directory":
            if member_type != "directory" or not any(
                other_path != path
                and _path_is_within(other_path, path)
                and other_path.startswith(f"{path}/")
                for other_path in rows_by_path
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                    f"不要またはfile扱いのarchive directoryがあります: {path}"
                )
        if category == "database_backup" and (
            member_type != "file"
            or PurePosixPath(path).parent != PurePosixPath("database")
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] DB backup pathが不正です。"
            )
        if category == "database_backup_manifest" and (
            member_type != "file"
            or PurePosixPath(path).parent != PurePosixPath("database")
            or not path.endswith(".json")
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] DB manifest pathが不正です。"
            )
        if category == "tenant_policy" and not _path_is_within(
            path,
            TENANT_POLICY_ARCHIVE_ROOT.as_posix(),
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] tenant policy pathが不正です。"
            )
        if category == "tenant_preferences" and (
            not _path_is_within(
                path,
                TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix(),
            )
            or (
                member_type == "file"
                and not path.casefold().endswith(".json")
            )
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] "
                "tenant preferences pathが不正です。"
            )
        if category == "private_payload" and not _path_is_within(
            path,
            PRIVATE_PAYLOAD_ARCHIVE_ROOT.as_posix(),
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CATEGORY_INVALID] private payload pathが不正です。"
            )
        if category == "generated_reference":
            root = GENERATED_REFERENCE_ARCHIVE_ROOT.as_posix()
            if not _path_is_within(path, root) or _generated_path_is_transient(
                path.removeprefix(root).lstrip("/")
            ):
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_TRANSIENT_GENERATED_REJECTED] "
                    "generated referenceにcacheまたはruntime一時fileがあります。"
                )


def _validate_checksums(
    content: bytes,
    *,
    observed: Mapping[str, _ObservedMember],
) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_CHECKSUMS_INVALID] "
            "checksums.txtは正しいUTF-8ではありません。"
        ) from exc
    if not text.endswith("\n") or "\r" in text:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_CHECKSUMS_INVALID] checksums.txtの改行形式が不正です。"
        )
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, path = line.partition("  ")
        if (
            separator != "  "
            or _SHA256_RE.fullmatch(digest) is None
            or not path
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CHECKSUMS_INVALID] checksums.txtの行形式が不正です。"
            )
        _validated_relative_contract_path(path)
        if path in checksums:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CHECKSUMS_DUPLICATE] checksum pathが重複しています。"
            )
        checksums[path] = digest
    expected_paths = {
        path
        for path, member in observed.items()
        if member.member_type == "file" and path != ARCHIVE_CHECKSUMS_PATH
    }
    if set(checksums) != expected_paths:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_CHECKSUMS_COVERAGE] "
            "checksums.txtがregular fileを過不足なく列挙していません。"
        )
    for path, digest in checksums.items():
        if digest != observed[path].sha256:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_CHECKSUM_MISMATCH] "
                f"member SHA256が一致しません: {path}"
            )


def _validate_operations_manifest(
    manifest: dict[str, object],
    *,
    restore_summary: dict[str, object],
    archive_rows: Mapping[str, Mapping[str, object]],
    observed: Mapping[str, _ObservedMember],
    captured: Mapping[str, bytes],
    root_name: str,
    expected_git_commit: str,
    expected_installation_id: str,
) -> dict[str, object]:
    _require_exact_keys(
        manifest,
        {
            "package_kind",
            "package_version",
            "package_root",
            "created_at",
            "privacy_classification",
            "required_application",
            "database_backup",
            "restore_verification",
            "database_contract",
            "runtime_identity",
            "tenant_policy",
            "payload",
            "environment_reference",
            "safety_contract",
        },
        path=OPERATIONS_MANIFEST_PATH,
    )
    if (
        manifest["package_kind"] != PACKAGE_KIND
        or isinstance(manifest["package_version"], bool)
        or not isinstance(manifest["package_version"], int)
        or manifest["package_version"] != PACKAGE_VERSION
        or manifest["package_root"] != root_name
        or manifest["privacy_classification"] != PRIVACY_CLASSIFICATION
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_OPERATIONS_MANIFEST_INVALID] "
            "operations manifestのpackage契約が一致しません。"
        )
    _validated_timestamp(manifest["created_at"], field="package created_at")
    required_application = _require_mapping(
        manifest["required_application"],
        path="required_application",
    )
    _require_exact_keys(
        required_application,
        {"git_commit", "git_branch", "source_tree_clean"},
        path="required_application",
    )
    archive_git = _require_mapping(
        _require_mapping(
            _load_json_object(
                captured[ARCHIVE_MANIFEST_PATH],
                path=ARCHIVE_MANIFEST_PATH,
            )["git_snapshot"],
            path="git_snapshot",
        ),
        path="git_snapshot",
    )
    if (
        str(required_application["git_commit"]).lower() != expected_git_commit
        or required_application["git_branch"] != archive_git["branch"]
        or required_application["source_tree_clean"] is not True
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_REQUIRED_APPLICATION_MISMATCH] "
            "必要Platform commitが期待値と一致しません。"
        )

    database_backup = _validate_database_backup(
        manifest["database_backup"],
        archive_rows=archive_rows,
        observed=observed,
        captured=captured,
    )
    verification = _validate_restore_verification(
        manifest["restore_verification"],
        restore_summary=restore_summary,
        observed=observed,
        expected_backup_run_id=database_backup["backup_run_id"],
    )
    contract = _validate_database_contract(
        manifest["database_contract"],
        restore_summary=restore_summary,
        database_engine=database_backup["database_engine"],
    )
    if (
        database_backup["sqlite_identity"] is not None
        and database_backup["sqlite_identity"] != contract["runtime_identity"]
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SQLITE_IDENTITY_MISMATCH] "
            "SQLite backup manifestのDB識別情報が復元契約と一致しません。"
        )
    runtime_identity = _require_mapping(
        manifest["runtime_identity"],
        path="runtime_identity",
    )
    if (
        dict(runtime_identity) != contract["runtime_identity"]
        or runtime_identity.get("installation_id") != expected_installation_id
        or runtime_identity.get("runtime_kind") != "product"
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_IDENTITY_MISMATCH] "
            "product installation IDが期待値と一致しません。"
        )
    _validate_restored_summary_counts(
        restore_summary["summary"],
        contract=contract,
        database_engine=database_backup["database_engine"],
        sqlite_expectations=database_backup["sqlite_expectations"],
    )
    _validate_tenant_policy(
        manifest["tenant_policy"],
        archive_rows=archive_rows,
    )
    _validate_payload(
        manifest["payload"],
        archive_rows=archive_rows,
        captured=captured,
    )
    _validate_environment_reference(
        manifest["environment_reference"],
        source_env=captured[SOURCE_ENV_PATH],
    )
    if manifest["safety_contract"] != SAFETY_CONTRACT:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SAFETY_CONTRACT_MISMATCH] "
            "運用パックの安全契約が一致しません。"
        )
    return {
        "database_engine": database_backup["database_engine"],
        "database_version": contract["database_version"],
        "backup_run_id": database_backup["backup_run_id"],
        "verification_run_id": verification["verification_run_id"],
    }


def _validate_database_backup(
    raw_backup: object,
    *,
    archive_rows: Mapping[str, Mapping[str, object]],
    observed: Mapping[str, _ObservedMember],
    captured: Mapping[str, bytes],
) -> dict[str, object]:
    backup = _require_mapping(raw_backup, path="database_backup")
    expected_keys = {
        "backup_run_id",
        "database_engine",
        "status",
        "trigger_kind",
        "backup_file_name",
        "archive_path",
        "backup_file_size",
        "backup_sha256",
        "manifest_file_name",
        "manifest_archive_path",
        "manifest_sha256",
        "finished_at",
        "updated_at",
    }
    _require_exact_keys(backup, expected_keys, path="database_backup")
    backup_run_id = _positive_int(
        backup["backup_run_id"],
        field="backup run ID",
    )
    database_engine = str(backup["database_engine"] or "").strip()
    if (
        database_engine not in backup_restore_contract.SUPPORTED_DATABASE_ENGINES
        or backup["status"] != "succeeded"
        or not isinstance(backup["trigger_kind"], str)
        or not backup["trigger_kind"].strip()
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_STATE_INVALID] "
            "backupのengine、状態、種別が不正です。"
        )
    _validated_timestamp(backup["finished_at"], field="backup finished_at")
    _validated_timestamp(backup["updated_at"], field="backup updated_at")

    artifact_path = _validated_database_member_path(
        backup["archive_path"],
        file_name=backup["backup_file_name"],
        field="backup archive path",
    )
    manifest_path = _validated_database_member_path(
        backup["manifest_archive_path"],
        file_name=backup["manifest_file_name"],
        field="backup manifest archive path",
    )
    if artifact_path == manifest_path or not manifest_path.endswith(".json"):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_PATH_INVALID] "
            "backup本体とmanifestのpathが不正です。"
        )
    expected_database_paths = {artifact_path, manifest_path}
    actual_database_files = {
        path
        for path, member in observed.items()
        if member.member_type == "file" and PurePosixPath(path).parent.as_posix() == "database"
    }
    if actual_database_files != expected_database_paths:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_DATABASE_COVERAGE] "
            "database directoryのfile構成がmanifestと一致しません。"
        )

    artifact = observed.get(artifact_path)
    manifest_member = observed.get(manifest_path)
    if (
        artifact is None
        or manifest_member is None
        or artifact.member_type != "file"
        or manifest_member.member_type != "file"
        or archive_rows[artifact_path]["category"] != "database_backup"
        or archive_rows[manifest_path]["category"] != "database_backup_manifest"
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_MEMBER_INVALID] "
            "backup本体またはmanifest memberが不正です。"
        )
    backup_size = _positive_int(
        backup["backup_file_size"],
        field="backup file size",
    )
    backup_sha256 = _validated_sha256(
        backup["backup_sha256"],
        field="backup SHA256",
    )
    manifest_sha256 = _validated_sha256(
        backup["manifest_sha256"],
        field="backup manifest SHA256",
    )
    if (
        artifact.size != backup_size
        or artifact.sha256 != backup_sha256
        or manifest_member.sha256 != manifest_sha256
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_DIGEST_MISMATCH] "
            "backup本体またはmanifestのsize / SHA256が一致しません。"
        )
    manifest_payload = captured.get(manifest_path)
    if manifest_payload is None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_MANIFEST_MISSING] "
            "backup manifestを検証用に読み取れません。"
        )
    backup_manifest = _load_json_object(manifest_payload, path=manifest_path)
    manifest_backup_run_id = _positive_int(
        backup_manifest.get("backup_run_id"),
        field="backup manifest run ID",
    )
    manifest_backup_size = _positive_int(
        backup_manifest.get("backup_file_size"),
        field="backup manifest file size",
    )
    manifest_backup_sha256 = _validated_sha256(
        backup_manifest.get("backup_sha256"),
        field="backup manifest backup SHA256",
    )
    expected_manifest_fields = {
        "backup_run_id": backup_run_id,
        "backup_file_name": backup["backup_file_name"],
        "backup_file_size": backup_size,
        "backup_sha256": backup_sha256,
    }
    actual_manifest_fields = {
        "backup_run_id": manifest_backup_run_id,
        "backup_file_name": backup_manifest.get("backup_file_name"),
        "backup_file_size": manifest_backup_size,
        "backup_sha256": manifest_backup_sha256,
    }
    if actual_manifest_fields != expected_manifest_fields:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_BACKUP_MANIFEST_MISMATCH] "
            "backup manifestが収録backupと一致しません。"
        )
    sqlite_identity = None
    sqlite_expectations = None
    if database_engine == "sqlite":
        if (
            isinstance(backup_manifest.get("manifest_version"), bool)
            or backup_manifest.get("manifest_version") != 2
            or backup_manifest.get("database_engine") != "sqlite"
            or backup_manifest.get("snapshot_excluded_backup_run_id")
            != backup_run_id
            or backup_manifest.get("trigger_kind") != backup["trigger_kind"]
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SQLITE_MANIFEST_INVALID] "
                "SQLite backup manifestの版・engine・run情報が不正です。"
            )
        raw_identity = _require_mapping(
            backup_manifest.get("database_identity"),
            path="backup manifest database_identity",
        )
        _require_exact_keys(
            raw_identity,
            {"installation_id", "runtime_kind"},
            path="backup manifest database_identity",
        )
        sqlite_identity = {
            "installation_id": _validated_uuid(
                raw_identity["installation_id"],
                field="SQLite backup installation ID",
            ),
            "runtime_kind": str(raw_identity["runtime_kind"] or "").strip(),
        }
        if sqlite_identity["runtime_kind"] != "product":
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SQLITE_IDENTITY_INVALID] "
                "SQLite backup manifestは製品DBではありません。"
            )
        sqlite_expectations = _require_mapping(
            backup_manifest.get("verification_expectations"),
            path="backup manifest verification_expectations",
        )
        _require_exact_keys(
            sqlite_expectations,
            {
                "quick_check",
                "foreign_key_violation_count",
                "table_counts",
            },
            path="backup manifest verification_expectations",
        )
        table_counts = _require_mapping(
            sqlite_expectations["table_counts"],
            path="backup manifest verification_expectations.table_counts",
        )
        required_count_fields = {
            "auth_user",
            "django_migrations",
            "imports_deceasedprofile",
            "imports_household",
            "imports_person",
        }
        if (
            set(table_counts) != required_count_fields
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in table_counts.values()
            )
            or sqlite_expectations["quick_check"] != "ok"
            or sqlite_expectations["foreign_key_violation_count"] != 0
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SQLITE_EXPECTATIONS_INVALID] "
                "SQLite backup manifestの検証条件が不正です。"
            )
        sqlite_expectations = {
            "quick_check": "ok",
            "foreign_key_violation_count": 0,
            "table_counts": dict(table_counts),
        }
    return {
        "backup_run_id": backup_run_id,
        "database_engine": database_engine,
        "sqlite_identity": sqlite_identity,
        "sqlite_expectations": sqlite_expectations,
    }


def _validate_restore_verification(
    raw_verification: object,
    *,
    restore_summary: dict[str, object],
    observed: Mapping[str, _ObservedMember],
    expected_backup_run_id: int,
) -> dict[str, int]:
    verification = _require_mapping(
        raw_verification,
        path="restore_verification",
    )
    _require_exact_keys(
        verification,
        {
            "backup_run_id",
            "verification_run_id",
            "status",
            "trigger_kind",
            "finished_at",
            "updated_at",
            "summary",
            "summary_sha256",
            "summary_path",
        },
        path="restore_verification",
    )
    _require_exact_keys(
        restore_summary,
        {
            "backup_run_id",
            "verification_run_id",
            "status",
            "finished_at",
            "summary",
        },
        path=VERIFICATION_SUMMARY_PATH,
    )
    backup_run_id = _positive_int(
        verification["backup_run_id"],
        field="verification backup run ID",
    )
    verification_run_id = _positive_int(
        verification["verification_run_id"],
        field="verification run ID",
    )
    summary_backup_run_id = _positive_int(
        restore_summary["backup_run_id"],
        field="restore summary backup run ID",
    )
    summary_verification_run_id = _positive_int(
        restore_summary["verification_run_id"],
        field="restore summary verification run ID",
    )
    if (
        backup_run_id != expected_backup_run_id
        or summary_backup_run_id != backup_run_id
        or summary_verification_run_id != verification_run_id
        or verification["status"] != "succeeded"
        or restore_summary["status"] != "succeeded"
        or not isinstance(verification["trigger_kind"], str)
        or not verification["trigger_kind"].strip()
        or verification["summary_path"] != VERIFICATION_SUMMARY_PATH
        or verification["summary"] != restore_summary["summary"]
        or not isinstance(restore_summary["summary"], dict)
        or not restore_summary["summary"]
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_RESULT_MISMATCH] "
            "backup runとtest restore結果が一致しません。"
        )
    if verification["finished_at"] != restore_summary["finished_at"]:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_RESULT_MISMATCH] "
            "test restore完了時刻が一致しません。"
        )
    _validated_timestamp(
        verification["finished_at"],
        field="verification finished_at",
    )
    _validated_timestamp(
        verification["updated_at"],
        field="verification updated_at",
    )
    summary_member = observed[VERIFICATION_SUMMARY_PATH]
    if (
        verification["summary_sha256"] != summary_member.sha256
        or _SHA256_RE.fullmatch(str(verification["summary_sha256"] or "")) is None
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_SUMMARY_DIGEST] "
            "test restore summaryのSHA256が一致しません。"
        )
    return {"verification_run_id": verification_run_id}


def _validate_database_contract(
    raw_contract: object,
    *,
    restore_summary: dict[str, object],
    database_engine: str,
) -> dict[str, object]:
    if not isinstance(raw_contract, Mapping):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_CONTRACT_INVALID] DB復元契約が不正です。"
        )
    try:
        normalized_manifest_contract = (
            backup_restore_contract.validated_restore_contract(
                {backup_restore_contract.RESTORE_CONTRACT_KEY: raw_contract},
                expected_database_engine=database_engine,
            )
        )
        normalized_summary_contract = (
            backup_restore_contract.validated_restore_contract(
                restore_summary["summary"],
                expected_database_engine=database_engine,
            )
        )
    except backup_restore_contract.BackupRestoreContractError as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_CONTRACT_INVALID] DB復元契約が不正です。"
        ) from exc
    if normalized_manifest_contract != normalized_summary_contract:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_RESTORE_CONTRACT_MISMATCH] "
            "operations manifestとtest restoreのDB契約が一致しません。"
        )
    return normalized_manifest_contract


def _validate_restored_summary_counts(
    raw_summary: object,
    *,
    contract: Mapping[str, object],
    database_engine: str,
    sqlite_expectations: object,
) -> None:
    summary = _require_mapping(raw_summary, path="restore summary")
    required_count_fields = {
        "auth_user",
        "django_migrations",
        "imports_deceasedprofile",
        "imports_household",
        "imports_person",
    }
    for field in required_count_fields:
        value = summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_RESTORE_COUNTS_INVALID] "
                f"test restore件数が不正です: {field}"
            )
    migrations = _require_mapping(
        contract["applied_migrations"],
        path="database_contract.applied_migrations",
    )
    if summary["django_migrations"] != migrations["count"]:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_MIGRATION_COUNT_MISMATCH] "
            "test restoreのmigration件数がDB契約と一致しません。"
        )
    if database_engine == "sqlite":
        expectations = _require_mapping(
            sqlite_expectations,
            path="SQLite verification expectations",
        )
        expected_counts = _require_mapping(
            expectations["table_counts"],
            path="SQLite verification expectation counts",
        )
        if (
            summary.get("quick_check") != expectations["quick_check"]
            or summary.get("foreign_key_violation_count")
            != expectations["foreign_key_violation_count"]
            or any(summary.get(table) != count for table, count in expected_counts.items())
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SQLITE_INTEGRITY_INVALID] "
                "SQLite test restore結果がbackup manifestの検証条件と一致しません。"
            )
    elif sqlite_expectations is not None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SQLITE_EXPECTATIONS_UNEXPECTED] "
            "PostgreSQL backupにSQLite検証条件が指定されています。"
        )


def _validate_tenant_policy(
    raw_policy: object,
    *,
    archive_rows: Mapping[str, Mapping[str, object]],
) -> None:
    policy = _require_mapping(raw_policy, path="tenant_policy")
    _require_exact_keys(
        policy,
        {"archive_root", "file_count", "sha256"},
        path="tenant_policy",
    )
    policy_rows = sorted(
        (
            dict(row)
            for row in archive_rows.values()
            if row["category"] == "tenant_policy" and row["type"] == "file"
        ),
        key=lambda row: str(row["path"]),
    )
    if (
        policy["archive_root"] != TENANT_POLICY_ARCHIVE_ROOT.as_posix()
        or isinstance(policy["file_count"], bool)
        or not isinstance(policy["file_count"], int)
        or policy["file_count"] != len(policy_rows)
        or not policy_rows
        or any(
            not str(row["path"]).endswith(".json")
            or not _path_is_within(
                str(row["path"]),
                TENANT_POLICY_ARCHIVE_ROOT.as_posix(),
            )
            for row in policy_rows
        )
        or policy["sha256"]
        != backup_restore_contract.canonical_json_sha256(policy_rows)
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_TENANT_POLICY_MISMATCH] "
            "tenant policy inventoryがmanifestと一致しません。"
        )


def _validate_payload(
    raw_payload: object,
    *,
    archive_rows: Mapping[str, Mapping[str, object]],
    captured: Mapping[str, bytes],
) -> None:
    payload = _require_mapping(raw_payload, path="payload")
    _require_exact_keys(
        payload,
        {
            "selection",
            "private_file_count",
            "generated_reference_file_count",
            "source_inventory_sha256",
        },
        path="payload",
    )
    source_rows = sorted(
        (
            dict(row)
            for row in archive_rows.values()
            if row["category"] in _SOURCE_CATEGORIES
        ),
        key=lambda row: str(row["path"]),
    )
    private_file_count = sum(
        row["category"] == "private_payload" and row["type"] == "file"
        for row in source_rows
    )
    generated_file_count = sum(
        row["category"] == "generated_reference" and row["type"] == "file"
        for row in source_rows
    )
    if (
        isinstance(payload["private_file_count"], bool)
        or not isinstance(payload["private_file_count"], int)
        or isinstance(payload["generated_reference_file_count"], bool)
        or not isinstance(payload["generated_reference_file_count"], int)
        or payload["private_file_count"] != private_file_count
        or payload["generated_reference_file_count"] != generated_file_count
        or payload["source_inventory_sha256"]
        != backup_restore_contract.canonical_json_sha256(source_rows)
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SOURCE_INVENTORY_MISMATCH] "
            "tenant payload inventoryがmanifestと一致しません。"
        )

    legacy_selection = [
        _expected_selection_row(
            ".env",
            SOURCE_ENV_PATH,
            included=True,
        ),
        _expected_selection_row(
            "config/tenant_policy/default",
            TENANT_POLICY_ARCHIVE_ROOT.as_posix(),
            included=True,
        ),
        _expected_selection_row(
            "data/private",
            PRIVATE_PAYLOAD_ARCHIVE_ROOT.as_posix(),
            included=PRIVATE_PAYLOAD_ARCHIVE_ROOT.as_posix() in archive_rows,
        ),
        _expected_selection_row(
            "data/runtime/source_registry.json",
            SOURCE_REGISTRY_ARCHIVE_PATH.as_posix(),
            included=SOURCE_REGISTRY_ARCHIVE_PATH.as_posix() in archive_rows,
        ),
        _expected_selection_row(
            "data/generated",
            GENERATED_REFERENCE_ARCHIVE_ROOT.as_posix(),
            included=GENERATED_REFERENCE_ARCHIVE_ROOT.as_posix() in archive_rows,
        ),
    ]
    expected_selection = [
        *legacy_selection[:2],
        _expected_selection_row(
            "config/tenant_preferences",
            TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix(),
            included=TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix() in archive_rows,
        ),
        *legacy_selection[2:],
    ]
    allowed_selections = [expected_selection]
    if TENANT_PREFERENCES_ARCHIVE_ROOT.as_posix() not in archive_rows:
        allowed_selections.append(legacy_selection)
    if payload["selection"] not in allowed_selections:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SELECTION_MISMATCH] "
            "source selectionが実archiveと一致しません。"
        )
    _validate_tenant_preferences(
        archive_rows=archive_rows,
        captured=captured,
    )
    _validate_source_registry(
        archive_rows=archive_rows,
        captured=captured,
    )


def _validate_tenant_preferences(
    *,
    archive_rows: Mapping[str, Mapping[str, object]],
    captured: Mapping[str, bytes],
) -> None:
    appearance_path = (
        TENANT_PREFERENCES_ARCHIVE_ROOT / "ui_appearance.json"
    ).as_posix()
    if appearance_path not in archive_rows:
        return
    content = captured.get(appearance_path)
    if content is None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PREFERENCES_MISSING] "
            "収録された表示設定JSONを読み取れません。"
        )
    payload = _load_json_object(content, path=appearance_path)
    theme = payload.get("theme")
    if (
        set(payload) != {"schema_version", "theme"}
        or payload["schema_version"] != 1
        or isinstance(payload["schema_version"], bool)
        or not isinstance(theme, str)
        or theme not in {"standard", "light"}
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PREFERENCES_INVALID] "
            "表示設定JSONの契約が一致しません。"
        )


def _validate_source_registry(
    *,
    archive_rows: Mapping[str, Mapping[str, object]],
    captured: Mapping[str, bytes],
) -> None:
    registry_path = SOURCE_REGISTRY_ARCHIVE_PATH.as_posix()
    registry_row = archive_rows.get(registry_path)
    if registry_row is None:
        return
    content = captured.get(registry_path)
    if content is None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_MISSING] "
            "収録されたsource registryを読み取れません。"
        )
    registry = _load_json_object(content, path=registry_path)
    sources = registry.get("sources", [])
    if not isinstance(sources, list):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_INVALID] "
            "source registryのsourcesがlistではありません。"
        )
    for index, raw_source in enumerate(sources):
        source = _require_mapping(
            raw_source,
            path=f"{registry_path}.sources[{index}]",
        )
        raw_path = str(
            source.get("path") or source.get("file_path") or ""
        ).strip()
        if (
            not raw_path
            or "\\" in raw_path
            or raw_path.startswith("/")
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in raw_path
            )
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_PATH_INVALID] "
                "source registryの参照pathが不正です。"
            )
        source_path = PurePosixPath(raw_path)
        if (
            source_path.as_posix() != raw_path
            or any(part in {"", ".", ".."} for part in source_path.parts)
            or source_path.parts[:3] != ("data", "private", "sources")
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_PATH_INVALID] "
                "source registryの参照path境界が不正です。"
            )
        archived_source_path = PurePosixPath("payload", *source_path.parts).as_posix()
        source_row = archive_rows.get(archived_source_path)
        if (
            source_row is None
            or source_row["type"] != "file"
            or source_row["category"] != "private_payload"
            or not source_row["sha256"]
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_FILE_MISSING] "
                "source registryの参照fileがprivate payloadにありません。"
            )
        recorded_sha256 = str(
            source.get("sha256")
            or source.get("file_sha256")
            or source.get("source_sha256")
            or ""
        ).strip().lower()
        if recorded_sha256 and (
            _SHA256_RE.fullmatch(recorded_sha256) is None
            or recorded_sha256 != source_row["sha256"]
        ):
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_SOURCE_REGISTRY_HASH_MISMATCH] "
                "source registryの記録SHA256が収録fileと一致しません。"
            )


def _validate_environment_reference(
    raw_environment: object,
    *,
    source_env: bytes,
) -> None:
    environment = _require_mapping(
        raw_environment,
        path="environment_reference",
    )
    _require_exact_keys(
        environment,
        {"path", "keys", "raw_env_auto_apply"},
        path="environment_reference",
    )
    if (
        environment["path"] != SOURCE_ENV_PATH
        or environment["raw_env_auto_apply"] is not False
        or environment["keys"] != _classified_env_keys(source_env)
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ENV_REFERENCE_MISMATCH] "
            ".env参照情報が収録内容と一致しません。"
        )


def _classified_env_keys(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_ENV_INVALID] source.envはUTF-8ではありません。"
        ) from exc
    keys: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, _value = stripped.partition("=")
        key = key.strip()
        if not separator or _ENV_KEY_RE.fullmatch(key) is None or key in keys:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_ENV_INVALID] "
                f"source.envの設定行が不正です: {line_number}"
            )
        keys.add(key)
    return [
        {"key": key, "classification": _classify_env_key(key)}
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


def _load_json_object(content: bytes, *, path: str) -> dict[str, object]:
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_JSON_INVALID] JSONを検証できません: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_JSON_INVALID] JSON objectではありません: {path}"
        )
    return payload


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TenantOperationsPackVerificationError(
                f"[TENANT_PACK_VERIFY_JSON_DUPLICATE_KEY] JSON keyが重複しています: {key}"
            )
        result[key] = value
    return result


def _require_mapping(raw_value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(raw_value, Mapping) or not all(
        isinstance(key, str) for key in raw_value
    ):
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_OBJECT_INVALID] objectが不正です: {path}"
        )
    return raw_value


def _require_exact_keys(
    raw_mapping: Mapping[str, object],
    expected_keys: set[str],
    *,
    path: str,
) -> None:
    if set(raw_mapping) != expected_keys:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_FIELDS_INVALID] field構成が不正です: {path}"
        )


def _validated_database_member_path(
    raw_path: object,
    *,
    file_name: object,
    field: str,
) -> str:
    path = _validated_relative_contract_path(raw_path)
    name = str(file_name or "")
    pure_path = PurePosixPath(path)
    if (
        pure_path.parent != PurePosixPath("database")
        or not name
        or "/" in name
        or "\\" in name
        or pure_path.name != name
    ):
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_BACKUP_PATH_INVALID] {field} が不正です。"
        )
    return path


def _validated_relative_contract_path(raw_path: object) -> str:
    if not isinstance(raw_path, str):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_PATH_INVALID] manifest pathが文字列ではありません。"
        )
    parts = _validated_raw_member_parts(raw_path)
    return "/".join(parts)


def _validated_sha256(raw_value: object, *, field: str) -> str:
    value = str(raw_value or "").strip().lower()
    if _SHA256_RE.fullmatch(value) is None:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_SHA256_INVALID] {field} が不正です。"
        )
    return value


def _validated_git_commit(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if _GIT_OBJECT_RE.fullmatch(value) is None:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_GIT_COMMIT_INVALID] "
            "期待するGit commitは完全な40桁または64桁hexで指定してください。"
        )
    return value


def _validated_uuid(raw_value: object, *, field: str) -> str:
    try:
        parsed = uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_UUID_INVALID] {field} が不正です。"
        ) from exc
    if parsed.int == 0:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_UUID_INVALID] {field} が不正です。"
        )
    return str(parsed)


def _positive_int(raw_value: object, *, field: str) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_NUMBER_INVALID] {field} が不正です。"
        )
    return raw_value


def _validated_timestamp(raw_value: object, *, field: str) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_TIMESTAMP_INVALID] {field} が不正です。"
        )
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_TIMESTAMP_INVALID] {field} が不正です。"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TenantOperationsPackVerificationError(
            f"[TENANT_PACK_VERIFY_TIMESTAMP_INVALID] {field} にtimezoneがありません。"
        )
    return raw_value


def _validate_input_archive_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_size <= 0
        or metadata.st_size > MAX_ARCHIVE_COMPRESSED_BYTES
    ):
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_INPUT_PERMISSIONS] "
            "運用パックは現在user所有・非共有・単一linkの通常fileである必要があります。"
        )


def _hash_and_validate_gzip_tar_envelope(file_object: BinaryIO) -> str:
    digest = hashlib.sha256()
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    envelope = _TarEnvelopeValidator()
    while True:
        chunk = file_object.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        if decompressor.eof:
            raise TenantOperationsPackVerificationError(
                "[TENANT_PACK_VERIFY_GZIP_TRAILING_DATA] "
                "gzip memberの後ろにpayloadがあります。"
            )
        pending = chunk
        while pending:
            try:
                expanded = decompressor.decompress(
                    pending,
                    max_length=READ_CHUNK_BYTES,
                )
            except zlib.error as exc:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_GZIP_INVALID] gzip streamが不正です。"
                ) from exc
            envelope.feed(expanded)
            if decompressor.unused_data:
                raise TenantOperationsPackVerificationError(
                    "[TENANT_PACK_VERIFY_GZIP_TRAILING_DATA] "
                    "連結gzipまたはtrailing payloadは許可していません。"
                )
            pending = decompressor.unconsumed_tail
            if decompressor.eof:
                if pending:
                    raise TenantOperationsPackVerificationError(
                        "[TENANT_PACK_VERIFY_GZIP_TRAILING_DATA] "
                        "gzip memberの後ろにpayloadがあります。"
                    )
                break
    if not decompressor.eof:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_GZIP_TRUNCATED] gzip streamが完了していません。"
        )
    try:
        envelope.feed(decompressor.flush())
    except zlib.error as exc:
        raise TenantOperationsPackVerificationError(
            "[TENANT_PACK_VERIFY_GZIP_INVALID] gzip streamを完了できません。"
        ) from exc
    envelope.finish()
    return digest.hexdigest()


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def _generated_path_is_transient(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if any(part.casefold() in _GENERATED_CACHE_DIR_NAMES for part in path.parts):
        return True
    name = path.name.casefold()
    return name.endswith(_RUNTIME_TRANSIENT_FILE_SUFFIXES) or name.endswith("~")


def _expected_selection_row(
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


__all__ = [
    "TenantOperationsPackMemberConsumer",
    "TenantOperationsPackVerificationError",
    "VerifiedTenantOperationsPackSession",
    "open_verified_tenant_operations_pack",
    "verify_tenant_operations_pack",
]
