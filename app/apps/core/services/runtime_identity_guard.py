from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from apps.core.models import DatabaseRuntimeIdentity
from config.instance_runtime import (
    InstanceSelection,
    InstanceSelectionError,
    selected_instance,
)

from . import runtime_database_contract, runtime_role

DATABASE_CONTRACT_BINDING_FILENAME = ".database-contract-binding.json"
DATABASE_CONTRACT_BINDING_SCHEMA_VERSION = 1
DATABASE_CONTRACT_SCHEMA_VERSION = 1
MAX_DATABASE_CONTRACT_BINDING_BYTES = 256 * 1024
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class RuntimeIdentityGuardError(RuntimeError):
    """Raised when a guarded web runtime points at the wrong database."""


@dataclass(frozen=True)
class ProductDatabaseBindingVerification:
    """Non-secret binding evidence after its live DB target was verified."""

    installation_id: str
    postgresql_major: int
    database_contract_sha256: str
    connection_target_sha256: str


@dataclass(frozen=True)
class _LiveProductDatabaseIdentity:
    """Stable live values that must continue to match after app migrations."""

    installation_id: str
    postgresql_major: int
    connection_target_sha256: str


def assert_web_runtime_identity() -> None:
    """Fail closed before serving a runtime that must remain offline."""

    try:
        role = runtime_role.current_runtime_role()
    except runtime_role.RuntimeRoleConfigurationError as exc:
        raise RuntimeIdentityGuardError(str(exc)) from exc
    if role == runtime_role.RUNTIME_ROLE_STANDBY:
        raise RuntimeIdentityGuardError(
            "TEMPLEDB_RUNTIME_ROLE=standby does not allow the TempleDB web runtime to start."
        )

    selection = _selected_instance()
    _assert_tenant_root_matches_selection(selection)
    demo_mode = getattr(settings, "TEMPLEDB_DEMO_MODE", False)
    configured_engine = getattr(settings, "TEMPLEDB_DATABASE_ENGINE", "")

    if selection is not None and selection.name == "demo":
        if demo_mode is not True:
            raise RuntimeIdentityGuardError(
                "current=instances/demo requires TEMPLEDB_DEMO_MODE=true."
            )
        _assert_supported_selected_engine(configured_engine)
        _assert_database_runtime_kind(
            expected_runtime_kind="demo",
            label="Selected demo",
        )
        return

    if selection is not None and selection.name == "product":
        if demo_mode is not False:
            raise RuntimeIdentityGuardError(
                "current=instances/product requires TEMPLEDB_DEMO_MODE=false."
            )
        _assert_supported_selected_engine(configured_engine)
        if configured_engine == "postgresql":
            _verify_selected_product_postgresql_binding(selection, connection)
        else:
            _assert_database_runtime_kind(
                expected_runtime_kind="product",
                label="Selected product SQLite",
            )
        return

    # Legacy layouts have no ``current`` pointer.  Preserve the existing
    # PostgreSQL demo guard while also protecting portable SQLite demos.
    if demo_mode or getattr(settings, "TEMPLEDB_POSTGRESQL_DEMO_MODE", False):
        _assert_database_runtime_kind(
            expected_runtime_kind="demo",
            label="Demo",
        )


def assert_product_database_binding(
    *,
    required: bool = True,
    database_connection=None,
) -> ProductDatabaseBindingVerification | None:
    """Verify the active product/PostgreSQL instance against its sealed binding.

    The dedicated management command uses the default ``required=True`` and
    therefore cannot report a skipped check as success.  Callers that only need
    to verify a binding when product/PostgreSQL is selected can opt out explicitly.
    """

    selection = _selected_instance()
    _assert_tenant_root_matches_selection(selection)
    selected_as_product = selection is not None and selection.name == "product"
    if (
        selected_as_product
        and getattr(settings, "TEMPLEDB_DEMO_MODE", False) is not False
    ):
        raise RuntimeIdentityGuardError(
            "current=instances/product requires TEMPLEDB_DEMO_MODE=false."
        )

    configured_engine = getattr(settings, "TEMPLEDB_DATABASE_ENGINE", "")
    is_product_postgresql = (
        selected_as_product
        and configured_engine == "postgresql"
    )
    if not is_product_postgresql:
        if required:
            raise RuntimeIdentityGuardError(
                "current=instances/productのPostgreSQL runtimeではありません。"
            )
        return None

    if selection is None:
        raise RuntimeIdentityGuardError(
            "current=instances/productの選択を確認できません。"
        )
    database_connection = database_connection or connection
    return _verify_selected_product_postgresql_binding(
        selection,
        database_connection,
    )


def _selected_instance() -> InstanceSelection | None:
    try:
        return selected_instance()
    except InstanceSelectionError as exc:
        raise RuntimeIdentityGuardError(
            "TempleDBのcurrent instanceを安全に確認できません。"
        ) from exc


