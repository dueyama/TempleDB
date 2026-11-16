from __future__ import annotations

import uuid

from django.db import models

DATABASE_BACKUP_TRIGGER_CHOICES = (
    ("manual", "手動"),
    ("scheduled", "日次自動"),
)
DATABASE_BACKUP_VERIFICATION_TRIGGER_CHOICES = (
    ("manual", "手動"),
    ("scheduled", "週次自動"),
)
DATABASE_BACKUP_STATUS_CHOICES = (
    ("running", "実行中"),
    ("succeeded", "成功"),
    ("failed", "失敗"),
)
DATABASE_BACKUP_ENGINE_CHOICES = (
    ("postgresql", "PostgreSQL"),
    ("sqlite", "SQLite"),
)
DATABASE_BACKUP_SCHEDULE_ENGINE_CHOICES = (
    ("", "未実行"),
    *DATABASE_BACKUP_ENGINE_CHOICES,
)
DEFAULT_TEMPLE_NAME = ""
DEFAULT_TEMPLE_PHONE = ""
DEFAULT_TEMPLE_SECT = ""
DEFAULT_TEMPLE_ADDRESS = ""
DEFAULT_TEMPLE_POSTAL_CODE = ""
DEFAULT_TEMPLE_CHIEF_PRIEST_NAME = ""
DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE = (
    "無量寿経",
    "観無量寿経",
    "阿弥陀経",
)
DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT = "\n".join(DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE)
DATABASE_RUNTIME_KIND_CHOICES = (
    ("product", "製品"),
    ("demo", "デモ"),
)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DatabaseRuntimeIdentity(TimestampedModel):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    installation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    runtime_kind = models.CharField(
        max_length=16,
        choices=DATABASE_RUNTIME_KIND_CHOICES,
        default="product",
    )

    class Meta:
        ordering = ["singleton_key"]

    def __str__(self) -> str:
        return f"{self.runtime_kind}:{self.installation_id}"


class DatabaseBackupSetting(TimestampedModel):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    destination_path = models.TextField(blank=True)
    retention_count = models.PositiveIntegerField(default=30)
    daily_enabled = models.BooleanField(default=True)
    weekly_verification_enabled = models.BooleanField(default=True)
    last_scheduled_attempt_on = models.DateField(null=True, blank=True)
    last_scheduled_attempt_engine = models.CharField(
        max_length=16,
        choices=DATABASE_BACKUP_SCHEDULE_ENGINE_CHOICES,
        blank=True,
        default="",
    )
    last_status = models.CharField(
        max_length=16,
        choices=DATABASE_BACKUP_STATUS_CHOICES,
        blank=True,
    )
    last_status_message = models.TextField(blank=True)
    last_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["singleton_key"]

    def __str__(self) -> str:
        return "database-backup-setting"


class TempleIdentitySetting(TimestampedModel):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    temple_sect = models.CharField(max_length=255, default=DEFAULT_TEMPLE_SECT, blank=True)
    temple_name = models.CharField(max_length=255, default=DEFAULT_TEMPLE_NAME, blank=True)
    temple_postal_code = models.CharField(max_length=32, default=DEFAULT_TEMPLE_POSTAL_CODE, blank=True)
    temple_address = models.CharField(max_length=255, default=DEFAULT_TEMPLE_ADDRESS, blank=True)
    temple_phone = models.CharField(max_length=255, default=DEFAULT_TEMPLE_PHONE, blank=True)
    chief_priest_name = models.CharField(
        max_length=255,
        default=DEFAULT_TEMPLE_CHIEF_PRIEST_NAME,
        blank=True,
    )
    service_schedule_sutra_cycle = models.TextField(
        default=DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT,
        blank=True,
    )

    class Meta:
        ordering = ["singleton_key"]

    def __str__(self) -> str:
        return "temple-identity-setting"


class GoogleCalendarSyncSetting(TimestampedModel):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    enabled = models.BooleanField(default=False)
    calendar_id = models.CharField(max_length=255, blank=True)
    base_url = models.CharField(max_length=500, blank=True)
    external_base_url = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["singleton_key"]

    def __str__(self) -> str:
        return "google-calendar-sync-setting"


class DatabaseBackupRun(TimestampedModel):
    setting = models.ForeignKey(
        DatabaseBackupSetting,
        on_delete=models.SET_NULL,
        related_name="runs",
        null=True,
        blank=True,
    )
    database_engine = models.CharField(
        max_length=16,
        choices=DATABASE_BACKUP_ENGINE_CHOICES,
        db_index=True,
    )
    trigger_kind = models.CharField(max_length=16, choices=DATABASE_BACKUP_TRIGGER_CHOICES)
    status = models.CharField(max_length=16, choices=DATABASE_BACKUP_STATUS_CHOICES)
    requested_by_label = models.CharField(max_length=100, blank=True)
    database_name = models.CharField(max_length=255, blank=True)
    database_host = models.CharField(max_length=255, blank=True)
    destination_path = models.TextField(blank=True)
    backup_file_name = models.CharField(max_length=255, blank=True)
    backup_file_path = models.TextField(blank=True)
    manifest_file_path = models.TextField(blank=True)
    backup_file_size = models.BigIntegerField(null=True, blank=True)
    backup_sha256 = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["trigger_kind", "started_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(database_engine__in=("postgresql", "sqlite")),
                name="core_backup_run_engine_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trigger_kind}:{self.status}:{self.started_at:%Y-%m-%d %H:%M}"


class DatabaseBackupVerificationRun(TimestampedModel):
    backup_run = models.ForeignKey(
        DatabaseBackupRun,
        on_delete=models.CASCADE,
        related_name="verification_runs",
    )
    trigger_kind = models.CharField(
        max_length=16,
        choices=DATABASE_BACKUP_VERIFICATION_TRIGGER_CHOICES,
        default="manual",
    )
    status = models.CharField(max_length=16, choices=DATABASE_BACKUP_STATUS_CHOICES)
    requested_by_label = models.CharField(max_length=100, blank=True)
    verification_database_name = models.CharField(max_length=255, blank=True)
    verification_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["backup_run", "started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.backup_run_id}:{self.status}:{self.started_at:%Y-%m-%d %H:%M}"
