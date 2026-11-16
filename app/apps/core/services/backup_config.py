from __future__ import annotations

import getpass
import json
import shlex
import stat
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core.models import (
    DatabaseBackupRun,
    DatabaseBackupSetting,
    DatabaseBackupVerificationRun,
)

BACKUP_DESTINATION_ENV_NAME = "TEMPLEDB_BACKUP_DESTINATION_PATH"


def _backup_module():
    from . import backup

    return backup


def is_postgresql_configured() -> bool:
    engine = settings.DATABASES["default"]["ENGINE"]
    return engine == "django.db.backends.postgresql"


def is_product_sqlite_configured() -> bool:
    engine = settings.DATABASES["default"]["ENGINE"]
    return bool(
        engine == "django.db.backends.sqlite3"
        and getattr(settings, "TEMPLEDB_PRODUCT_SQLITE_MODE", False)
    )


def current_database_engine() -> str:
    engine = settings.DATABASES["default"]["ENGINE"]
    if engine == "django.db.backends.postgresql":
        return "postgresql"
    if engine == "django.db.backends.sqlite3":
        return "sqlite"
    raise _backup_module().BackupServiceError(
        f"未対応のDBエンジンです: {engine}"
    )


def is_database_backup_supported() -> bool:
    runtime = _backup_module()
    return runtime.is_postgresql_configured() or runtime.is_product_sqlite_configured()


def backup_runs_for_current_engine():
    return DatabaseBackupRun.objects.filter(
        database_engine=_backup_module().current_database_engine()
    )


def verification_runs_for_current_engine():
    return DatabaseBackupVerificationRun.objects.filter(
        backup_run__database_engine=_backup_module().current_database_engine()
    )


def get_or_create_backup_setting() -> DatabaseBackupSetting:
    setting, _created = DatabaseBackupSetting.objects.get_or_create(singleton_key=1)
    return setting


def effective_backup_destination_path(setting: DatabaseBackupSetting) -> str:
    env_value = (
        getattr(settings, BACKUP_DESTINATION_ENV_NAME, "") or ""
    ).strip()
    if env_value:
        if "\x00" in env_value:
            raise _backup_module().BackupServiceError(
                f"{BACKUP_DESTINATION_ENV_NAME}に使用できない文字が含まれています。"
            )
        path = Path(env_value)
        if not path.is_absolute():
            raise _backup_module().BackupServiceError(
                f"{BACKUP_DESTINATION_ENV_NAME}は絶対pathで指定してください。"
            )
        if path.parent == path or any(part in {".", ".."} for part in path.parts):
            raise _backup_module().BackupServiceError(
                f"{BACKUP_DESTINATION_ENV_NAME}にroot、'.'、'..'は指定できません。"
            )
        return str(path)
    return (setting.destination_path or "").strip()


def backup_destination_path_source(setting: DatabaseBackupSetting) -> str:
    if (getattr(settings, BACKUP_DESTINATION_ENV_NAME, "") or "").strip():
        return "env"
    if (setting.destination_path or "").strip():
        return "database_compatibility"
    return "unset"


def backup_destination_status_for_setting(
    setting: DatabaseBackupSetting,
) -> dict[str, object]:
    source = backup_destination_path_source(setting)
    try:
        destination_path = effective_backup_destination_path(setting)
    except _backup_module().BackupServiceError as exc:
        return {
            "configured": True,
            "connected": False,
            "path": (
                getattr(settings, BACKUP_DESTINATION_ENV_NAME, "") or ""
            ).strip(),
            "source": source,
            "error": str(exc),
        }
    status = backup_destination_status(destination_path)
    return {
        **status,
        "source": source,
        "error": "",
    }


def list_available_volumes(*, volumes_root: Path | None = None) -> list[dict[str, str]]:
    runtime = _backup_module()
    root = volumes_root or runtime.VOLUMES_ROOT
    if not root.exists():
        return []
    volumes = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        volumes.append({"name": entry.name, "label": entry.name, "path": str(entry)})
    return volumes