def _assert_tenant_root_matches_selection(
    selection: InstanceSelection | None,
) -> None:
    configured_tenant_root = _canonical_runtime_root(
        Path(settings.TEMPLEDB_TENANT_ROOT)
    )
    product_root = _canonical_runtime_root(
        Path(settings.BASE_DIR) / "instances" / "product"
    )
    configured_as_product = configured_tenant_root == product_root
    selected_as_product = selection is not None and selection.name == "product"
    if configured_as_product != selected_as_product:
        raise RuntimeIdentityGuardError(
            "instances/productはTempleDB/currentによる選択が必要です。"
        )
    if (
        selection is not None
        and configured_tenant_root != _canonical_runtime_root(selection.root)
    ):
        raise RuntimeIdentityGuardError(
            "TempleDB/currentと有効なtenant rootが一致しません。"
        )


def _canonical_runtime_root(path: Path) -> Path:
    try:
        return Path(path).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeIdentityGuardError(
            "TempleDBのtenant rootを安全に解決できません。"
        ) from exc


def _assert_supported_selected_engine(configured_engine: str) -> None:
    if configured_engine not in {"sqlite", "postgresql"}:
        raise RuntimeIdentityGuardError(
            "Selected TempleDB instance requires sqlite or postgresql."
        )


def _assert_database_runtime_kind(
    *,
    expected_runtime_kind: str,
    label: str,
) -> None:
    try:
        identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
    except DatabaseRuntimeIdentity.DoesNotExist as exc:
        raise RuntimeIdentityGuardError(
            f"{label} database identity is missing."
        ) from exc
    except DatabaseError as exc:
        raise RuntimeIdentityGuardError(
            f"{label} database identity could not be verified."
        ) from exc

    try:
        installation_id = uuid.UUID(str(identity.installation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeIdentityGuardError(
            f"{label} database installation identity is invalid."
        ) from exc
    if installation_id.int == 0:
        raise RuntimeIdentityGuardError(
            f"{label} database installation identity is invalid."
        )
    if identity.runtime_kind != expected_runtime_kind:
        raise RuntimeIdentityGuardError(
            f"{label} runtime refuses a database whose runtime identity is not "
            f"{expected_runtime_kind}."
        )


def _verify_selected_product_postgresql_binding(
    selection: InstanceSelection,
    database_connection,
) -> ProductDatabaseBindingVerification:
    if database_connection.vendor != "postgresql":
        raise RuntimeIdentityGuardError(
            "製品instanceの設定と接続先database engineが一致しません。"
        )

    binding = _read_product_database_binding(
        selection.root / DATABASE_CONTRACT_BINDING_FILENAME
    )
    live_identity = _read_live_product_database_identity(database_connection)
    if binding.installation_id != live_identity.installation_id:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingと接続先DBのinstallation IDが一致しません。"
        )
    if binding.postgresql_major != live_identity.postgresql_major:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingと接続先PostgreSQL majorが一致しません。"
        )
    if binding.connection_target_sha256 != live_identity.connection_target_sha256:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingとPostgreSQL接続先が一致しません。"
        )
    # database_contract_sha256 remains sealed initial backup/restore evidence.
    # It deliberately is not compared with the live migration inventory: applying
    # an application migration must not make the same product DB unbootable.
    return binding


def _read_product_database_binding(
    path: Path,
) -> ProductDatabaseBindingVerification:
    raw_content = _read_owner_only_binding_file(path)
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingをJSONとして読み取れません。"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "bound_at",
        "contract",
    }:
        raise RuntimeIdentityGuardError("製品instanceのDB binding形式が不正です。")
    if payload.get("schema_version") != DATABASE_CONTRACT_BINDING_SCHEMA_VERSION:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB binding versionが一致しません。"
        )
    if not isinstance(payload.get("bound_at"), str) or not payload["bound_at"].strip():
        raise RuntimeIdentityGuardError("製品instanceのDB binding時刻が不正です。")

    contract = payload.get("contract")
    if not isinstance(contract, dict):
        raise RuntimeIdentityGuardError("製品instanceのDB contractが不正です。")
    if (
        contract.get("schema_version") != DATABASE_CONTRACT_SCHEMA_VERSION
        or contract.get("read_only") is not True
    ):
        raise RuntimeIdentityGuardError(
            "製品instanceのDB contract versionまたはread-only証跡が不正です。"
        )

    database = contract.get("database")
    if not isinstance(database, dict) or database.get("engine") != "postgresql":
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingはPostgreSQL contractではありません。"
        )
    postgresql_major = database.get("postgresql_major")
    if (
        isinstance(postgresql_major, bool)
        or not isinstance(postgresql_major, int)
        or not 10 <= postgresql_major <= 99
    ):
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingにあるPostgreSQL majorが不正です。"
        )

    runtime_identity = contract.get("runtime_identity")
    if not isinstance(runtime_identity, dict):
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingにruntime identityがありません。"
        )
    installation_id = _validated_installation_id(
        runtime_identity.get("installation_id"),
        label="製品instanceのDB binding",
    )
    if runtime_identity.get("runtime_kind") != "product":
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingはproduct runtimeではありません。"
        )
    database_contract_sha256 = str(
        contract.get("database_contract_sha256") or ""
    ).strip().lower()
    if not _SHA256_RE.fullmatch(database_contract_sha256):
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingにあるdatabase contract SHA256が不正です。"
        )
    connection_target_sha256 = str(
        contract.get("connection_target_sha256") or ""
    ).strip().lower()
    if not _SHA256_RE.fullmatch(connection_target_sha256):
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingにあるconnection target SHA256が不正です。"
        )
    return ProductDatabaseBindingVerification(
        installation_id=installation_id,
        postgresql_major=postgresql_major,
        database_contract_sha256=database_contract_sha256,
        connection_target_sha256=connection_target_sha256,
    )


