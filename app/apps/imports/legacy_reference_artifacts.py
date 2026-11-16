from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import unicodedata
from collections.abc import Callable
from itertools import zip_longest
from pathlib import Path
from typing import Any

from config.runtime_paths import exports_root, prepared_root

ToolRunner = Callable[[list[str], dict[str, str]], str]


class ArtifactVerificationError(RuntimeError):
    """A sanitized error raised when a legacy reference artifact is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactVerificationError("Artifact file cannot be read.") from exc
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_tool(command: list[str], env: dict[str, str]) -> str:
    tool = command[0]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
            errors="strict",
            text=True,
        )
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"Required tool is not installed: {tool}") from exc
    except (OSError, UnicodeError) as exc:
        raise ArtifactVerificationError(f"Legacy source verification tool is unavailable: {tool}") from exc
    if completed.returncode != 0:
        raise ArtifactVerificationError(
            f"Legacy source verification tool failed: {tool} (exit {completed.returncode})"
        )
    return completed.stdout


def _safe_component(value: str, *, label: str) -> str:
    normalized = (value or "").strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or Path(normalized).name != normalized
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ArtifactVerificationError(f"Invalid {label}.")
    return normalized


def _safe_file(root: Path, relative_path: str, *, label: str) -> Path:
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise ArtifactVerificationError(f"Unsafe artifact path: {label}")

    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ArtifactVerificationError(f"Symlink is not allowed: {label}")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"Artifact file is missing: {label}") from exc
    except (OSError, RuntimeError) as exc:
        raise ArtifactVerificationError(f"Artifact file cannot be accessed: {label}") from exc
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ArtifactVerificationError(f"Artifact file is invalid: {label}")
    return resolved


def _snapshot_root(base: Path, source_id: str, snapshot_id: str, *, label: str) -> Path:
    try:
        resolved_base = base.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"Artifact root is missing: {label}") from exc
    except (OSError, RuntimeError) as exc:
        raise ArtifactVerificationError(f"Artifact root cannot be accessed: {label}") from exc
    if not resolved_base.is_dir():
        raise ArtifactVerificationError(f"Artifact root is invalid: {label}")

    current = base
    for component in (source_id, snapshot_id):
        current /= component
        if current.is_symlink():
            raise ArtifactVerificationError(f"Symlink is not allowed: {label}")
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"Artifact snapshot is missing: {label}") from exc
    except (OSError, RuntimeError) as exc:
        raise ArtifactVerificationError(f"Artifact snapshot cannot be accessed: {label}") from exc
    if not resolved.is_relative_to(resolved_base) or not resolved.is_dir():
        raise ArtifactVerificationError(f"Artifact snapshot is invalid: {label}")
    return resolved


def _directory_files(root: Path, directory_name: str, *, label: str) -> set[str]:
    directory = root / directory_name
    if directory.is_symlink():
        raise ArtifactVerificationError(f"Symlink is not allowed: {label}")
    try:
        resolved_directory = directory.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"Artifact directory is missing: {label}") from exc
    except (OSError, RuntimeError) as exc:
        raise ArtifactVerificationError(f"Artifact directory cannot be accessed: {label}") from exc
    if not resolved_directory.is_relative_to(root) or not resolved_directory.is_dir():
        raise ArtifactVerificationError(f"Artifact directory is invalid: {label}")

    files: set[str] = set()
    try:
        entries = sorted(resolved_directory.rglob("*"))
    except OSError as exc:
        raise ArtifactVerificationError(f"Artifact directory cannot be read: {label}") from exc
    for entry in entries:
        if entry.is_symlink():
            raise ArtifactVerificationError(f"Symlink is not allowed: {label}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ArtifactVerificationError(f"Artifact directory contains an invalid entry: {label}")
        try:
            resolved = entry.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ArtifactVerificationError(
                f"Artifact directory entry cannot be accessed: {label}"
            ) from exc
        if not resolved.is_relative_to(resolved_directory):
            raise ArtifactVerificationError(f"Artifact directory contains an unsafe entry: {label}")
        normalized_path = _normalized_relative_path(resolved.relative_to(root))
        if normalized_path in files:
            raise ArtifactVerificationError(
                f"Artifact directory contains a Unicode-normalized path collision: {label}"
            )
        files.add(normalized_path)
    return files


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ArtifactVerificationError(f"Artifact file cannot be read: {label}") from exc


def _normalized_relative_path(path: Path) -> str:
    return unicodedata.normalize("NFC", path.as_posix())


def _load_json_file(root: Path, relative_path: str, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = _safe_file(root, relative_path, label=label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"Artifact JSON is invalid: {label}") from exc
    if not isinstance(value, dict):
        raise ArtifactVerificationError(f"Artifact JSON must be an object: {label}")
    return path, value


def _table_map(rows: object, *, label: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if not isinstance(rows, list):
        raise ArtifactVerificationError(f"Artifact table list is invalid: {label}")

    names: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ArtifactVerificationError(f"Artifact table entry is invalid: {label}")
        name = row.get("table_name")
        if not isinstance(name, str) or not name:
            raise ArtifactVerificationError(f"Artifact table name is invalid: {label}")
        if name in result:
            raise ArtifactVerificationError(f"Duplicate artifact table name: {name}")
        names.append(name)
        result[name] = row
    return names, result


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactVerificationError(f"Artifact integer is invalid: {label}")
    return value


def _export_environment(export_settings: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    for manifest_key, env_key in (("lang", "LANG"), ("lc_all", "LC_ALL")):
        value = export_settings.get(manifest_key)
        if isinstance(value, str) and value:
            env[env_key] = value
        else:
            env.pop(env_key, None)
    return env


def _verify_prepared_rows(
    *,
    csv_path: Path,
    jsonl_path: Path,
    source_id: str,
    snapshot_id: str,
    table_name: str,
    csv_relative_path: str,
    expected_columns: object,
    null_token: str,
) -> int:
    try:
        csv_handle = csv_path.open("r", encoding="utf-8", newline="")
        jsonl_handle = jsonl_path.open("r", encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArtifactVerificationError(f"Artifact table cannot be read: {table_name}") from exc

    sentinel = object()
    with csv_handle, jsonl_handle:
        try:
            reader = csv.DictReader(csv_handle)
            columns = reader.fieldnames or []
            if not all(isinstance(column, str) and column for column in columns):
                raise ArtifactVerificationError(f"CSV header is invalid: {table_name}")
            if len(set(columns)) != len(columns):
                raise ArtifactVerificationError(f"CSV header contains duplicates: {table_name}")
            if not isinstance(expected_columns, list) or columns != expected_columns:
                raise ArtifactVerificationError(
                    f"CSV and prepared columns differ: {table_name}"
                )

            row_count = 0
            pairs = zip_longest(reader, jsonl_handle, fillvalue=sentinel)
            for row_number, pair in enumerate(pairs, start=1):
                csv_row, jsonl_line = pair
                if csv_row is sentinel or jsonl_line is sentinel:
                    raise ArtifactVerificationError(
                        f"CSV and prepared row counts differ: {table_name}"
                    )
                if not isinstance(csv_row, dict) or None in csv_row:
                    raise ArtifactVerificationError(
                        f"CSV row shape is invalid: {table_name} row {row_number}"
                    )
                if any(csv_row.get(column) is None for column in columns):
                    raise ArtifactVerificationError(
                        f"CSV row shape is invalid: {table_name} row {row_number}"
                    )

                try:
                    record = json.loads(jsonl_line)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ArtifactVerificationError(
                        f"Prepared JSONL is invalid: {table_name} row {row_number}"
                    ) from exc
                if not isinstance(record, dict):
                    raise ArtifactVerificationError(
                        f"Prepared JSONL row is invalid: {table_name} row {row_number}"
                    )

                expected_record_keys = {
                    "source_id",
                    "snapshot_id",
                    "source_table",
                    "source_csv_file",
                    "source_row_number",
                    "values",
                }
                if set(record) != expected_record_keys:
                    raise ArtifactVerificationError(
                        f"Prepared JSONL row shape is invalid: {table_name} row {row_number}"
                    )

                expected_values = {
                    column: None if csv_row[column] == null_token else csv_row[column]
                    for column in columns
                }
                metadata_matches = (
                    record.get("source_id") == source_id
                    and record.get("snapshot_id") == snapshot_id
                    and record.get("source_table") == table_name
                    and record.get("source_csv_file") == csv_relative_path
                    and isinstance(record.get("source_row_number"), int)
                    and not isinstance(record.get("source_row_number"), bool)
                    and record.get("source_row_number") == row_number
                )
                if not metadata_matches:
                    raise ArtifactVerificationError(
                        f"Prepared provenance differs: {table_name} row {row_number}"
                    )
                values = record.get("values")
                if not isinstance(values, dict) or list(values) != columns:
                    raise ArtifactVerificationError(
                        f"Prepared value columns differ: {table_name} row {row_number}"
                    )
                if values != expected_values:
                    raise ArtifactVerificationError(
                        f"CSV and prepared values differ: {table_name} row {row_number}"
                    )
                row_count = row_number
        except ArtifactVerificationError:
            raise
        except (csv.Error, OSError, UnicodeError) as exc:
            raise ArtifactVerificationError(f"CSV is invalid: {table_name}") from exc
    return row_count


def verify_legacy_reference_artifacts(
    *,
    source_id: str,
    snapshot_id: str,
    exports_base: Path | None = None,
    prepared_base: Path | None = None,
    tool_runner: ToolRunner = _run_tool,
) -> dict[str, Any]:
    """Verify one explicit legacy-adapter snapshot without mutating it or the database."""

    source_id = _safe_component(source_id, label="source ID")
    snapshot_id = _safe_component(snapshot_id, label="snapshot ID")
    export_root_path = _snapshot_root(
        exports_base or exports_root(),
        source_id,
        snapshot_id,
        label="export snapshot",
    )
    prepared_root_path = _snapshot_root(
        prepared_base or prepared_root(),
        source_id,
        snapshot_id,
        label="prepared snapshot",
    )

    manifest_path, manifest = _load_json_file(
        export_root_path,
        "manifest.json",
        label="export manifest",
    )
    raw_manifest_path, raw_manifest = _load_json_file(
        prepared_root_path,
        "raw_manifest.json",
        label="prepared manifest",
    )

    source = manifest.get("source")
    snapshot = manifest.get("snapshot")
    export_settings = manifest.get("export_settings")
    if not isinstance(source, dict) or not isinstance(snapshot, dict):
        raise ArtifactVerificationError("Export manifest identity is invalid.")
    if not isinstance(export_settings, dict):
        raise ArtifactVerificationError("Export settings are invalid.")
    if source.get("source_id") != source_id or snapshot.get("snapshot_id") != snapshot_id:
        raise ArtifactVerificationError("Export manifest identity does not match the request.")
    if snapshot.get("copied_mdb") is not True:
        raise ArtifactVerificationError("Export snapshot does not contain a copied raw MDB.")
    if raw_manifest.get("source_id") != source_id or raw_manifest.get("snapshot_id") != snapshot_id:
        raise ArtifactVerificationError("Prepared manifest identity does not match the request.")

    null_token = export_settings.get("null_token")
    if not isinstance(null_token, str) or raw_manifest.get("null_token") != null_token:
        raise ArtifactVerificationError("Export and prepared NULL tokens differ.")

    source_filename_value = source.get("source_filename")
    if not isinstance(source_filename_value, str):
        raise ArtifactVerificationError("Source filename is invalid.")
    source_filename = _safe_component(source_filename_value, label="source filename")
    raw_mdb_path = _safe_file(
        export_root_path,
        f"raw_mdb/{source_filename}",
        label="raw MDB",
    )
    expected_size = _integer(source.get("size_bytes"), label="source size")
    expected_source_sha256 = source.get("sha256")
    if not isinstance(expected_source_sha256, str) or len(expected_source_sha256) != 64:
        raise ArtifactVerificationError("Source SHA256 is invalid.")
    actual_source_sha256 = _sha256(raw_mdb_path)
    try:
        actual_size = raw_mdb_path.stat().st_size
    except OSError as exc:
        raise ArtifactVerificationError("Raw MDB cannot be accessed.") from exc
    if actual_size != expected_size:
        raise ArtifactVerificationError("Raw MDB size differs from the manifest.")
    if actual_source_sha256 != expected_source_sha256:
        raise ArtifactVerificationError("Raw MDB SHA256 differs from the manifest.")

    export_names, export_tables = _table_map(manifest.get("tables"), label="export manifest")
    prepared_names, prepared_tables = _table_map(
        raw_manifest.get("tables"),
        label="prepared manifest",
    )
    if export_names != prepared_names:
        raise ArtifactVerificationError("Export and prepared table lists differ.")
    manifest_table_count = _integer(
        export_settings.get("table_count"),
        label="export table count",
    )
    if manifest_table_count != len(export_names):
        raise ArtifactVerificationError("Export table count differs from the manifest list.")

    expected_csv_files: set[str] = set()
    expected_jsonl_files: set[str] = set()
    for table_name in export_names:
        csv_relative = export_tables[table_name].get("csv_file")
        jsonl_relative = prepared_tables[table_name].get("jsonl_file")
        if not isinstance(csv_relative, str) or Path(csv_relative).parent != Path("csv"):
            raise ArtifactVerificationError(f"CSV path is invalid: {table_name}")
        if not isinstance(jsonl_relative, str) or Path(jsonl_relative).parent != Path("raw_jsonl"):
            raise ArtifactVerificationError(f"Prepared JSONL path is invalid: {table_name}")
        expected_csv_files.add(_normalized_relative_path(Path(csv_relative)))
        expected_jsonl_files.add(_normalized_relative_path(Path(jsonl_relative)))
    if len(expected_csv_files) != len(export_names):
        raise ArtifactVerificationError("Export manifest reuses a CSV file path.")
    if len(expected_jsonl_files) != len(prepared_names):
        raise ArtifactVerificationError("Prepared manifest reuses a JSONL file path.")
    if _directory_files(export_root_path, "csv", label="CSV directory") != expected_csv_files:
        raise ArtifactVerificationError("CSV file set differs from the export manifest.")
    if (
        _directory_files(prepared_root_path, "raw_jsonl", label="prepared JSONL directory")
        != expected_jsonl_files
    ):
        raise ArtifactVerificationError(
            "Prepared JSONL file set differs from the prepared manifest."
        )
    if _directory_files(export_root_path, "raw_mdb", label="raw MDB directory") != {
        _normalized_relative_path(Path("raw_mdb") / source_filename)
    }:
        raise ArtifactVerificationError("Raw MDB file set differs from the export manifest.")

    env = _export_environment(export_settings)
    listed_tables = tool_runner(["mdb-tables", "-1", str(raw_mdb_path)], env)
    if [line.strip() for line in listed_tables.splitlines() if line.strip()] != export_names:
        raise ArtifactVerificationError("Raw MDB table list differs from the manifest.")

    date_format = export_settings.get("date_format")
    datetime_format = export_settings.get("datetime_format")
    if not isinstance(date_format, str) or not isinstance(datetime_format, str):
        raise ArtifactVerificationError("Export date settings are invalid.")

    table_results: list[dict[str, Any]] = []
    fingerprint_files: list[dict[str, str]] = [
        {"kind": "raw_mdb", "name": source_filename, "sha256": actual_source_sha256},
        {"kind": "export_manifest", "name": "manifest.json", "sha256": _sha256(manifest_path)},
        {
            "kind": "prepared_manifest",
            "name": "raw_manifest.json",
            "sha256": _sha256(raw_manifest_path),
        },
    ]
    total_rows = 0
    for table_name in export_names:
        export_table = export_tables[table_name]
        prepared_table = prepared_tables[table_name]
        export_row_count = _integer(
            export_table.get("row_count"),
            label=f"export row count for {table_name}",
        )
        prepared_row_count = _integer(
            prepared_table.get("row_count"),
            label=f"prepared row count for {table_name}",
        )
        if export_row_count != prepared_row_count:
            raise ArtifactVerificationError(f"Manifest row counts differ: {table_name}")

        csv_relative = export_table.get("csv_file")
        jsonl_relative = prepared_table.get("jsonl_file")
        if not isinstance(csv_relative, str) or not isinstance(jsonl_relative, str):
            raise ArtifactVerificationError(f"Artifact table paths are invalid: {table_name}")
        csv_path = _safe_file(
            export_root_path,
            csv_relative,
            label=f"CSV for {table_name}",
        )
        jsonl_path = _safe_file(
            prepared_root_path,
            jsonl_relative,
            label=f"prepared JSONL for {table_name}",
        )

        reproduced_csv = tool_runner(
            [
                "mdb-export",
                "-D",
                date_format,
                "-T",
                datetime_format,
                "-0",
                null_token,
                str(raw_mdb_path),
                table_name,
            ],
            env,
        )
        if reproduced_csv.encode("utf-8") != _read_bytes(
            csv_path,
            label=f"CSV for {table_name}",
        ):
            raise ArtifactVerificationError(f"Raw MDB re-export differs: {table_name}")

        actual_rows = _verify_prepared_rows(
            csv_path=csv_path,
            jsonl_path=jsonl_path,
            source_id=source_id,
            snapshot_id=snapshot_id,
            table_name=table_name,
            csv_relative_path=csv_relative,
            expected_columns=prepared_table.get("columns"),
            null_token=null_token,
        )
        if actual_rows != export_row_count:
            raise ArtifactVerificationError(f"Artifact row count differs: {table_name}")

        csv_sha256 = _sha256(csv_path)
        jsonl_sha256 = _sha256(jsonl_path)
        table_results.append(
            {
                "table_name": table_name,
                "row_count": actual_rows,
                "csv_sha256": csv_sha256,
                "prepared_jsonl_sha256": jsonl_sha256,
            }
        )
        fingerprint_files.extend(
            [
                {"kind": "csv", "name": table_name, "sha256": csv_sha256},
                {"kind": "prepared_jsonl", "name": table_name, "sha256": jsonl_sha256},
            ]
        )
        total_rows += actual_rows

    fingerprint_payload = {
        "schema_version": 1,
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "files": fingerprint_files,
    }
    return {
        "schema_version": 1,
        "read_only": True,
        "status": "verified",
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "source": {
            "size_bytes": expected_size,
            "sha256": actual_source_sha256,
        },
        "counts": {
            "tables": len(table_results),
            "rows": total_rows,
            "verified_files": len(fingerprint_files),
        },
        "tables": table_results,
        "evidence_sha256": _json_sha256(fingerprint_payload),
    }


__all__ = [
    "ArtifactVerificationError",
    "verify_legacy_reference_artifacts",
]
