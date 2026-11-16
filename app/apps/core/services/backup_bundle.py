from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import django

from . import backup_migration_archive as _migration_archive

ARCHIVE_CHECKSUMS_PATH = _migration_archive.ARCHIVE_CHECKSUMS_PATH
ARCHIVE_MANIFEST_PATH = _migration_archive.ARCHIVE_MANIFEST_PATH
POSTAL_SCAN_BUNDLE_ROOT = _migration_archive.POSTAL_SCAN_BUNDLE_ROOT
PRIVATE_MIGRATION_MANIFEST_PATH = _migration_archive.PRIVATE_MIGRATION_MANIFEST_PATH
PRIVATE_MIGRATION_WORKSPACE_ROOT = _migration_archive.PRIVATE_MIGRATION_WORKSPACE_ROOT
WORKSPACE_ARCHIVE_ROOT = _migration_archive.WORKSPACE_ARCHIVE_ROOT
_ArchiveMember = _migration_archive._ArchiveMember
_bytes_archive_member = _migration_archive._bytes_archive_member
_capture_git_snapshot = _migration_archive._capture_git_snapshot
_collect_bundle_source_members = _migration_archive._collect_bundle_source_members
_collect_tracked_placeholder_members = _migration_archive._collect_tracked_placeholder_members
_collect_tree_archive_members = _migration_archive._collect_tree_archive_members
_iter_private_postal_scan_archive_files = (
    _migration_archive._iter_private_postal_scan_archive_files
)
_iter_workspace_archive_files = _migration_archive._iter_workspace_archive_files
_private_migration_payload_sources_exist = (
    _migration_archive._private_migration_payload_sources_exist
)
_private_postal_scan_archive_files_exist = (
    _migration_archive._private_postal_scan_archive_files_exist
)
_render_archive_integrity_files = _migration_archive._render_archive_integrity_files
_render_private_migration_manifest = _migration_archive._render_private_migration_manifest
_runtime_database_exclusions_for_roots = (
    _migration_archive._runtime_database_exclusions_for_roots
)
_source_file_archive_member = _migration_archive._source_file_archive_member
_source_inventory_fingerprint = _migration_archive._source_inventory_fingerprint
_validate_archive_member_set = _migration_archive._validate_archive_member_set
_validate_backup_manifest_for_bundle = _migration_archive._validate_backup_manifest_for_bundle
_validate_runtime_source_registry_snapshot = (
    _migration_archive._validate_runtime_source_registry_snapshot
)
_validated_archive_path = _migration_archive._validated_archive_path
_with_archive_parent_directories = _migration_archive._with_archive_parent_directories
_workspace_runtime_database_exclusions = (
    _migration_archive._workspace_runtime_database_exclusions
)
_write_archive_member = _migration_archive._write_archive_member
_write_archive_root_directory = _migration_archive._write_archive_root_directory


def _backup_module():
    from . import backup

    return backup


def _tenant_root_for_runtime(runtime, workspace_root: Path) -> Path:
    configured = Path(
        getattr(runtime.settings, "TEMPLEDB_TENANT_ROOT", workspace_root)
    ).expanduser()
    if not configured.is_absolute():
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_TENANT_ROOT_INVALID] "
            "TEMPLEDB_TENANT_ROOTは絶対pathで指定してください。"
        )

    # Tests and compatibility callers may replace backup.BASE_DIR only. When
    # Django still reports its unchanged default pair, preserve the caller's
    # workspace root exactly as the pre-tenant-root implementation did.
    settings_base = Path(
        getattr(runtime.settings, "BASE_DIR", workspace_root)
    ).expanduser()
    if (
        configured == settings_base
        and workspace_root.absolute() != settings_base.absolute()
    ):
        return workspace_root.absolute()
    return configured.absolute()


def _backup_artifact_filename(backup_run, *, default: str) -> str:
    """Return the basename of the artifact that the bundle actually stores."""
    backup_file_path = (getattr(backup_run, "backup_file_path", "") or "").strip()
    if backup_file_path:
        return Path(backup_file_path).name or default
    backup_file_name = (getattr(backup_run, "backup_file_name", "") or "").strip()
    return Path(backup_file_name).name if backup_file_name else default


def build_backup_migration_bundle_filename(backup_run) -> str:
    base_name = Path(
        _backup_artifact_filename(backup_run, default="templedb_backup")
    ).stem
    return f"{base_name}_migration_bundle.tar.gz"


def build_backup_migration_bundle_root_dir(backup_run) -> str:
    return Path(build_backup_migration_bundle_filename(backup_run)).name.removesuffix(".tar.gz")