def _read_owner_only_binding_file(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise RuntimeIdentityGuardError(
            "製品instanceにDB bindingがありません。"
        ) from exc
    except OSError as exc:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingを開けません。"
        ) from exc

    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > MAX_DATABASE_CONTRACT_BINDING_BYTES
        ):
            raise RuntimeIdentityGuardError(
                "製品instanceのDB bindingは小さい単一linkの通常fileが必要です。"
            )
        if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise RuntimeIdentityGuardError(
                "製品instanceのDB bindingはowner-onlyにしてください。"
            )
        if not metadata.st_mode & stat.S_IRUSR:
            raise RuntimeIdentityGuardError(
                "製品instanceのDB bindingをownerが読み取れる権限にしてください。"
            )
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise RuntimeIdentityGuardError(
                "製品instanceのDB bindingの所有者が現在userではありません。"
            )
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            content = stream.read(MAX_DATABASE_CONTRACT_BINDING_BYTES + 1)
            if len(content) > MAX_DATABASE_CONTRACT_BINDING_BYTES:
                raise RuntimeIdentityGuardError(
                    "製品instanceのDB bindingが大きすぎます。"
                )
            return content
    except UnicodeError as exc:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingをUTF-8として読み取れません。"
        ) from exc
    except OSError as exc:
        raise RuntimeIdentityGuardError(
            "製品instanceのDB bindingを読み取れません。"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_live_product_database_identity(
    database_connection,
) -> _LiveProductDatabaseIdentity:
    if database_connection.in_atomic_block:
        raise RuntimeIdentityGuardError(
            "製品DB binding照合は既存transactionの外側で実行してください。"
        )

    table_name = database_connection.ops.quote_name(
        DatabaseRuntimeIdentity._meta.db_table
    )
    try:
        with transaction.atomic(using=database_connection.alias):
            with database_connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cursor.execute(
                    "SELECT singleton_key, installation_id, runtime_kind "
                    f"FROM {table_name} ORDER BY singleton_key LIMIT 2"
                )
                identity_rows = cursor.fetchall()
                cursor.execute("SHOW server_version_num")
                version_row = cursor.fetchone()
            try:
                connection_target_sha256 = (
                    runtime_database_contract.connection_target_fingerprint_sha256(
                        database_connection
                    )
                )
            except runtime_database_contract.RuntimeDatabaseContractError as exc:
                raise RuntimeIdentityGuardError(
                    "接続先製品DBのconnection targetを照合できません。"
                ) from exc
    except RuntimeIdentityGuardError:
        raise
    except DatabaseError as exc:
        raise RuntimeIdentityGuardError(
            "接続先製品DBを読み取り専用で照合できません。"
        ) from exc

    if len(identity_rows) != 1 or identity_rows[0][0] != 1:
        raise RuntimeIdentityGuardError(
            "接続先製品DBのruntime identityが一意に存在しません。"
        )
    _singleton_key, raw_installation_id, runtime_kind = identity_rows[0]
    installation_id = _validated_installation_id(
        raw_installation_id,
        label="接続先製品DB",
    )
    if runtime_kind != "product":
        raise RuntimeIdentityGuardError(
            "接続先DBのruntime identityはproductではありません。"
        )

    try:
        server_version_num = int(version_row[0]) if version_row else 0
    except (TypeError, ValueError, IndexError) as exc:
        raise RuntimeIdentityGuardError(
            "接続先PostgreSQL majorを確認できません。"
        ) from exc
    postgresql_major = server_version_num // 10_000
    if not 10 <= postgresql_major <= 99:
        raise RuntimeIdentityGuardError(
            "接続先PostgreSQL majorの形式が不正です。"
        )
    return _LiveProductDatabaseIdentity(
        installation_id=installation_id,
        postgresql_major=postgresql_major,
        connection_target_sha256=connection_target_sha256,
    )


def _validated_installation_id(raw_value: object, *, label: str) -> str:
    try:
        installation_id = uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeIdentityGuardError(
            f"{label}のinstallation IDが不正です。"
        ) from exc
    if installation_id.int == 0:
        raise RuntimeIdentityGuardError(f"{label}のinstallation IDが不正です。")
    return str(installation_id)


__all__ = [
    "ProductDatabaseBindingVerification",
    "RuntimeIdentityGuardError",
    "assert_product_database_binding",
    "assert_web_runtime_identity",
]