def split_destination_path(destination_path: str) -> tuple[str, str] | None:
    runtime = _backup_module()
    raw_path = (destination_path or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        relative = path.relative_to(runtime.VOLUMES_ROOT)
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    volume_name = parts[0]
    subdirectory = "/".join(parts[1:]) if len(parts) > 1 else "TempleDBBackups"
    return volume_name, subdirectory


def backup_destination_status(destination_path: str) -> dict[str, object]:
    raw_path = (destination_path or "").strip()
    if not raw_path:
        return {"configured": False, "connected": False, "path": ""}
    path = Path(raw_path)
    return {
        "configured": True,
        "connected": path.exists() and path.is_dir(),
        "path": str(path),
    }


def next_scheduled_run_label(setting: DatabaseBackupSetting) -> str:
    runtime = _backup_module()
    if not runtime.is_database_backup_supported():
        return "本運用DB（PostgreSQL / SQLite）で利用できます。"
    destination_status = backup_destination_status_for_setting(setting)
    if destination_status["error"]:
        return str(destination_status["error"])
    if not destination_status["configured"]:
        return "保存先が未設定です。"
    if not setting.daily_enabled:
        return "自動バックアップは停止中です。"
    today = timezone.localdate()
    if (
        setting.last_scheduled_attempt_on == today
        and setting.last_scheduled_attempt_engine == runtime.current_database_engine()
    ):
        return "本日分の日次バックアップは実行済みです。"
    return "認証済みアクセス時に、次の画面遷移で日次バックアップを判定します。"


def next_scheduled_verification_label(setting: DatabaseBackupSetting) -> str:
    runtime = _backup_module()
    if not runtime.is_database_backup_supported():
        return "本運用DB（PostgreSQL / SQLite）で利用できます。"
    destination_status = backup_destination_status_for_setting(setting)
    if destination_status["error"]:
        return str(destination_status["error"])
    if not destination_status["configured"]:
        return "保存先が未設定です。"
    if not setting.weekly_verification_enabled:
        return "週次自動テスト復元は停止中です。"
    if runtime.latest_successful_backup_run() is None:
        return "成功バックアップの作成後に判定します。"

    latest_success = runtime.latest_successful_verification_run()
    if latest_success is None or latest_success.finished_at is None:
        return "次の認証済みアクセス時に判定します。"

    next_due_at = latest_success.finished_at + timedelta(
        days=runtime.WEEKLY_VERIFICATION_INTERVAL_DAYS
    )
    if next_due_at <= runtime.timezone.now():
        return "次の認証済みアクセス時に判定します。"
    due_label = runtime.timezone.localtime(next_due_at).strftime("%Y-%m-%d %H:%M")
    return f"{due_label} 以降の認証済みアクセス時に判定します。"


def ensure_destination_directory(volume_name: str, subdirectory_name: str) -> Path:
    destination_path = resolve_destination_path(volume_name, subdirectory_name)
    destination_path.mkdir(parents=True, exist_ok=True)
    probe_path = destination_path / ".templedb-write-check"
    try:
        probe_path.write_text("ok\n", encoding="utf-8")
    except OSError as exc:
        raise _backup_module().BackupServiceError(
            f"保存先へ書き込めませんでした: {destination_path}"
        ) from exc
    finally:
        if probe_path.exists():
            probe_path.unlink()
    return destination_path


def resolve_destination_path(volume_name: str, subdirectory_name: str) -> Path:
    runtime = _backup_module()
    volume_path = runtime.VOLUMES_ROOT / volume_name
    if not volume_path.exists() or not volume_path.is_dir():
        raise runtime.BackupServiceError(f"外部ディスク {volume_name} が接続されていません。")
    return volume_path / subdirectory_name


def recent_backup_runs(*, limit: int = 10) -> list[DatabaseBackupRun]:
    return list(backup_runs_for_current_engine().order_by("-started_at", "-id")[:limit])


def recent_verification_runs(*, limit: int = 10) -> list[DatabaseBackupVerificationRun]:
    return list(
        verification_runs_for_current_engine().select_related("backup_run")
        .order_by("-started_at", "-id")[:limit]
    )


def latest_successful_verification_run() -> DatabaseBackupVerificationRun | None:
    return (
        verification_runs_for_current_engine().select_related("backup_run")
        .filter(status="succeeded")
        .exclude(finished_at__isnull=True)
        .order_by("-finished_at", "-id")
        .first()
    )


def latest_successful_scheduled_verification_run() -> DatabaseBackupVerificationRun | None:
    return (
        verification_runs_for_current_engine().select_related("backup_run")
        .filter(trigger_kind="scheduled", status="succeeded")
        .exclude(finished_at__isnull=True)
        .order_by("-finished_at", "-id")
        .first()
    )


def latest_successful_backup_run() -> DatabaseBackupRun | None:
    return (
        backup_runs_for_current_engine().filter(status="succeeded")
        .exclude(started_at__isnull=True)
        .order_by("-started_at", "-id")
        .first()
    )


def latest_failed_backup_run() -> DatabaseBackupRun | None:
    return (
        backup_runs_for_current_engine()
        .filter(status="failed")
        .order_by("-started_at", "-id")
        .first()
    )


def latest_verification_for_backup_run(
    backup_run: DatabaseBackupRun,
) -> DatabaseBackupVerificationRun | None:
    return (
        verification_runs_for_current_engine()
        .filter(backup_run=backup_run)
        .order_by("-started_at", "-id")
        .first()
    )


def _backup_manifest_matches_run(backup_run: DatabaseBackupRun) -> bool:
    raw_path = (backup_run.manifest_file_path or "").strip()
    if not raw_path:
        return False
    manifest_path = Path(raw_path)
    try:
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            return False
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        backup_path = Path((backup_run.backup_file_path or "").strip())
        actual_size = backup_path.stat().st_size
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return {
        "backup_run_id": payload.get("backup_run_id"),
        "backup_file_name": payload.get("backup_file_name"),
        "backup_file_size": payload.get("backup_file_size"),
        "backup_sha256": str(payload.get("backup_sha256") or "").strip().lower(),
    } == {
        "backup_run_id": backup_run.id,
        "backup_file_name": backup_path.name,
        "backup_file_size": actual_size,
        "backup_sha256": (backup_run.backup_sha256 or "").strip().lower(),
    }


def _is_single_link_regular_file(path: Path) -> bool:
    try:
        file_stat = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(file_stat.st_mode) and file_stat.st_nlink == 1


def _migration_workspace_readiness(workspace_root: Path) -> tuple[bool, bool]:
    env_ready = _is_single_link_regular_file(workspace_root / ".env")
    git_root = workspace_root / ".git"
    try:
        workspace_stat = workspace_root.lstat()
        git_stat = git_root.lstat()
    except OSError:
        return env_ready, False
    git_metadata_ready = bool(
        stat.S_ISDIR(workspace_stat.st_mode)
        and stat.S_ISDIR(git_stat.st_mode)
        and workspace_stat.st_dev == git_stat.st_dev
        and _is_single_link_regular_file(git_root / "HEAD")
    )
    return env_ready, git_metadata_ready


def _canonical_backup_artifact_name(backup_run, *, default: str) -> str:
    backup_file_path = (getattr(backup_run, "backup_file_path", "") or "").strip()
    if not backup_file_path:
        return default
    return Path(backup_file_path).name or default


def _quoted_bundle_relative_path(path: str) -> str:
    return shlex.quote(f"./{path}")


def _backup_migration_common_context(
    *,
    migration_bundle_filename: str,
    migration_bundle_root_dir: str,
    database_requirement: str,
) -> dict[str, object]:
    bundle_name = migration_bundle_filename or "<backup>_migration_bundle.tar.gz"
    bundle_root = migration_bundle_root_dir or "<backup>_migration_bundle"
    return {
        "old_mac_steps": [
            "TempleDB の作業ディレクトリで `git status --short --branch` と `git branch --all` を記録する。未コミット・未追跡の現状も引越し対象なので、作成のために勝手に削除・初期化しない。",
            "管理者で /settings/backup/ を開き、引越し直前のバックアップを作成する。",
            "その同じバックアップに「別DBへテスト復元」を実行し、成功と manifest の存在を確認する。",
            f"`このバックアップで引越し` 画面で `お引越しセット作成` を押し、`{bundle_name}` を作る。",
            (
                "セットには Git履歴・ブランチ、.env、tenant policy、tenant preferences、"
                "CSV/MDB・credential・fontを含む "
                "TEMPLEDB_TENANT_ROOT配下のdata/private/、source registry、必要な運用資産が入る。"
                "未設定時は従来どおりTempleDB workspace配下を使う。暗号化ディスク等で"
                "新Macへ直接渡し、クラウドや共有フォルダへ無暗号で置かない。"
            ),
            "最終バックアップ後は旧Macへの新規入力を止め、新Macを正本にする直前に `TempleDB Server Stop.command` で旧Macのサーバーを停止する。",
            "新Macの確認と新しいバックアップのテスト復元が終わるまで、旧Macは停止状態の rollback 元として残す。",
        ],
        "new_mac_requirements": [
            "Homebrew が使える Mac であること。",
            f"`{bundle_name}` を新しいMacの暗号化されたローカル領域で展開できること。",
            "pyenv を入れ、Python 3.13.12 を TempleDB directory で固定できること。",
            database_requirement,
            "TempleDB Server.command を使う場合は Homebrew 版 Caddy を入れること。",
            "Tailscale を使う場合は、新Macで同じ tailnet へログインし、hostname と Serve を再設定できること。Tailscaleの端末identity自体はセットに入らない。",
            "新Macのバックアップ保存先にする外部ディスクと、新しい絶対pathを決めておくこと。",
        ],
        "private_payload_restore_steps": [
            f"`{bundle_root}/private/migration_payload/workspace/` を、TempleDB workspace と分けた隔離領域として扱う。`pwd -P` で workspace と payload の絶対pathを確認する。",
            (
                "docs/archive_manifest.json、docs/checksums.txt、private/migration_payload/MANIFEST.json "
                "を確認してから、payload/workspace/ の .env、credentialを除く data/private/ "
                "全entry、data/generated/ を新MacのTEMPLEDB_TENANT_ROOTへ戻す。未設定で"
                "従来配置を維持する場合だけTempleDB workspaceをtenant rootとして使う。"
                "郵便振込PDF証跡だけはprivate/annual_membership_fee_postal_scans/から"
                "同じtenant root配下の元の場所へ戻す。"
            ),
            "TEMPLEDB_TENANT_ROOT/data/runtime/ は一括上書きせず、source_registry.json だけを戻す。その他のstatus/progress JSONは参照用に隔離保持し、必要なものだけAIと確認して選択復元する。",
            "credential は旧Macを停止し、新URLとGoogle Calendar設定が確定するまで payload 側に隔離したままにする。それまで新MacからGoogle同期は行わない。",
            ".env の SQLite DB、Google credential、private source など機械固有pathを新Macの絶対pathに直し、そのpathが実在することを確認する。",
            ".venv、staticfiles、cache、PID/lock/temp、稼働中SQLiteの WAL/SHM は復元せず、新Macで再生成する。",
        ],
        "tailscale_cutover_steps": [
            "現在のURLを維持するか、新しいTailscale hostname/URLへ変えるかを決める。",
            "現在のURLを維持する場合は、旧Macを停止して旧hostnameの競合を解消した後に、新Macへ同じhostnameを設定する。",
            "URLを変える場合は、.env の DJANGO_ALLOWED_HOSTS、DJANGO_CSRF_TRUSTED_ORIGINS、TEMPLEDB_BASE_URL、TEMPLEDB_EXTERNAL_BASE_URL を新URLへ更新する。",
            (
                "TEMPLEDB_TAILSCALE_SERVE=auto として TempleDB Server.command を起動後、"
                "`tailscale status` と `tailscale serve status` で https://*.ts.net から "
                "http://127.0.0.1:8000 への proxy を確認する。"
            ),
            "Caddy と Tailscale Serve はファイル移送だけで完了しない。新Mac上の実process、port、HTTPS URL を確認する。",
        ],
        "google_calendar_cutover_steps": [
            "Google Calendar ID は変えず、旧Macと同じ Service Account credential を使う。そうすれば既存のGoogle予定IDを使って更新できる。",
            "別DBテスト復元が証明するのはDBの復元と内容の読み取りまでで、Google APIへの到達性は含まない。外部接続は後述の1件同期で確認する。",
            "旧Macのサーバー停止と新URL確定が終わるまで、新Macにcredentialを有効配置しない。両Macから同時に同期しない。",
            "新Macの「設定 > Google カレンダー」で TempleDB URL（内部）/（外部）を新URLへ更新する。DBに保存されたこのURLは .env より優先される。",
            (
                "Calendar ID、新URL、既存bindingを先に確認した後、新Macのサーバー停止中に "
                "`rsync -a ../private/migration_payload/workspace/data/private/credentials/ "
                '"$TENANT_ROOT/data/private/credentials/"` でcredentialを戻し、.env が指す'
                "TEMPLEDB_TENANT_ROOT配下の絶対pathで読めるようにする。"
            ),
            (
                "新MacのTempleDBサーバーを停止したまま、`.venv/bin/python manage.py "
                "reconcile_google_calendar_sync --schedule-id <既存法要ID>` を実行する。"
                "Google側の同じ予定IDが更新され、重複作成されないことを1件で確認する。"
            ),
            (
                "1件確認後に新Macのサーバーを起動する。最初の認証済みアクセスで"
                "残りの自動照合が起動し得る。起動しない場合は「既存法要を一括同期」を実行する。"
                "大量の新規作成が出たら停止してCalendar IDとbindingを再確認する。"
            ),
        ],
        "cutover_safety_steps": [
            "新Macはまず localhost だけで起動し、件数、主要画面、ユーザー、帳票、private資産を確認する。",
            "外部公開やGoogle credential有効化の前に、新Macの.envでTEMPLEDB_BACKUP_DESTINATION_PATHを新しい絶対pathへ設定し、再起動後に「設定 > バックアップ」で同じpathと接続中表示を確認する。",
            "新Macで手動バックアップを1回作成し、その同じrunを別DBへテスト復元する。",
            "最終バックアップ後の旧Macに入力差分がないことと、旧MacのTempleDBが停止していることを確認してから、新Macを正本にする。",
            "rollbackする場合も新Macを先に停止し、2台同時を避けて旧Macだけを再開する。",
        ],
    }


def build_backup_migration_guide_context(
    backup_run: DatabaseBackupRun | None,
) -> dict[str, object]:
    runtime = _backup_module()
    workspace_env_ready, git_metadata_ready = _migration_workspace_readiness(
        Path(runtime.BASE_DIR)
    )
    verification_run = (
        latest_verification_for_backup_run(backup_run) if backup_run is not None else None
    )
    artifact_exists = bool(
        backup_run and backup_run.backup_file_path and Path(backup_run.backup_file_path).exists()
    )
    manifest_exists = bool(
        backup_run and backup_run.manifest_file_path and Path(backup_run.manifest_file_path).exists()
    )
    manifest_matches_run = bool(
        backup_run and manifest_exists and _backup_manifest_matches_run(backup_run)
    )
    verification_state = "none"
    if verification_run is not None:
        verification_state = verification_run.status
    verification_finished = bool(
        verification_run is not None and verification_run.finished_at is not None
    )
    verification_summary_ready = bool(
        verification_run is not None
        and isinstance(verification_run.verification_summary, dict)
        and verification_run.verification_summary
    )

    warnings: list[str] = []
    bundle_blockers: list[str] = []
    if not workspace_env_ready:
        message = "現行checkoutの .env が通常ファイルとして見つかりません。安全に収録できる .env を用意してください。"
        warnings.append(message)
        bundle_blockers.append(message)
    if not git_metadata_ready:
        message = "現行checkoutの .git/HEAD が通常ファイルとして見つかりません。完全なGit履歴を確認してください。"
        warnings.append(message)
        bundle_blockers.append(message)
    if backup_run is None:
        message = "まだ成功バックアップがありません。先に /settings/backup/ でバックアップを作成してください。"
        warnings.append(message)
        bundle_blockers.append(message)
    else:
        if backup_run.status != "succeeded":
            message = "選択中のバックアップは成功扱いではありません。引越し元として使う前に再作成してください。"
            warnings.append(message)
            bundle_blockers.append(message)
        if not artifact_exists:
            message = "バックアップファイルが現在の保存先に見つかりません。外部ディスクの接続先とファイルの所在を確認してください。"
            warnings.append(message)
            bundle_blockers.append(message)
        if not manifest_exists:
            message = "manifest が見つかりません。同じ backup run の .json が揃うまでお引越しセットは作成できません。"
            warnings.append(message)
            bundle_blockers.append(message)
        elif not manifest_matches_run:
            message = "manifest が選択中の backup run、ファイル名、size、SHA256と一致しません。同じrunの正しい .json を揃えてください。"
            warnings.append(message)
            bundle_blockers.append(message)
        if verification_run is None:
            message = "このバックアップはまだ別DBへテスト復元していません。旧Macで同じバックアップに「別DBへテスト復元」を成功させるまで作成できません。"
            warnings.append(message)
            bundle_blockers.append(message)
        elif verification_run.status != "succeeded":
            message = "このバックアップの最新の別DBテスト復元が成功していません。同じバックアップのテスト復元が成功するまで作成できません。"
            warnings.append(message)
            bundle_blockers.append(message)
        elif not verification_finished:
            message = "このバックアップの最新の別DBテスト復元は完了時刻が記録されていません。完了したテスト復元をやり直してください。"
            warnings.append(message)
            bundle_blockers.append(message)
        elif not verification_summary_ready:
            message = "このバックアップの最新の別DBテスト復元に確認結果の件数要約がありません。内容確認まで完了したテスト復元をやり直してください。"
            warnings.append(message)
            bundle_blockers.append(message)

    can_create_bundle = bool(backup_run is not None and not bundle_blockers)

    migration_bundle_filename = (
        runtime.build_backup_migration_bundle_filename(backup_run) if backup_run is not None else ""
    )
    migration_bundle_root_dir = (
        runtime.build_backup_migration_bundle_root_dir(backup_run) if backup_run is not None else ""
    )
    if backup_run is not None and backup_run.database_engine == "sqlite":
        return _build_sqlite_backup_migration_guide_context(
            backup_run=backup_run,
            artifact_exists=artifact_exists,
            manifest_exists=manifest_exists,
            manifest_matches_run=manifest_matches_run,
            verification_run=verification_run,
            verification_state=verification_state,
            verification_finished=verification_finished,
            verification_summary_ready=verification_summary_ready,
            workspace_env_ready=workspace_env_ready,
            git_metadata_ready=git_metadata_ready,
            warnings=warnings,
            bundle_blockers=bundle_blockers,
            can_create_bundle=can_create_bundle,
            migration_bundle_filename=migration_bundle_filename,
            migration_bundle_root_dir=migration_bundle_root_dir,
        )
    artifact_name = (
        _canonical_backup_artifact_name(backup_run, default="<dump-file>")
        if backup_run is not None
        else "<dump-file>"
    )
    dump_path_example = f"../backup/{artifact_name}"
    restore_command = (
        "pg_restore --exit-on-error --single-transaction --no-owner --no-privileges "
        f"--username=templedb -d templedb -- {shlex.quote(dump_path_example)}"
    )

    readiness_label = "未準備"
    if can_create_bundle:
        readiness_label = "引越しに使える候補"
    elif backup_run is not None and backup_run.status == "succeeded" and artifact_exists:
        readiness_label = "要テスト復元"

    return {
        "database_engine": (
            backup_run.database_engine
            if backup_run is not None
            else runtime.current_database_engine()
        ),
        "database_engine_label": (
            "SQLite"
            if backup_run is None and runtime.current_database_engine() == "sqlite"
            else "PostgreSQL"
        ),
        "backup_run": backup_run,
        "artifact_exists": artifact_exists,
        "manifest_exists": manifest_exists,
        "manifest_matches_run": manifest_matches_run,
        "verification_run": verification_run,
        "verification_state": verification_state,
        "verification_finished": verification_finished,
        "verification_summary_ready": verification_summary_ready,
        "workspace_env_ready": workspace_env_ready,
        "git_metadata_ready": git_metadata_ready,
        "readiness_label": readiness_label,
        "warnings": warnings,
        "bundle_blockers": bundle_blockers,
        "can_create_bundle": can_create_bundle,
        "python_requirement": "Python 3.13 系",
        "migration_bundle_filename": migration_bundle_filename,
        "migration_bundle_root_dir": migration_bundle_root_dir,
        **_backup_migration_common_context(
            migration_bundle_filename=migration_bundle_filename,
            migration_bundle_root_dir=migration_bundle_root_dir,
            database_requirement=(
                "Homebrew 版 PostgreSQL 17 を使い、非superuser roleと空のTempleDBを新規作成すること。"
                "roleまたはDBが既にあれば停止し、既存DBへ復元しないこと。"
            ),
        ),
        "command_groups": [
            {
                "title": "1. お引越しセットを展開して TempleDB directory へ入る",
                "commands": [
                    (
                        "test ! -e "
                        f"{_quoted_bundle_relative_path(migration_bundle_root_dir or '<backup>_migration_bundle')} "
                        "&& test ! -L "
                        f"{_quoted_bundle_relative_path(migration_bundle_root_dir or '<backup>_migration_bundle')} "
                        "&& tar -xzf "
                        f"{_quoted_bundle_relative_path(migration_bundle_filename or '<backup>_migration_bundle.tar.gz')}"
                    ),
                    (
                        "cd -- "
                        f"{_quoted_bundle_relative_path(migration_bundle_root_dir or '<backup>_migration_bundle')}"
                    ),
                    "shasum -a 256 -c docs/checksums.txt",
                    "cd TempleDB",
                    "git fsck --full",
                    "git rev-parse HEAD",
                    "git status --short --branch",
                    "git branch --all",
                    "git log --oneline -5",
                ],
            },
            {
                "title": "2. Homebrew と Python を揃える",
                "commands": [
                    "brew install pyenv",
                    "brew install postgresql@17",
                    "pyenv install 3.13.12",
                    "pyenv local 3.13.12",
                ],
            },
            {
                "title": "3. 仮想環境を作って TempleDB を入れる",
                "commands": [
                    "python -m venv .venv",
                    "source .venv/bin/activate",
                    "python -m pip install --upgrade pip",
                    "python -m pip install -e .",
                    "python -m pip install -e '.[dev]'  # pytest / ruff も使う場合",
                ],
            },
            {
                "title": "4. PostgreSQL を起動して新規の非superuser roleと空DBを作る",
                "commands": [
                    "brew services run postgresql@17",
                    "# roleまたはDBが既に存在して失敗したら停止し、既存DBへ復元しない",
                    "# 隔離payloadの.envにあるDATABASE_NAME/USER/PASSWORDを秘密値を表示せず確認し、role/dbと一致させる。変更時は.envも同時更新する",
                    "createuser --no-superuser --no-createdb --no-createrole --pwprompt templedb",
                    "createdb --owner=templedb --encoding=UTF8 templedb",
                ],
            },
            {
                "title": "5. 隔離payloadから機械固有設定と運用資産を戻す",
                "commands": [
                    'WORKSPACE_DIR="$(pwd -P)"',
                    'TENANT_ROOT="$WORKSPACE_DIR"  # 分離する場合は新Mac上の絶対pathへ変更',
                    'PAYLOAD_DIR="$(cd ../private/migration_payload/workspace && pwd -P)"',
                    'test -f "../private/migration_payload/MANIFEST.json"',
                    'test -f "../docs/archive_manifest.json"',
                    'test "$PAYLOAD_DIR" != "$WORKSPACE_DIR"',
                    'cp -p "$PAYLOAD_DIR/.env" "$WORKSPACE_DIR/.env"',
                    "# DATABASE_NAME/USER/PASSWORDがstep 4で作成したrole/dbと一致することを秘密値を表示せず確認する",
                    'mkdir -p "$TENANT_ROOT/config/tenant_policy" "$TENANT_ROOT/config/tenant_preferences" "$TENANT_ROOT/data/private" "$TENANT_ROOT/data/runtime" "$TENANT_ROOT/data/generated"',
                    '[ ! -d "$PAYLOAD_DIR/config/tenant_policy/default" ] || cp -Rp "$PAYLOAD_DIR/config/tenant_policy/default" "$TENANT_ROOT/config/tenant_policy/"',
                    '[ ! -d "$PAYLOAD_DIR/config/tenant_preferences" ] || cp -Rp "$PAYLOAD_DIR/config/tenant_preferences/." "$TENANT_ROOT/config/tenant_preferences/"',
                    'rsync -a --exclude="credentials/" "$PAYLOAD_DIR/data/private/" "$TENANT_ROOT/data/private/"',
                    '[ ! -d "$PAYLOAD_DIR/data/generated" ] || cp -Rp "$PAYLOAD_DIR/data/generated/." "$TENANT_ROOT/data/generated/"',
                    '[ ! -f "$PAYLOAD_DIR/data/runtime/source_registry.json" ] || cp -p "$PAYLOAD_DIR/data/runtime/source_registry.json" "$TENANT_ROOT/data/runtime/source_registry.json"',
                    '# data/runtimeのその他のstatus/progress JSONは隔離保持し、必要なものだけ選択復元する',
                    '# credentialは旧Mac停止と新URL確定まで payload側に隔離する',
                    '[ ! -d ../private/annual_membership_fee_postal_scans ] || cp -Rp ../private/annual_membership_fee_postal_scans "$TENANT_ROOT/data/private/auxiliary/"',
                    'chmod 600 "$WORKSPACE_DIR/.env"  # 復元後',
                    '# .envのTEMPLEDB_TENANT_ROOTとその他の機械固有pathを新Macの絶対pathに直し、test -eで確認する',
                    "brew install caddy  # TempleDB Server.command を使う前に、まだ無ければ",
                ],
            },
            {
                "title": "6. dump を復元してアプリ確認する",
                "commands": [
                    restore_command,
                    "python manage.py migrate --noinput",
                    "python manage.py check",
                    "open \"TempleDB Server.command\"",
                    "python manage.py runserver 0.0.0.0:8000  # fallback が必要な時だけ",
                    "open \"TempleDB Console.command\"  # fallback が必要な時だけ",
                ],
            },
        ],
        "restore_command": restore_command,
        "dump_path_example": dump_path_example,
        "post_restore_checks": [
            "TempleDB directory に `.git` が残り、`git status --short --branch`、`git branch --all`、`git log --oneline -5` が旧Macで記録した現状と合うことを確認する。",
            ".env と private source / credential / SQLiteなどの機械固有pathが新Macの絶対pathを指し、各file/directoryが実在することを確認する。",
            (
                "TEMPLEDB_TENANT_ROOT配下のconfig/tenant_policy/default/、"
                "config/tenant_preferences/、"
                "data/runtime/source_registry.json、data/private/、data/generated/と、"
                "payload側に残したruntime参照snapshotを MANIFEST.json と照合する。"
            ),
            ".venv/bin/python manage.py check が通ることを確認する。",
            "TempleDB Server.command でまず localhost のトップ画面を開き、主要画面と代表データの件数を確認する。",
            "新Macの.envでTEMPLEDB_BACKUP_DESTINATION_PATHを外部ディスクの絶対pathへ設定し、再起動後に /settings/backup/ で同じpathと接続中表示を確認する。",
            ".venv/bin/python manage.py verify_membership_fee_postal_scans を実行し、郵便振込PDF証跡の欠落がないことを確認する。",
            "旧Mac停止後にTailscale/Google Calendarの切替を行い、新Macのサーバー停止中に `reconcile_google_calendar_sync --schedule-id ...` で1件確認してから残りを同期する。",
            "新Macで手動バックアップを1回作成し、その同じrunを別DBへテスト復元する。",
            "旧Macと新MacのTempleDBが同時稼働していないことを確認し、旧Macは停止状態のrollback元として残す。",
        ],
    }


def _build_sqlite_backup_migration_guide_context(
    *,
    backup_run: DatabaseBackupRun,
    artifact_exists: bool,
    manifest_exists: bool,
    manifest_matches_run: bool,
    verification_run: DatabaseBackupVerificationRun | None,
    verification_state: str,
    verification_finished: bool,
    verification_summary_ready: bool,
    workspace_env_ready: bool,
    git_metadata_ready: bool,
    warnings: list[str],
    bundle_blockers: list[str],
    can_create_bundle: bool,
    migration_bundle_filename: str,
    migration_bundle_root_dir: str,
) -> dict[str, object]:
    backup_name = _canonical_backup_artifact_name(
        backup_run,
        default="<backup>.sqlite3",
    )
    backup_source = f"../backup/{backup_name}"
    sqlite_target = "$TENANT_ROOT/data/product/templedb.sqlite3"
    restore_command = (
        f'test ! -e "{sqlite_target}" && test ! -L "{sqlite_target}" '
        f'&& cp -- {shlex.quote(backup_source)} "{sqlite_target}"'
    )
    readiness_label = "未準備"
    if can_create_bundle:
        readiness_label = "引越しに使える候補"
    elif backup_run.status == "succeeded" and artifact_exists:
        readiness_label = "要テスト復元"

    bundle_name = migration_bundle_filename or "<backup>_migration_bundle.tar.gz"
    bundle_root = migration_bundle_root_dir or "<backup>_migration_bundle"
    return {
        "database_engine": "sqlite",
        "database_engine_label": "SQLite",
        "backup_run": backup_run,
        "artifact_exists": artifact_exists,
        "manifest_exists": manifest_exists,
        "manifest_matches_run": manifest_matches_run,
        "verification_run": verification_run,
        "verification_state": verification_state,
        "verification_finished": verification_finished,
        "verification_summary_ready": verification_summary_ready,
        "workspace_env_ready": workspace_env_ready,
        "git_metadata_ready": git_metadata_ready,
        "readiness_label": readiness_label,
        "warnings": warnings,
        "bundle_blockers": bundle_blockers,
        "can_create_bundle": can_create_bundle,
        "python_requirement": "Python 3.13 系",
        "migration_bundle_filename": migration_bundle_filename,
        "migration_bundle_root_dir": migration_bundle_root_dir,
        **_backup_migration_common_context(
            migration_bundle_filename=migration_bundle_filename,
            migration_bundle_root_dir=migration_bundle_root_dir,
            database_requirement=(
                "SQLite は Python に同梱されるため、PostgreSQL のインストールは不要です。"
            ),
        ),
        "command_groups": [
            {
                "title": "1. お引越しセットを展開して TempleDB directory へ入る",
                "commands": [
                    (
                        f"test ! -e {_quoted_bundle_relative_path(bundle_root)} "
                        f"&& test ! -L {_quoted_bundle_relative_path(bundle_root)} "
                        f"&& tar -xzf {_quoted_bundle_relative_path(bundle_name)}"
                    ),
                    f"cd -- {_quoted_bundle_relative_path(bundle_root)}",
                    "shasum -a 256 -c docs/checksums.txt",
                    "cd TempleDB",
                    "git fsck --full",
                    "git rev-parse HEAD",
                    "git status --short --branch",
                    "git branch --all",
                    "git log --oneline -5",
                ],
            },
            {
                "title": "2. Homebrew と Python を揃える",
                "commands": [
                    "brew install pyenv",
                    "pyenv install 3.13.12",
                    "pyenv local 3.13.12",
                ],
            },
            {
                "title": "3. 仮想環境を作って TempleDB を入れる",
                "commands": [
                    "python -m venv .venv",
                    "source .venv/bin/activate",
                    "python -m pip install --upgrade pip",
                    "python -m pip install -e .",
                    "python -m pip install -e '.[dev]'  # pytest / ruff も使う場合",
                ],
            },
            {
                "title": "4. SQLite DBファイルを配置する",
                "commands": [
                    'WORKSPACE_DIR="$(pwd -P)"',
                    'TENANT_ROOT="$WORKSPACE_DIR"  # 分離する場合は新Mac上の絶対pathへ変更',
                    'mkdir -p "$TENANT_ROOT/data/product"',
                    restore_command,
                    f'chmod 600 -- "{sqlite_target}"',
                ],
            },
            {
                "title": "5. 隔離payloadから機械固有設定と運用資産を戻す",
                "commands": [
                    'WORKSPACE_DIR="$(pwd -P)"',
                    'TENANT_ROOT="$WORKSPACE_DIR"  # step 4と同じ絶対path',
                    'PAYLOAD_DIR="$(cd ../private/migration_payload/workspace && pwd -P)"',
                    'test -f "../private/migration_payload/MANIFEST.json"',
                    'test -f "../docs/archive_manifest.json"',
                    'test "$PAYLOAD_DIR" != "$WORKSPACE_DIR"',
                    'cp -p "$PAYLOAD_DIR/.env" "$WORKSPACE_DIR/.env"',
                    'mkdir -p "$TENANT_ROOT/config/tenant_policy" "$TENANT_ROOT/config/tenant_preferences" "$TENANT_ROOT/data/private" "$TENANT_ROOT/data/runtime" "$TENANT_ROOT/data/generated"',
                    '[ ! -d "$PAYLOAD_DIR/config/tenant_policy/default" ] || cp -Rp "$PAYLOAD_DIR/config/tenant_policy/default" "$TENANT_ROOT/config/tenant_policy/"',
                    '[ ! -d "$PAYLOAD_DIR/config/tenant_preferences" ] || cp -Rp "$PAYLOAD_DIR/config/tenant_preferences/." "$TENANT_ROOT/config/tenant_preferences/"',
                    'rsync -a --exclude="credentials/" "$PAYLOAD_DIR/data/private/" "$TENANT_ROOT/data/private/"',
                    '[ ! -d "$PAYLOAD_DIR/data/generated" ] || cp -Rp "$PAYLOAD_DIR/data/generated/." "$TENANT_ROOT/data/generated/"',
                    '[ ! -f "$PAYLOAD_DIR/data/runtime/source_registry.json" ] || cp -p "$PAYLOAD_DIR/data/runtime/source_registry.json" "$TENANT_ROOT/data/runtime/source_registry.json"',
                    '# data/runtimeのその他のstatus/progress JSONは隔離保持し、必要なものだけ選択復元する',
                    '# credentialは旧Mac停止と新URL確定まで payload側に隔離する',
                    '[ ! -d ../private/annual_membership_fee_postal_scans ] || cp -Rp ../private/annual_membership_fee_postal_scans "$TENANT_ROOT/data/private/auxiliary/"',
                    "# .env: TEMPLEDB_DATABASE_ENGINE=sqlite / DATABASE_HOST=",
                    "# .env: TEMPLEDB_TENANT_ROOT=$TENANT_ROOT",
                    "# .env: TEMPLEDB_SQLITE_DB_PATH=$TENANT_ROOT/data/product/templedb.sqlite3",
                    'chmod 600 "$WORKSPACE_DIR/.env"',
                    '# .env内の機械固有pathを新Macの絶対pathに直し、test -eで確認する',
                    "brew install caddy  # TempleDB Server.command を使う前に、まだ無ければ",
                ],
            },
            {
                "title": "6. migration とアプリ確認を行う",
                "commands": [
                    "python manage.py migrate --noinput",
                    "python manage.py check",
                    'open "TempleDB Server.command"',
                    "python manage.py runserver 0.0.0.0:8000  # fallback が必要な時だけ",
                    'open "TempleDB Console.command"  # fallback が必要な時だけ',
                ],
            },
        ],
        "restore_command": restore_command,
        "dump_path_example": backup_source,
        "post_restore_checks": [
            "TempleDB directory に `.git` が残り、`git status --short --branch`、`git branch --all`、`git log --oneline -5` が旧Macで記録した現状と合うことを確認する。",
            "`.env` の TEMPLEDB_SQLITE_DB_PATH が配置したDBファイルの新Mac上の絶対pathを指し、その他の機械固有pathも実在することを確認する。",
            (
                "TEMPLEDB_TENANT_ROOT配下のconfig/tenant_policy/default/、"
                "config/tenant_preferences/、"
                "data/runtime/source_registry.json、data/private/、data/generated/と、"
                "payload側に残したruntime参照snapshotを MANIFEST.json と照合する。"
            ),
            ".venv/bin/python manage.py check が通ることを確認する。",
            "TempleDB Server.command でまず localhost のトップ画面を開き、主要画面と代表データの件数を確認する。",
            "新Macの.envでTEMPLEDB_BACKUP_DESTINATION_PATHを外部ディスクの絶対pathへ設定し、再起動後に /settings/backup/ で同じpathと接続中表示を確認する。",
            ".venv/bin/python manage.py verify_membership_fee_postal_scans を実行し、郵便振込PDF証跡の欠落がないことを確認する。",
            "旧Mac停止後にTailscale/Google Calendarの切替を行い、新Macのサーバー停止中に `reconcile_google_calendar_sync --schedule-id ...` で1件確認してから残りを同期する。",
            "新Macで手動バックアップを1回作成し、その同じrunを別DBへテスト復元する。",
            "旧Macと新MacのTempleDBが同時稼働していないことを確認し、旧Macは停止状態のrollback元として残す。",
        ],
    }


def get_postgres_connection_config():
    runtime = _backup_module()
    if not runtime.is_postgresql_configured():
        raise runtime.BackupServiceError("PostgreSQL 設定が見つかりません。")
    database = runtime.settings.DATABASES["default"]
    return runtime.PostgresConnectionConfig(
        database_name=str(database.get("NAME", "")),
        database_user=str(database.get("USER", "")),
        database_password=str(database.get("PASSWORD", "")),
        database_host=str(database.get("HOST", "")),
        database_port=str(database.get("PORT", "")),
    )


def get_postgres_admin_config():
    runtime = _backup_module()
    database_port = (
        str(runtime.settings.DATABASES["default"].get("PORT", ""))
        if runtime.is_postgresql_configured()
        else ""
    )
    return runtime.PostgresAdminConfig(
        database_name=runtime.os.environ.get("TEMPLEDB_BACKUP_ADMIN_DATABASE", "postgres"),
        database_user=runtime.os.environ.get("TEMPLEDB_BACKUP_ADMIN_USER", getpass.getuser()),
        database_password=runtime.os.environ.get("TEMPLEDB_BACKUP_ADMIN_PASSWORD", ""),
        database_host=runtime.os.environ.get("TEMPLEDB_BACKUP_ADMIN_HOST", ""),
        database_port=runtime.os.environ.get("TEMPLEDB_BACKUP_ADMIN_PORT", database_port),
    )
