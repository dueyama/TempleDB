from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from config.runtime_paths import sqlite_db_path


@dataclass
class SqliteAdminRow:
    username: str
    password: str
    is_staff: bool
    is_superuser: bool
    is_active: bool
    email: str
    first_name: str
    last_name: str
    last_login: object | None
    date_joined: object | None


class Command(BaseCommand):
    help = "Copy the legacy SQLite admin user into the current database if missing."

    def handle(self, *args, **options) -> None:
        User = get_user_model()
        existing = User.objects.filter(username="admin").first()
        if existing is not None:
            self.stdout.write(self.style.WARNING("admin already exists in the current database."))
            return

        source_admin = self._load_sqlite_admin()
        if source_admin is None:
            self.stdout.write(self.style.WARNING("SQLite admin user was not found."))
            return

        with transaction.atomic():
            user = User(
                username=source_admin.username,
                password=source_admin.password,
                is_staff=source_admin.is_staff,
                is_superuser=source_admin.is_superuser,
                is_active=source_admin.is_active,
                email=source_admin.email,
                first_name=source_admin.first_name,
                last_name=source_admin.last_name,
            )
            if source_admin.last_login is not None:
                user.last_login = source_admin.last_login
            if source_admin.date_joined is not None:
                user.date_joined = source_admin.date_joined
            user.save(force_insert=True)

        self.stdout.write(self.style.SUCCESS("Copied admin user from SQLite into the current database."))

    def _load_sqlite_admin(self) -> SqliteAdminRow | None:
        path = sqlite_db_path()
        if not path.exists():
            return None

        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                """
                SELECT
                    username,
                    password,
                    is_staff,
                    is_superuser,
                    is_active,
                    COALESCE(email, ''),
                    COALESCE(first_name, ''),
                    COALESCE(last_name, ''),
                    last_login,
                    date_joined
                FROM auth_user
                WHERE username = 'admin'
                LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return None

        return SqliteAdminRow(
            username=str(row[0]),
            password=str(row[1]),
            is_staff=bool(row[2]),
            is_superuser=bool(row[3]),
            is_active=bool(row[4]),
            email=str(row[5] or ""),
            first_name=str(row[6] or ""),
            last_name=str(row[7] or ""),
            last_login=self._normalize_datetime(row[8]),
            date_joined=self._normalize_datetime(row[9]),
        )

    def _normalize_datetime(self, raw_value: object) -> object | None:
        if not raw_value:
            return None
        parsed = parse_datetime(str(raw_value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
