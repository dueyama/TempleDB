from __future__ import annotations

import uuid

from django.db import models

from .models_shared import TimestampedModel


class LegacySource(TimestampedModel):
    source_id = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=200, blank=True)
    file_path = models.TextField()
    file_name = models.CharField(max_length=255, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, default="registered")
    notes = models.TextField(blank=True)
    is_primary = models.BooleanField(default=False)
    class Meta:
        ordering = ["source_id"]

    def __str__(self) -> str:
        return self.label or self.source_id


class District(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    short_name = models.CharField(max_length=40, blank=True)
    sort_order = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.short_name or self.name


class DistrictMemberSheetState(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="district_member_sheet_states",
    )
    district = models.ForeignKey(
        "imports.District",
        on_delete=models.CASCADE,
        related_name="member_sheet_states",
    )
    manual_note = models.TextField(blank=True)
    last_printed_member_snapshot = models.JSONField(default=list, blank=True)
    last_printed_prepared_snapshot_id = models.CharField(max_length=255, blank=True)
    last_printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["source__source_id", "district__sort_order", "district__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "district"],
                name="imports_districtmembersheetstate_unique_source_district",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.district}"


class ExportSnapshot(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="export_snapshots",
    )
    snapshot_id = models.CharField(max_length=64)
    export_dir = models.TextField()
    manifest_path = models.TextField()
    log_path = models.TextField(blank=True)
    source_created_at = models.DateTimeField(null=True, blank=True)
    table_count = models.PositiveIntegerField(default=0)
    null_token = models.CharField(max_length=64, default="__MDB_NULL__")
    manifest = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source__source_id", "-source_created_at", "-snapshot_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "snapshot_id"],
                name="imports_exportsnapshot_unique_source_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.snapshot_id}"


class ImportBatch(TimestampedModel):
    class Mode(models.TextChoices):
        REHEARSAL = "rehearsal", "Rehearsal"
        FINAL = "final", "Final"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    batch_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.PROTECT,
        related_name="import_batches",
    )
    export_snapshot = models.ForeignKey(
        "imports.ExportSnapshot",
        on_delete=models.PROTECT,
        related_name="import_batches",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=64, default="households_persons")
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.REHEARSAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    prepared_snapshot_id = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    records_read = models.PositiveIntegerField(default=0)
    households_imported = models.PositiveIntegerField(default=0)
    persons_imported = models.PositiveIntegerField(default=0)
    deceased_profiles_imported = models.PositiveIntegerField(default=0)
    service_schedules_imported = models.PositiveIntegerField(default=0)
    issues_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.prepared_snapshot_id or 'pending'}:{self.batch_uuid}"


class ImportIssue(TimestampedModel):
    class Severity(models.TextChoices):
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.CASCADE,
        related_name="issues",
    )
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    code = models.CharField(max_length=64)
    source_table = models.CharField(max_length=128, blank=True)
    source_row_number = models.PositiveIntegerField(null=True, blank=True)
    legacy_pk_text = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["batch", "created_at", "id"]

    def __str__(self) -> str:
        return f"{self.batch_id}:{self.severity}:{self.code}"


class SourceOperationLog(TimestampedModel):
    class OperationKind(models.TextChoices):
        OPERATIONAL_SOURCE_BOOTSTRAP = "operational_source_bootstrap", "通常運用 primary 自動補完"
        IMPORT_PIPELINE_STARTED = "import_pipeline_started", "再取込開始"
        IMPORT_PIPELINE_SUCCEEDED = "import_pipeline_succeeded", "再取込完了"
        IMPORT_PIPELINE_FAILED = "import_pipeline_failed", "再取込失敗"

    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="operation_logs",
    )
    target_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.SET_NULL,
        related_name="source_operation_logs",
        null=True,
        blank=True,
    )
    operation_kind = models.CharField(max_length=48, choices=OperationKind.choices)
    before_payload = models.JSONField(default=dict, blank=True)
    after_payload = models.JSONField(default=dict, blank=True)
    editor_label = models.CharField(max_length=100, blank=True)
    change_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["operation_kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_id}:{self.operation_kind}:{self.created_at:%Y-%m-%d %H:%M}"


__all__ = [
    "District",
    "DistrictMemberSheetState",
    "ExportSnapshot",
    "ImportBatch",
    "ImportIssue",
    "LegacySource",
    "SourceOperationLog",
]
