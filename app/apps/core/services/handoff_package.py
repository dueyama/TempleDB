from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from config.runtime_paths import generated_root

from .handoff_archive import (
    HandoffFile,
    build_archive,
    build_file_inventory,
    write_archive_atomic,
)
from .handoff_repository_snapshot import build_repository_snapshot
from .handoff_runtime_snapshot import build_runtime_snapshot

PACKAGE_KIND = "templedb-ai-maintenance-handoff-v2"
PACKAGE_VERSION = 2
UI_CONTRACT_VERSION = 2


def create_handoff_package(
    *,
    repository_root: str | Path | None = None,
    database_connection=None,
) -> tuple[BinaryIO, str]:
    """Build a private AI-maintenance archive without operational row values."""

    package_root, files, manifest = _prepare_package(
        repository_root=repository_root,
        database_connection=database_connection,
    )
    return build_archive(package_root=package_root, files=files, manifest=manifest)


def export_handoff_package(
    *,
    output_root: str | Path | None = None,
    repository_root: str | Path | None = None,
    database_connection=None,
) -> dict[str, object]:
    """Write one owner-only archive atomically and return its manifest metadata."""

    package_root, files, manifest = _prepare_package(
        repository_root=repository_root,
        database_connection=database_connection,
    )
    package_file, filename = build_archive(
        package_root=package_root,
        files=files,
        manifest=manifest,
    )
    try:
        archive_result = write_archive_atomic(
            package_file,
            filename=filename,
            output_root=output_root or _default_output_root(),
        )
    finally:
        package_file.close()
    return {**manifest, **archive_result}


def _prepare_package(
    *,
    repository_root: str | Path | None,
    database_connection,
) -> tuple[str, list[HandoffFile], dict[str, object]]:
    exported_at = timezone.localtime()
    repository = build_repository_snapshot(repository_root)
    untracked_omitted = int(repository["summary"]["untracked_omitted"])
    if untracked_omitted:
        raise RuntimeError(
            "AI handoff source is incomplete: "
            f"{untracked_omitted} allowlisted untracked file(s) would be omitted. "
            "Add the intended files to Git before generating the package."
        )
    tracked_missing_omitted = int(
        repository["summary"].get("tracked_missing_omitted", 0)
    )
    if tracked_missing_omitted:
        raise RuntimeError(
            "AI handoff source is incomplete: "
            f"{tracked_missing_omitted} inventoried source file(s) are missing. "
            "Restore the files or rebuild the release source manifest before "
            "generating the package."
        )
    runtime = build_runtime_snapshot(database_connection)
    package_root = _package_root_name(exported_at)
    files = _build_package_files(repository=repository, runtime=runtime)
    manifest = _build_manifest(
        exported_at=exported_at,
        package_root=package_root,
        repository=repository,
        runtime=runtime,
        files=files,
    )
    return package_root, files, manifest


def _package_root_name(exported_at: datetime) -> str:
    return f"templedb_ai_handoff_{exported_at.strftime('%Y%m%d_%H%M%S')}"


def _default_output_root() -> Path:
    return generated_root() / "handoff_packages"