def build_backup_migration_bundle_entries(backup_run) -> list[dict[str, object]]:
    if backup_run is None:
        return []
    runtime = _backup_module()
    backup_file_name = _backup_artifact_filename(backup_run, default="backup.dump")
    manifest_file_name = (backup_run.manifest_file_path or "").strip()
    manifest_name = Path(manifest_file_name).name if manifest_file_name else ""
    verification_run = runtime.latest_verification_for_backup_run(backup_run)
    workspace_root = Path(runtime.BASE_DIR)
    tenant_root = _tenant_root_for_runtime(runtime, workspace_root)
    postal_scan_files_included = _private_postal_scan_archive_files_exist(
        workspace_root,
        tenant_root=tenant_root,
    )
    private_payload_included = _private_migration_payload_sources_exist(
        workspace_root,
        tenant_root=tenant_root,
    )
    is_sqlite = backup_run.database_engine == "sqlite"
    return [
        {
            "label": "TempleDB workspace",
            "path": f"{WORKSPACE_ARCHIVE_ROOT}/",
            "included": True,
            "description": "現在の tracked / untracked 変更を含む workspace snapshot です。機密・runtime・generated data は誤起動を防ぐ隔離領域へ分けます。",
        },
        {
            "label": "Git履歴・branch・worktree metadata",
            "path": f"{WORKSPACE_ARCHIVE_ROOT}/.git/",
            "included": True,
            "description": "`.git` を明示的な必須資産として含め、履歴と現在の作業状態を新しいMacへ渡します。",
        },
        {
            "label": "引越し専用の機密・運用snapshot",
            "path": f"{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/",
            "included": private_payload_included,
            "description": (
                "`.env`、active tenant policy、UIから変更するtenant preferences、"
                "`data/private`、source registry、cache以外のgenerated、"
                "DB/PID/lock以外のruntime stateを、起動中workspaceとは分離して含めます。"
            ),
        },
        {
            "label": "機密・運用snapshot manifest",
            "path": PRIVATE_MIGRATION_MANIFEST_PATH.as_posix(),
            "included": True,
            "description": "隔離snapshotの元path、格納path、size、mode、SHA256と、存在しなかった任意資産を記録します。",
        },
        {
            "label": "郵便振込PDF証跡",
            "path": f"{POSTAL_SCAN_BUNDLE_ROOT.as_posix()}/",
            "included": postal_scan_files_included,
            "description": "護持会費の郵便振込PDFと名前欄切り抜きだけを `data/private` の例外として含めます。",
        },
        {
            "label": "バックアップDBファイル" if is_sqlite else "バックアップ dump",
            "path": f"backup/{backup_file_name}",
            "included": True,
            "description": (
                "新しいMacへ配置するSQLite DB本体です。"
                if is_sqlite
                else "新しいMacで pg_restore する本体です。"
            ),
        },
        {
            "label": "manifest",
            "path": f"backup/{manifest_name or '<backup>.json'}",
            "included": bool(manifest_name),
            "description": "SHA256 や backup metadata を確認する付随ファイルです。",
        },
        {
            "label": "guide.md",
            "path": "docs/guide.md",
            "included": True,
            "description": "旧Macと新しいMacでの作業手順をまとめた説明ファイルです。",
        },
        {
            "label": "runtime_versions.json",
            "path": "docs/runtime_versions.json",
            "included": True,
            "description": "旧Macで使っていた DBエンジン / Python / Django / Gunicorn / Caddy などの情報です。",
        },
        {
            "label": "checksums.txt",
            "path": ARCHIVE_CHECKSUMS_PATH.as_posix(),
            "included": True,
            "description": "workspace、`.git`、backup、機密payload、docsを含む全regular file（checksums自身を除く）のSHA256一覧です。",
        },
        {
            "label": "archive_manifest.json",
            "path": ARCHIVE_MANIFEST_PATH.as_posix(),
            "included": True,
            "description": "bundle memberのpath、type、owner-only mode、size、SHA256を正確に列挙します。",
        },
        {
            "label": "workspace_exclusions.txt",
            "path": "docs/workspace_exclusions.txt",
            "included": True,
            "description": "workspace snapshot に入れない path と理由の一覧です。",
        },
        {
            "label": "verification_summary.json",
            "path": "docs/verification_summary.json",
            "included": bool(verification_run and verification_run.verification_summary),
            "description": "直近の別DBテスト復元で読めた主要テーブル件数の summary です。",
        },
    ]


