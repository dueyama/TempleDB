"""Read-only startup binding for an explicitly promoted product deployment.

The root-owned receipt is an operator authorization, not an automatic election.
It seals the former staging provenance without freezing subsequent business data.
Remote-primary fencing and backup/restore acceptance are operator attestations;
this guard does not claim to re-prove them on every process start.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection

from . import (
    database_transfer_postgresql,
    runtime_identity_guard,
    runtime_role,
)
from . import (
    tenant_operations_candidate_activation as activation,
)
from . import (
    tenant_operations_pack_apply as pack_apply,
)

_MAX_RECEIPT_BYTES = 64 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PrimaryPromotionGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrimaryPromotionVerification:
    database_name: str
    database_oid: int
    installation_id: str
    runtime_commit: str
    receipt_sha256: str


def verify_primary_promotion(
    *,
    promotion_receipt: str | Path,
    database_connection=None,
) -> PrimaryPromotionVerification:
    """Verify one root-authorized primary; never alter role, DB, or receipts."""
    if (
        runtime_role.current_runtime_role() != runtime_role.RUNTIME_ROLE_PRIMARY
        or os.environ.get("TEMPLEDB_RUNTIME_ROLE") != "primary"
        or getattr(settings, "TEMPLEDB_DATABASE_ENGINE", "") != "postgresql"
        or getattr(settings, "TEMPLEDB_DEMO_MODE", False) is not False
        or getattr(settings, "TEMPLEDB_POSTGRESQL_DEMO_MODE", False) is not False
    ):
        raise PrimaryPromotionGuardError("Explicit primary product PostgreSQL runtime required.")
    raw, receipt = _read_root_receipt(Path(promotion_receipt))
    _validate_receipt(receipt)
    app_root = _clean_absolute_path(receipt["platform_root"])
    tenant_root = _clean_absolute_path(receipt["tenant_root"])
    if (
        _clean_absolute_path(settings.BASE_DIR) != app_root
        or _clean_absolute_path(settings.TEMPLEDB_TENANT_ROOT) != tenant_root
        or tenant_root == app_root
        or tenant_root.is_relative_to(app_root)
        or app_root.is_relative_to(tenant_root)
        or os.geteuid() != receipt["run_uid"]
    ):
        raise PrimaryPromotionGuardError(
            "Primary deployment path or runtime owner differs from receipt."
        )
    _assert_root_owned_tree(app_root)
    try:
        pack_apply._assert_platform_commit(
            app_root,
            expected_git_commit=receipt["runtime_commit"],
        )
        activation._validated_candidate_root(
            tenant_root,
            expected_owner_uid=receipt["run_uid"],
        )
        _verify_historical_provenance(receipt, tenant_root)
    except (
        activation.TenantOperationsCandidateActivationError,
        pack_apply.TenantOperationsPackApplyError,
    ) as exc:
        raise PrimaryPromotionGuardError(
            "Primary deployment provenance could not be verified."
        ) from exc

    db = database_connection or connection
    database = receipt["database"]
    if (
        db.vendor != "postgresql"
        or db.settings_dict.get("NAME") != database["name"]
        or db.settings_dict.get("USER") != database["owner"]
    ):
        raise PrimaryPromotionGuardError("Configured primary DB differs from promotion receipt.")
    try:
        state = database_transfer_postgresql.inspect_connected_postgresql_candidate(
            database_name=database["name"],
            expected_database_oid=database["oid"],
            expected_ownership_token_sha256=database["ownership_token_sha256"],
            database_connection=db,
        )
        live = runtime_identity_guard._read_live_product_database_identity(db)
    except (
        database_transfer_postgresql.DatabaseTransferError,
        runtime_identity_guard.RuntimeIdentityGuardError,
    ) as exc:
        raise PrimaryPromotionGuardError("Primary database binding could not be verified.") from exc
    if (
        state.owner != database["owner"]
        or live.installation_id != receipt["installation_id"]
        or live.postgresql_major != database["postgresql_major"]
        or live.connection_target_sha256 != database["connection_target_sha256"]
    ):
        raise PrimaryPromotionGuardError(
            "Live primary identity, owner, cluster or major differs from receipt."
        )
    return PrimaryPromotionVerification(
        database_name=state.database_name,
        database_oid=state.database_oid,
        installation_id=live.installation_id,
        runtime_commit=receipt["runtime_commit"],
        receipt_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _verify_historical_provenance(receipt: dict, tenant_root: Path) -> None:
    owner = receipt["run_uid"]
    for name in (
        activation.ACTIVATION_PENDING_NAME,
        activation.DEACTIVATION_PENDING_NAME,
        activation.DEACTIVATION_RECEIPT_NAME,
    ):
        if os.path.lexists(tenant_root / name):
            raise PrimaryPromotionGuardError(
                "Candidate has incomplete activation or deactivation evidence."
            )
    # Machine configuration must remain outside the app-writable tenant .env.
    size, digest = activation._safe_file_size_and_sha256(
        tenant_root / ".env",
        expected_owner_uid=owner,
    )
    if (
        size != 0
        or digest != hashlib.sha256(b"").hexdigest()
        or stat.S_IMODE((tenant_root / ".env").lstat().st_mode) != 0o600
    ):
        raise PrimaryPromotionGuardError("Tenant .env must remain an empty sealed sentinel.")
    apply_raw, apply_receipt = activation._read_private_json(
        tenant_root / pack_apply.APPLY_RECEIPT_NAME,
        expected_owner_uid=owner,
    )
    _marker_raw, marker = activation._read_private_json(
        tenant_root / pack_apply.APPLY_COMPLETION_MARKER_NAME,
        expected_owner_uid=owner,
    )
    activation_raw, activation_receipt = activation._read_private_json(
        tenant_root / activation.ACTIVATION_RECEIPT_NAME,
        expected_owner_uid=owner,
    )
    apply_sha = hashlib.sha256(apply_raw).hexdigest()
    if (
        apply_sha != receipt["apply_receipt_sha256"]
        or hashlib.sha256(activation_raw).hexdigest() != receipt["activation_receipt_sha256"]
    ):
        raise PrimaryPromotionGuardError(
            "Historical candidate receipt digest differs from promotion."
        )
    database = receipt["database"]
    shared = dict(
        candidate_root=tenant_root,
        expected_git_commit=receipt["source_commit"],
        expected_archive_sha256=receipt["archive_sha256"],
        expected_installation_id=receipt["installation_id"],
        expected_database_name=database["name"],
        apply_sha256=apply_sha,
    )
    original = activation._validated_apply_receipt(apply_receipt, marker=marker, **shared)
    if (
        original["oid"] != database["oid"]
        or original["ownership_token_sha256"] != database["ownership_token_sha256"]
    ):
        raise PrimaryPromotionGuardError("Promotion changes the historical candidate DB object.")
    _contract, original_major = activation._validated_expected_candidate_contract(
        apply_receipt,
        expected_installation_id=receipt["installation_id"],
    )
    if original_major != database["postgresql_major"]:
        raise PrimaryPromotionGuardError("Promotion changes the historical PostgreSQL major.")
    activation._validated_activation_receipt(
        activation_receipt,
        expected_database_oid=database["oid"],
        expected_ownership_token_sha256=database["ownership_token_sha256"],
        **shared,
    )
    # Deliberately do not compare the former staging file baseline or migration
    # inventory with live mutable tenant state. migrate --check remains a separate
    # startup gate; the release manifest and root-owned deployment seal code.


def _validate_receipt(receipt: dict) -> None:
    keys = {
        "format",
        "version",
        "status",
        "promoted_at",
        "platform_root",
        "tenant_root",
        "run_uid",
        "source_commit",
        "runtime_commit",
        "archive_sha256",
        "installation_id",
        "database",
        "apply_receipt_sha256",
        "activation_receipt_sha256",
        "authorization",
    }
    if (
        set(receipt) != keys
        or receipt["format"] != "templedb-primary-promotion"
        or type(receipt["version"]) is not int
        or receipt["version"] != 1
        or receipt["status"] != "active-primary"
        or type(receipt["run_uid"]) is not int
        or receipt["run_uid"] <= 0
    ):
        raise PrimaryPromotionGuardError("Invalid primary promotion receipt format.")
    try:
        if datetime.fromisoformat(receipt["promoted_at"]).utcoffset() is None:
            raise ValueError("timestamp requires timezone")
        activation._validated_git_commit(receipt["source_commit"])
        activation._validated_git_commit(receipt["runtime_commit"])
        if (
            activation._validated_installation_id(receipt["installation_id"])
            != receipt["installation_id"]
        ):
            raise ValueError("installation UUID must be canonical")
        if receipt["installation_id"] == "00000000-0000-0000-0000-000000000000":
            raise ValueError("installation UUID must not be nil")
    except (TypeError, ValueError, activation.TenantOperationsCandidateActivationError) as exc:
        raise PrimaryPromotionGuardError(
            "Invalid promotion time, commits or installation identity."
        ) from exc
    for key in ("archive_sha256", "apply_receipt_sha256", "activation_receipt_sha256"):
        _require_sha256(receipt[key])
    database = receipt["database"]
    if (
        not isinstance(database, dict)
        or set(database)
        != {
            "name",
            "oid",
            "owner",
            "postgresql_major",
            "ownership_token_sha256",
            "connection_target_sha256",
        }
        or type(database["oid"]) is not int
        or database["oid"] <= 0
        or type(database["postgresql_major"]) is not int
        or not 10 <= database["postgresql_major"] <= 99
        or not isinstance(database["owner"], str)
        or not re.fullmatch(r"[a-z_][a-z0-9_]*", database["owner"])
    ):
        raise PrimaryPromotionGuardError("Invalid primary database contract.")
    try:
        activation._validated_database_name(database["name"])
    except activation.TenantOperationsCandidateActivationError as exc:
        raise PrimaryPromotionGuardError("Invalid primary candidate database name.") from exc
    _require_sha256(database["ownership_token_sha256"])
    _require_sha256(database["connection_target_sha256"])
    authorization = receipt["authorization"]
    if (
        not isinstance(authorization, dict)
        or set(authorization)
        != {"previous_primary_fenced", "verified_backup_sha256", "verified_restore_receipt_sha256"}
        or authorization["previous_primary_fenced"] is not True
    ):
        raise PrimaryPromotionGuardError(
            "Explicit fenced-primary and recovery attestation required."
        )
    _require_sha256(authorization["verified_backup_sha256"])
    _require_sha256(authorization["verified_restore_receipt_sha256"])


def _require_sha256(value: object) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PrimaryPromotionGuardError("Expected a canonical SHA256 digest.")


def _clean_absolute_path(raw_path: object) -> Path:
    try:
        path = Path(raw_path)
        if not path.is_absolute() or ".." in path.parts or path.resolve(strict=True) != path:
            raise ValueError("not an existing canonical absolute path")
        return path
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        raise PrimaryPromotionGuardError("Expected an existing non-symlink absolute path.") from exc


def _assert_root_owned_directory_chain(path: Path) -> None:
    current = _clean_absolute_path(path)
    while True:
        metadata = current.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PrimaryPromotionGuardError(
                "Promotion authority must have root-owned immutable ancestors."
            )
        if current == current.parent:
            return
        current = current.parent


def _assert_root_owned_tree(root: Path) -> None:
    _assert_root_owned_directory_chain(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name
            metadata = path.lstat()
            if (
                metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
                or (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1)
            ):
                raise PrimaryPromotionGuardError(
                    "Primary code must remain a root-owned immutable tree."
                )


def _read_root_receipt(path: Path) -> tuple[bytes, dict]:
    path = _clean_absolute_path(path)
    _assert_root_owned_directory_chain(path.parent)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) not in {0o444, 0o644}
            or not 0 < before.st_size <= _MAX_RECEIPT_BYTES
        ):
            raise PrimaryPromotionGuardError(
                "Promotion receipt must be root-owned, single-link 0644/0444."
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(_MAX_RECEIPT_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            len(raw) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise PrimaryPromotionGuardError("Promotion receipt changed during verification.")
        receipt = json.loads(raw, object_pairs_hook=_unique_json_object)
        if not isinstance(receipt, dict):
            raise PrimaryPromotionGuardError("Promotion receipt must be an object.")
        return raw, receipt
    except (OSError, UnicodeError, ValueError) as exc:
        raise PrimaryPromotionGuardError(
            "Could not read the root-authorized promotion receipt."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unique_json_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