def _build_package_files(
    *,
    repository: dict[str, object],
    runtime: dict[str, object],
) -> list[HandoffFile]:
    files = [
        HandoffFile("README.md", _text_bytes(_render_readme(repository))),
        HandoffFile("AI_HANDOFF.md", _text_bytes(_render_ai_handoff(repository))),
        HandoffFile(
            "security/PRIVACY.md",
            _text_bytes(_render_privacy_boundary(repository)),
        ),
        HandoffFile("repository/git.json", _json_bytes(_repository_metadata(repository))),
        HandoffFile(
            "repository/source_files.json",
            _json_bytes(_repository_file_metadata(repository)),
        ),
        HandoffFile("runtime/environment.json", _json_bytes(_runtime_environment(runtime))),
        HandoffFile("runtime/migrations.json", _json_bytes(runtime["migrations"])),
        HandoffFile("runtime/model_counts.json", _json_bytes(runtime["model_counts"])),
        HandoffFile("runtime/backup_status.json", _json_bytes(runtime["backup"])),
        HandoffFile("schema/physical_schema.json", _json_bytes(runtime["schema"])),
        HandoffFile("ui/route_catalog.json", _json_bytes(_route_catalog())),
        HandoffFile(
            "checks/verification.md",
            _text_bytes(_render_verification(repository=repository, runtime=runtime)),
        ),
    ]

    repository_files = repository["files"]
    if not isinstance(repository_files, list):
        raise TypeError("Repository snapshot files must be a list.")
    for entry in repository_files:
        if not isinstance(entry, dict):
            raise TypeError("Repository snapshot file entry must be a dictionary.")
        relative_path = str(entry["path"])
        content = entry["content"]
        if not isinstance(content, bytes):
            raise TypeError(f"Repository snapshot content must be bytes: {relative_path}")
        files.append(HandoffFile(f"source/{relative_path}", content))

        contract_prefix = "config/ui_contract/"
        if relative_path.startswith(contract_prefix):
            contract_path = relative_path.removeprefix(contract_prefix)
            files.append(HandoffFile(f"ui_contract/{contract_path}", content))

        policy_prefix = "config/tenant_policy/default/"
        if relative_path.startswith(policy_prefix):
            policy_path = relative_path.removeprefix(policy_prefix)
            files.append(HandoffFile(f"policy/tenant_policy_default/{policy_path}", content))
    return files


def _build_manifest(
    *,
    exported_at: datetime,
    package_root: str,
    repository: dict[str, object],
    runtime: dict[str, object],
    files: list[HandoffFile],
) -> dict[str, object]:
    repository_summary = repository["summary"]
    schema_counts = runtime["schema"]["counts"]
    model_counts = runtime["model_counts"]
    migrations = runtime["migrations"]
    source_inventory = _source_inventory_description(repository)
    repository_manifest = {
        "name": repository["repository_name"],
        "source": repository["source"],
        "git": repository["git"],
        "snapshot": repository_summary,
    }
    if "release_manifest" in repository:
        repository_manifest["release_manifest"] = repository["release_manifest"]
    return {
        "package_kind": PACKAGE_KIND,
        "package_version": PACKAGE_VERSION,
        "package_root": package_root,
        "exported_at": exported_at.isoformat(),
        "purpose": "AI-assisted maintenance of this TempleDB installation",
        "scope": "installation_and_repository",
        "privacy_classification": "internal-maintenance",
        "restore_capability": "none",
        "privacy": {
            "database_runtime_export": {
                "contains_operational_record_rows": False,
                "contains_database_backup": False,
                "contains_credentials": False,
                "contains_authentication_records": False,
                "contains_raw_import_sources": False,
                "contains_temple_identity_setting_values": False,
                "aggregate_counts_only": True,
            },
            "repository_source_snapshot": {
                "contains_tracked_allowlisted_text_source": True,
                "untracked_files_included": False,
                "high_confidence_secret_scan": {
                    "status": "passed",
                    "scope": "included_allowlisted_repository_text",
                    "limitations": "not_exhaustive_and_not_a_PII_or_anonymity_proof",
                },
                "may_contain_developer_authored_examples": True,
                "may_contain_documented_operational_references": True,
                "may_contain_tracked_PII_or_tenant_identity_text": True,
                "safe_for_public_distribution": False,
                "intended_recipient": "trusted_internal_maintainer_or_AI",
            },
        },
        "boundaries": {
            "database_restore": "Use the separately managed database backup workflow.",
            "private_migration_data": (
                "Requires a separate, explicitly authorized export; it is not part of this package."
            ),
            "source_snapshot": (
                f"{source_inventory} for internal maintenance reference; "
                "it may include examples or documented paths/endpoints and is not public material."
            ),
        },
        "repository": repository_manifest,
        "runtime_summary": {
            "database_vendor": runtime["database"]["vendor"],
            "database_runtime_kind": runtime["database"]["runtime_kind"],
            "applied_migration_count": migrations["count"],
            "managed_model_count": model_counts["count"],
            "physical_schema": schema_counts,
        },
        "ui_contract_version": UI_CONTRACT_VERSION,
        "file_inventory_scope": "all archive members except MANIFEST.json",
        "files": build_file_inventory(files),
    }


def _repository_metadata(repository: dict[str, object]) -> dict[str, object]:
    metadata = {
        "format_version": repository["format_version"],
        "source": repository["source"],
        "repository_name": repository["repository_name"],
        "git": repository["git"],
        "limits": repository["limits"],
        "summary": repository["summary"],
    }
    if "release_manifest" in repository:
        metadata["release_manifest"] = repository["release_manifest"]
    return metadata


