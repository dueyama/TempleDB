"""Validate and prepare only the explicitly owned, disposable preview database."""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import DatabaseBackupSetting, GoogleCalendarSyncSetting
from apps.core.services import backup
from apps.core.services import database_transfer_postgresql as transfer
from config.realdata_preview_guard import load_preview_record, verify_live_database


class Command(BaseCommand):
    help = "使い捨てMac検証DBを確認し、試験用ログインを準備します。"

    def handle(self, *args, **options):
        record = load_preview_record()
        verify_live_database()
        session = Path(record["session_dir"])
        config = backup.PostgresConnectionConfig(
            database_name="templedb_preview", database_user="templedb_preview",
            database_password="", database_host=str(session / "socket"), database_port="55433",
        )
        if transfer._read_unvalidated_constraints(config, config.database_name):
            raise RuntimeError("復元DBに未検証の制約があります。")
        if transfer._count_broken_postgresql_generic_relations(config, config.database_name):
            raise RuntimeError("復元DBの関連データに不整合があります。")
        sequences = transfer._validate_postgresql_sequences(config, config.database_name)
        login = json.loads((session / "login.json").read_text())
        with transaction.atomic():
            # The copied legacy mirror contains Pi paths. Rebind only the copy to
            # its own registry; this does not change the preserved source files.
            call_command("normalize_legacy_source_paths", execute=True,
                         skip_checks=True, stdout=StringIO())
            DatabaseBackupSetting.objects.update(
                daily_enabled=False, weekly_verification_enabled=False,
                destination_path=str(session / "tenant/backups"),
            )
            GoogleCalendarSyncSetting.objects.update(
                enabled=False, base_url="http://127.0.0.1:8010", external_base_url="",
            )
            # Never change a copied person's existing account or password.
            user_model = get_user_model()
            if user_model.objects.filter(username=login["username"]).exists():
                raise RuntimeError("試験用のユーザー名が既存アカウントと重複しています。")
            user_model.objects.create_superuser(
                username=login["username"], password=login["password"], email="",
            )
        self.stdout.write(json.dumps({"preview_ready": True, "sequence_checks": len(sequences)}))
