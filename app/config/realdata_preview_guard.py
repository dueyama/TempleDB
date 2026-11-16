"""Fail closed before a disposable preview can select any database or tenant."""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path


def load_preview_record(environment=None) -> dict:
    env = os.environ if environment is None else environment
    session = Path(env.get("TEMPLEDB_PREVIEW_SESSION", ""))
    if (not session.is_absolute() or session.resolve() != session
            or not re.fullmatch(r"preview-[a-f0-9]{12}", session.name)):
        raise RuntimeError("専用のテスト領域が指定されていません。")
    for path in (session, session / "tenant", session / "socket"):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or path.resolve() != path
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
            raise RuntimeError("テスト領域の所有者・権限が一致しません。")
    marker = session / "preview.json"
    info = marker.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536):
        raise RuntimeError("テスト環境の記録が不正です。")
    record = json.loads(marker.read_text())
    if (record.get("format") != "templedb-disposable-preview-v1"
            or record.get("session_dir") != str(session)
            or record.get("source_root") != str(Path(__file__).resolve().parents[1])):
        raise RuntimeError("テスト環境の記録が現在の作業フォルダと一致しません。")
    required = {
        "TEMPLEDB_TENANT_ROOT": str(session / "tenant"),
        "TEMPLEDB_DATABASE_ENGINE": "postgresql", "TEMPLEDB_DEMO_MODE": "0",
        "TEMPLEDB_RUNTIME_ROLE": "staging", "TEMPLEDB_STAGING_ALLOW_OPENAI": "0",
        "DATABASE_HOST": str(session / "socket"), "DATABASE_PORT": "55433",
        "DATABASE_NAME": "templedb_preview", "DATABASE_USER": "templedb_preview",
        "DATABASE_PASSWORD": "", "TEMPLEDB_TRUSTED_PROXY_HTTPS": "0",
    }
    if any(env.get(key) != value for key, value in required.items()):
        raise RuntimeError("テスト環境以外の接続・外部連携設定を拒否しました。")
    # libpq can otherwise override an explicit Unix socket with PGHOSTADDR.
    if any(key.startswith("PG") for key in env):
        raise RuntimeError("テスト環境へPostgreSQLの外部設定を継承できません。")
    sentinel = session / "tenant/.env"
    if sentinel.is_symlink() or not sentinel.is_file() or sentinel.read_bytes():
        raise RuntimeError("テスト環境の.envは空でなければなりません。")
    return record


def verify_live_database() -> None:
    from django.conf import settings
    from django.db import connection

    record = load_preview_record()
    session = Path(record["session_dir"])
    db = settings.DATABASES["default"]
    if (settings.TEMPLEDB_RUNTIME_ROLE != "staging"
            or settings.TEMPLEDB_STAGING_ALLOW_OPENAI
            or db["ENGINE"] != "django.db.backends.postgresql"
            or db["HOST"] != str(session / "socket")
            or db["NAME"] != "templedb_preview" or str(db["PORT"]) != "55433"):
        raise RuntimeError("テストDBの接続先が変更されています。")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), inet_server_addr(), current_user")
        if cursor.fetchone() != ("templedb_preview", None, "templedb_preview"):
            raise RuntimeError("専用Unix socketのテストDBではありません。")
        cursor.execute("SHOW data_directory")
        if Path(cursor.fetchone()[0]) != session / "pgdata":
            raise RuntimeError("専用PostgreSQL以外の起動を拒否しました。")
        cursor.execute("SELECT installation_id::text, runtime_kind "
                       "FROM core_databaseruntimeidentity WHERE singleton_key=1")
        if cursor.fetchone() != (record["installation_id"], "product"):
            raise RuntimeError("復元したデータの識別情報が一致しません。")