def _runtime_environment(runtime: dict[str, object]) -> dict[str, object]:
    return {
        "format_version": runtime["format_version"],
        "python": runtime["python"],
        "django": runtime["django"],
        "platform": runtime["platform"],
        "database": runtime["database"],
    }


def _repository_file_metadata(repository: dict[str, object]) -> dict[str, object]:
    metadata = []
    for entry in repository["files"]:
        metadata.append(
            {
                key: value
                for key, value in entry.items()
                if key != "content"
            }
        )
    return {
        "format_version": repository["format_version"],
        "text_source_only": True,
        "binary_assets_included": False,
        "files": metadata,
    }


def _route_catalog() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def visit(patterns, prefix: str = "") -> None:
        for pattern in patterns:
            route = f"{prefix}{pattern.pattern}"
            if isinstance(pattern, URLResolver):
                visit(pattern.url_patterns, route)
            elif isinstance(pattern, URLPattern):
                callback = pattern.callback
                view_name = getattr(callback, "__name__", "")
                view_module = getattr(callback, "__module__", "")
                rows.append(
                    {
                        "name": pattern.name or "",
                        "route": route,
                        "view": f"{view_module}.{view_name}".strip("."),
                    }
                )

    visit(get_resolver().url_patterns)
    return sorted(rows, key=lambda row: (row["route"], row["name"]))


def _render_readme(repository: dict[str, object]) -> str:
    source_inventory = _source_inventory_description(repository)
    return f"""# TempleDB AI Maintenance Handoff

- kind: `{PACKAGE_KIND}`
- operational database rows: not included
- restore data: not included
- intended use: internal AI-assisted maintenance

This archive captures {source_inventory} together with a sanitized, read-only
description of database structure and aggregate state.
Start with `AI_HANDOFF.md`, then verify every packaged file against
`MANIFEST.json` before relying on it.
"""


def _render_ai_handoff(repository: dict[str, object]) -> str:
    git = repository["git"]
    source_paths = {
        str(entry["path"])
        for entry in repository["files"]
        if isinstance(entry, dict) and "path" in entry
    }
    preferred_read_paths = [
        "AGENTS.md",
        "docs/ai_maintenance_guide.md",
        "memory.md",
        "docs/decision_log.md",
        "docs/repo_structure_review.md",
        "README.md",
        "config/ui_contract/SPEC.md",
        "config/ui_contract/RECONSTRUCTION_GUIDE.md",
    ]
    available_read_paths = [
        f"source/{path}" for path in preferred_read_paths if path in source_paths
    ]
    read_order = [
        "`MANIFEST.json`, `security/PRIVACY.md`, and `checks/verification.md`",
    ]
    read_order.extend(f"`{path}`" for path in available_read_paths)
    read_order.extend(
        [
            "`repository/git.json` and `repository/source_files.json`",
            "`schema/physical_schema.json`, `runtime/migrations.json`, and "
            "`runtime/environment.json`",
            "`runtime/model_counts.json` and `runtime/backup_status.json`",
            "`ui/route_catalog.json` and the packaged UI contract when present",
        ]
    )
    read_order_text = "\n".join(
        f"{index}. {instruction}"
        for index, instruction in enumerate(read_order, start=1)
    )
    if repository["source"] == "build_time_manifest_allowlisted_worktree":
        source_rule = (
            "Treat the source tree as the current contents of files declared by the "
            "build-time release manifest. The exporter compares that manifest with "
            "the bounded allowlisted runtime tree, rejects unlisted or missing source, "
            "and records modifications from the release baseline."
        )
        dirty_note = (
            "Release source differed from its build-time baseline when exported."
            if git.get("tracked_dirty")
            else "Release source matched its build-time baseline when exported."
        )
    else:
        source_rule = (
            "Treat the source tree as the exact Git-tracked allowlisted worktree "
            "snapshot, including packaged modifications to tracked files. The "
            "exporter rejects allowlisted untracked or missing source."
        )
        dirty_note = (
            "The tracked worktree had changes when exported."
            if git.get("tracked_dirty")
            else "No tracked worktree changes were reported when exported."
        )
    return f"""# AI Handoff

This is a maintenance snapshot for the TempleDB codebase and its current runtime
shape. It is deliberately not a database backup or an operational-data export.

## Read order

{read_order_text}

## Rules

- {source_rule}
- Consult `repository/source_files.json` for original executable-bit metadata.
  Archive members themselves are owner-only data files and are not directly executable.
- Keep the archive internal and give it only to a trusted maintainer or AI.
  Tracked repository text/history may contain synthetic examples and also real
  operational references such as names, addresses, phone numbers, temple identity,
  local paths, or endpoints. The credential scan is not PII anonymization.
- Treat the physical schema as observed structure, not as ORM intent and not as
  data that can recreate the database.
- Physical schema identifiers (table, column, constraint, and index names) are included.
- Treat model counts as anonymous aggregate context only.
- Treat backup status as status evidence only; the archive contains no backup.
- Use synthetic records for tests or UI reconstruction.
- Use the normal backup/restore workflow for recovery. Design any private
  migration-data export as a separate, explicitly authorized operation.

Export note: {dirty_note}
"""