def create_backup_migration_bundle(
    backup_run,
    *,
    include_private_migration_payload: bool = False,
):
    runtime = _backup_module()
    if backup_run is None:
        raise runtime.BackupServiceError("対象バックアップが見つかりません。")
    if not include_private_migration_payload:
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_CONFIRMATION_REQUIRED] 機密情報を含む引越し専用bundleであることを確認してください。"
        )
    if backup_run.database_engine != runtime.current_database_engine():
        raise runtime.BackupServiceError("現在のDBエンジンとは異なるバックアップです。")
    backup_file_path = runtime.validate_backup_artifact(backup_run)
    verification_run = runtime.latest_verification_for_backup_run(backup_run)
    if (
        verification_run is None
        or verification_run.status != "succeeded"
        or getattr(verification_run, "finished_at", None) is None
        or not isinstance(getattr(verification_run, "verification_summary", None), dict)
        or not verification_run.verification_summary
    ):
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_VERIFICATION_REQUIRED] 同じバックアップの最新テスト復元を成功させてください。"
        )
    manifest_file_path, validated_manifest_sha256 = _validate_backup_manifest_for_bundle(
        runtime,
        backup_run,
        backup_file_path,
    )
    guide = runtime.build_backup_migration_guide_context(backup_run)

    root_dir = build_backup_migration_bundle_root_dir(backup_run)
    _validated_archive_path(root_dir)
    bundle_entries = build_backup_migration_bundle_entries(backup_run)
    guide_markdown = _render_backup_migration_guide_markdown(
        guide,
        bundle_entries,
        bundle_filename=build_backup_migration_bundle_filename(backup_run),
        bundle_root_dir=root_dir,
    )
    runtime_versions = _collect_runtime_versions(backup_run, verification_run)
    workspace_root = Path(runtime.BASE_DIR)
    tenant_root = _tenant_root_for_runtime(runtime, workspace_root)
    (
        runtime_database_exclusions,
        tenant_runtime_database_exclusions,
    ) = _runtime_database_exclusions_for_roots(
        runtime,
        workspace_root,
        tenant_root,
    )
    git_snapshot_before = _capture_git_snapshot(workspace_root)
    source_members, private_selection = _collect_bundle_source_members(
        workspace_root,
        runtime_database_exclusions=runtime_database_exclusions,
        tenant_root=tenant_root,
        tenant_runtime_database_exclusions=tenant_runtime_database_exclusions,
    )
    _validate_runtime_source_registry_snapshot(
        workspace_root,
        source_members,
        private_selection,
        tenant_root=tenant_root,
    )

    generated_members: list[_ArchiveMember] = [
        _bytes_archive_member("docs/guide.md", guide_markdown.encode("utf-8"), "guide"),
        _bytes_archive_member(
            "docs/runtime_versions.json",
            json.dumps(runtime_versions, ensure_ascii=False, indent=2).encode("utf-8"),
            "runtime_versions",
        ),
        _bytes_archive_member(
            "docs/workspace_exclusions.txt",
            _render_workspace_exclusions().encode("utf-8"),
            "workspace_exclusions",
        ),
    ]
    if verification_run and verification_run.verification_summary:
        generated_members.append(
            _bytes_archive_member(
                "docs/verification_summary.json",
                json.dumps(
                    verification_run.verification_summary, ensure_ascii=False, indent=2
                ).encode("utf-8"),
                "verification_summary",
            )
        )
    private_members = [
        member
        for member in source_members
        if member.category
        in {
            "private_payload",
            "runtime_snapshot",
            "generated_snapshot",
            "postal_scans",
        }
    ]
    private_manifest_content = _render_private_migration_manifest(
        private_members,
        private_selection,
    )
    generated_members.append(
        _bytes_archive_member(
            PRIVATE_MIGRATION_MANIFEST_PATH.as_posix(),
            private_manifest_content,
            "private_payload_manifest",
        )
    )

    backup_database_member = _source_file_archive_member(
        backup_file_path,
        f"backup/{backup_file_path.name}",
        category="backup_database",
        private=True,
    )
    backup_manifest_member = _source_file_archive_member(
        manifest_file_path,
        f"backup/{manifest_file_path.name}",
        category="backup_manifest",
        private=True,
    )
    if (
        backup_database_member.sha256
        != (getattr(backup_run, "backup_sha256", "") or "").strip().lower()
        or backup_manifest_member.sha256 != validated_manifest_sha256
    ):
        raise runtime.BackupServiceError(
            "[MIGRATION_BUNDLE_BACKUP_CHANGED] backupまたはmanifestが検証後に変更されました。"
        )
    source_members.extend([backup_database_member, backup_manifest_member])
    payload_members = _with_archive_parent_directories(source_members + generated_members)
    _validate_archive_member_set(payload_members)
    archive_manifest_content, checksums_content = _render_archive_integrity_files(
        payload_members,
        root_dir=root_dir,
        git_snapshot=git_snapshot_before,
    )
    integrity_members = [
        _bytes_archive_member(
            ARCHIVE_MANIFEST_PATH.as_posix(),
            archive_manifest_content,
            "archive_manifest",
        ),
        _bytes_archive_member(
            ARCHIVE_CHECKSUMS_PATH.as_posix(),
            checksums_content,
            "archive_checksums",
        ),
    ]
    all_members = _with_archive_parent_directories(payload_members + integrity_members)
    _validate_archive_member_set(all_members)

    bundle_file = tempfile.TemporaryFile()
    os.fchmod(bundle_file.fileno(), 0o600)
    try:
        with tarfile.open(fileobj=bundle_file, mode="w:gz") as archive:
            _write_archive_root_directory(archive, root_dir)
            for member in sorted(all_members, key=lambda item: item.archive_path):
                _write_archive_member(archive, root_dir, member)

        source_members_after, private_selection_after = _collect_bundle_source_members(
            workspace_root,
            runtime_database_exclusions=runtime_database_exclusions,
            tenant_root=tenant_root,
            tenant_runtime_database_exclusions=tenant_runtime_database_exclusions,
        )
        backup_members_after = [
            _source_file_archive_member(
                backup_file_path,
                f"backup/{backup_file_path.name}",
                category="backup_database",
                private=True,
            ),
            _source_file_archive_member(
                manifest_file_path,
                f"backup/{manifest_file_path.name}",
                category="backup_manifest",
                private=True,
            ),
        ]
        backup_members_before = [
            member
            for member in source_members
            if member.category in {"backup_database", "backup_manifest"}
        ]
        if (
            _source_inventory_fingerprint(source_members_after)
            != _source_inventory_fingerprint(
                [
                    member
                    for member in source_members
                    if member.category
                    not in {"backup_database", "backup_manifest"}
                ]
            )
            or private_selection_after != private_selection
            or _capture_git_snapshot(workspace_root) != git_snapshot_before
            or _source_inventory_fingerprint(backup_members_after)
            != _source_inventory_fingerprint(backup_members_before)
        ):
            raise runtime.BackupServiceError(
                "[MIGRATION_BUNDLE_SOURCE_CHANGED] 作成中にworkspaceまたは運用資産が変更されました。操作を止めて再実行してください。"
            )
    except Exception:
        bundle_file.close()
        raise

    bundle_file.seek(0)
    return bundle_file, build_backup_migration_bundle_filename(backup_run)