def _render_privacy_boundary(repository: dict[str, object]) -> str:
    source_inventory = _source_inventory_description(repository)
    return f"""# Privacy and Security Boundary

The database/runtime exporter does not read or serialize individual operational
rows. It exports schema metadata, applied migration names, per-model aggregate
counts, and a small allowlist of backup/test-restore status fields.

Not read or serialized from the live database:

- household, person, deceased, service, accounting, memo, audit, or import row values
- temple identity setting values and Google Calendar setting values
- authentication records, password hashes, sessions, tokens, and credentials
- database name, database host/user, installation ID, and runtime filesystem paths
- backup files, raw MDB/CSV inputs, source registry, and private workspace data

The source tree contains {source_inventory}. It can
contain developer-authored examples and real operational references in tracked
history, tests, migrations, configuration, or source. Those references may include
names, addresses, phone numbers, temple identity, endpoints, or local paths.
Source inventory mismatches and high-confidence credential patterns cause
generation to fail, but this scan is not exhaustive and is neither PII detection
nor anonymization.
Give the archive only to a trusted internal maintainer or AI; do not publish it or
upload it to an untrusted service. File paths and content are bounded, checked for
links and portable-name collisions, and hashed in `MANIFEST.json`.

Binary assets are intentionally omitted from `source/`. Original executable-bit
metadata for included text files is recorded in `repository/source_files.json`;
the archive itself keeps every member non-executable and owner-only.
"""


def _render_verification(
    *,
    repository: dict[str, object],
    runtime: dict[str, object],
) -> str:
    repository_summary = repository["summary"]
    schema_counts = runtime["schema"]["counts"]
    model_counts = runtime["model_counts"]
    migrations = runtime["migrations"]
    source_inventory = _source_inventory_description(repository)
    return f"""# Export-time Verification

- repository inventory: {source_inventory}
- repository source files: {repository_summary['file_count']}
- repository source bytes: {repository_summary['total_bytes']}
- repository snapshot SHA-256: `{repository_summary['sha256']}`
- included repository text secret scan: passed (high-confidence patterns only)
- physical database objects: {schema_counts['object_count']}
- physical foreign keys: {schema_counts['relation_count']}
- existing managed models counted: {model_counts['count']}
- applied migrations recorded: {migrations['count']}

The exporter completed its bounded source reads, physical schema introspection,
aggregate counts, status-field reads, path validation, and per-file hashing.
`MANIFEST.json` records SHA-256 and byte size for every other archive member.

This file does not claim that the packaged source test suite was run at export
time. Run the repository's documented checks in an isolated environment before
deploying changes. Never point restoration or migration experiments at the
production database.
"""


def _source_inventory_description(repository: dict[str, object]) -> str:
    if repository["source"] == "build_time_manifest_allowlisted_worktree":
        return (
            "the build-manifest-declared allowlisted current release source, "
            "checked against the bounded allowlisted runtime tree"
        )
    return "the Git-tracked allowlisted current worktree"


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _text_bytes(text: str) -> bytes:
    return text.encode("utf-8")


__all__ = [
    "PACKAGE_KIND",
    "PACKAGE_VERSION",
    "create_handoff_package",
    "export_handoff_package",
]