def _render_backup_migration_guide_markdown(
    guide: dict[str, object],
    bundle_entries: list[dict[str, object]],
    *,
    bundle_filename: str,
    bundle_root_dir: str,
) -> str:
    lines = [
        "# TempleDB お引越しセット",
        "",
        "この tar.gz には、現在のdirty/untracked状態と`.git`を含むTempleDB workspace、選んだbackup、機密・運用資産の隔離snapshotが入っています。",
        "新しいMacではこの archive を展開して `TempleDB/` へ入り、guide の手順に従って復元してください。",
        f"機密・運用資産は誤起動を防ぐため `{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/` に隔離されており、確認前に一括上書きしません。",
        "",
        "## 引越し準備",
        f"- 状態: {guide.get('readiness_label', '-')}",
        f"- Python 要件: {guide.get('python_requirement', '-')}",
        f"- archive: {bundle_filename}",
        f"- 展開後の作業 directory: {bundle_root_dir}/{WORKSPACE_ARCHIVE_ROOT}/",
    ]
    backup_run = guide.get("backup_run")
    if backup_run is not None:
        lines.extend(
            [
                f"- バックアップファイル: {_backup_artifact_filename(backup_run, default='-')}",
                f"- SHA256: {getattr(backup_run, 'backup_sha256', '-') or '-'}",
                f"- 保存先: {getattr(backup_run, 'destination_path', '-') or '-'}",
            ]
        )

    warnings = guide.get("warnings") or []
    if warnings:
        lines.extend(["", "## 注意", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    lines.extend(["", "## bundle に入っているもの", ""])
    for item in bundle_entries:
        status = "あり" if item.get("included") else "なし"
        lines.append(
            f"- `{item['path']}`: {item['label']} ({status})。{item['description']}"
        )

    old_mac_steps = guide.get("old_mac_steps") or []
    if old_mac_steps:
        lines.extend(["", "## 旧Macでやること", ""])
        for index, step in enumerate(old_mac_steps, start=1):
            lines.append(f"{index}. {step}")

    new_mac_requirements = guide.get("new_mac_requirements") or []
    if new_mac_requirements:
        lines.extend(["", "## 新しいMacに入れるもの", ""])
        for requirement in new_mac_requirements:
            lines.append(f"- {requirement}")

    command_groups = guide.get("command_groups") or []
    if command_groups:
        lines.extend(["", "## 新しいMacで打つコマンド", ""])
        for group in command_groups:
            lines.append(f"### {group['title']}")
            lines.append("")
            lines.append("```bash")
            for command in group["commands"]:
                lines.append(str(command))
            lines.append("```")
            lines.append("")

    post_restore_checks = guide.get("post_restore_checks") or []
    if post_restore_checks:
        lines.extend(["## 引越し後の確認", ""])
        for index, step in enumerate(post_restore_checks, start=1):
            lines.append(f"{index}. {step}")

    additional_sections = (
        ("private_payload_restore_steps", "機密・運用snapshotの復元"),
        ("tailscale_cutover_steps", "Tailscale切替"),
        ("google_calendar_cutover_steps", "Googleカレンダー切替"),
        ("cutover_safety_steps", "本番切替の安全確認"),
    )
    for context_key, title in additional_sections:
        steps = guide.get(context_key) or []
        if not steps:
            continue
        lines.extend(["", f"## {title}", ""])
        for index, step in enumerate(steps, start=1):
            lines.append(f"{index}. {step}")

    return "\n".join(lines).strip() + "\n"


def _collect_runtime_versions(backup_run, verification_run) -> dict[str, object]:
    runtime = _backup_module()
    return {
        "generated_at": runtime.timezone.localtime(runtime.timezone.now()).isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "django": django.get_version(),
        "database_engine": getattr(backup_run, "database_engine", "") or "",
        "sqlite": sqlite3.sqlite_version,
        "gunicorn": _import_module_version("gunicorn"),
        "psql": _postgresql_tool_version(runtime, "psql"),
        "pg_restore": _postgresql_tool_version(runtime, "pg_restore"),
        "caddy": _run_version_command(["caddy", "version"]),
        "git_head": _run_version_command(["git", "rev-parse", "HEAD"]),
        "backup_file_name": _backup_artifact_filename(backup_run, default=""),
        "backup_sha256": getattr(backup_run, "backup_sha256", "") or "",
        "verification_database_name": getattr(verification_run, "verification_database_name", "")
        or "",
        "verification_status": getattr(verification_run, "status", "") or "",
    }


def _postgresql_tool_version(runtime, command_name: str) -> str:
    try:
        executable = runtime.ensure_command_available(command_name) or command_name
    except Exception:
        return ""
    return _run_version_command([executable, "--version"])


def _import_module_version(module_name: str) -> str:
    try:
        module = __import__(module_name)
    except Exception:
        return ""
    return str(getattr(module, "__version__", "") or "")


def _run_version_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return completed.stdout.strip() or completed.stderr.strip()


def _render_workspace_exclusions() -> str:
    lines = [
        "TempleDB active workspace snapshot から除外・隔離するもの",
        "",
        "- .venv/: 仮想環境は新しいMacで再作成する",
        "- staticfiles/: collectstatic で再生成する",
        "- templedb.egg-info/: editable install で再生成する",
        f"- data/generated/: cache subtreeだけを除外し、残りは `{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/data/generated/` に隔離して保持する",
        "- data/product/: 稼働中のSQLite正本とWAL等は含めず、検証済みbackupだけを bundle の backup/ に別枠で含める",
        f"- data/runtime/: SQLite本体/sidecar、PID、lock、guard、tempだけを除外し、status/progress/state/source registryは `{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/data/runtime/` に隔離する",
        "- workspace内の現在のSQLite DB path: data/product/以外に設定されていても、正本と -wal / -shm / -journal は含めない",
        f"- data/private/: `{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/data/private/` にowner-onlyで隔離する。"
        f"郵便振込PDF証跡だけは互換path `{POSTAL_SCAN_BUNDLE_ROOT.as_posix()}/` に別枠で含め、重複させない",
        "- __pycache__/, .pytest_cache/, .ruff_cache/, .mypy_cache/: cache を持ち込まない",
        f"- .env: active workspace直下には置かず、`{PRIVATE_MIGRATION_WORKSPACE_ROOT.as_posix()}/.env` にowner-onlyで隔離する",
        "- .DS_Store: Finder 由来の不要ファイル",
        "",
        "`.git`、tracked/untracked変更、private source/CSV/credential/font、source registry、cache以外のgenerated、DB/PID/lock/temp以外のruntime stateはbundle全体manifestとSHA256の対象です。",
    ]
    return "\n".join(lines).strip() + "\n"
