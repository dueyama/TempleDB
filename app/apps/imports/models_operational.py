from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from . import model_operational_sync
from .models_shared import SoftDeleteMixin, TimestampedModel


class ImportedOperationalMixin(TimestampedModel):
    related_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_records",
        null=True,
        blank=True,
    )
    household = models.ForeignKey(
        "imports.Household",
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_household_records",
        null=True,
        blank=True,
    )
    person = models.ForeignKey(
        "imports.Person",
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_person_records",
        null=True,
        blank=True,
    )
    legacy_source_id = models.CharField(max_length=100, blank=True)
    household_uid = models.CharField(max_length=255, blank=True)
    person_uid = models.CharField(max_length=255, blank=True)
    household_name_snapshot = models.CharField(max_length=255, blank=True)
    person_name_snapshot = models.CharField(max_length=255, blank=True)
    is_demo_data = models.BooleanField(default=True)

    class Meta:
        abstract = True

    @property
    def legacy_household_id(self) -> str:
        """Compatibility alias for the former operational ORM field name."""

        return self.household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str | None) -> None:
        self.household_uid = str(value or "")

    @property
    def legacy_person_id(self) -> str:
        """Compatibility alias for the former operational ORM field name."""

        return self.person_uid

    @legacy_person_id.setter
    def legacy_person_id(self, value: str | None) -> None:
        self.person_uid = str(value or "")

    def clean(self) -> None:
        super().clean()
        if self.person_id and self.household_id and self.person.household_id != self.household_id:
            raise ValidationError({"person": "Selected person must belong to the selected household."})

    def _sync_import_references(self) -> None:
        model_operational_sync.sync_imported_operational_references(self)

    def save(self, *args, **kwargs):  # type: ignore[override]
        return model_operational_sync.save_imported_operational_record(
            self,
            ImportedOperationalMixin,
            *args,
            **kwargs,
        )


class ServiceSchedule(SoftDeleteMixin, ImportedOperationalMixin):
    class EventScope(models.TextChoices):
        HOUSEHOLD = "household", "家の予定"
        TEMPLE = "temple", "寺の予定"

    class Origin(models.TextChoices):
        IMPORTED = "imported", "取込"
        MANUAL = "manual", "手入力"

    class Category(models.TextChoices):
        MEMORIAL = "memorial", "年忌"
        CHUIN = "chuin", "中陰"
        HATSUBON = "hatsubon", "初盆"
        FUNERAL = "funeral", "葬儀"
        BON = "bon", "盆"
        OTOKOSHI = "otokoshi", "お取越し"
        VISIT = "visit", "訪問"
        OTHER = "other", "その他"

    class Status(models.TextChoices):
        CANDIDATE = "candidate", "候補"
        SCHEDULED = "scheduled", "予定済み"
        COMPLETED = "completed", "完了"
        CANCELLED = "cancelled", "中止"
        DEFERRED = "deferred", "見送り"

    record_origin = models.CharField(max_length=16, choices=Origin.choices, default=Origin.MANUAL)
    event_scope = models.CharField(max_length=16, choices=EventScope.choices, default=EventScope.HOUSEHOLD, db_index=True)
    source_export_batch = models.CharField(max_length=64, blank=True)
    source_table = models.CharField(max_length=128, blank=True)
    source_row_number = models.PositiveIntegerField(null=True, blank=True)
    legacy_pk_text = models.CharField(max_length=255, blank=True)
    schedule_uid = models.CharField(max_length=255, blank=True)
    legacy_schedule_type_id = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.MEMORIAL)
    service_label = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255, blank=True)
    link_group_key = models.CharField(max_length=32, blank=True, db_index=True)
    target_date = models.DateField(null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CANDIDATE)
    notes = models.TextField(blank=True)
    external_calendar_ref = models.CharField(max_length=255, blank=True)
    raw_record = models.JSONField(default=dict, blank=True)

    @property
    def legacy_schedule_id(self) -> str:
        return self.schedule_uid

    @legacy_schedule_id.setter
    def legacy_schedule_id(self, value: str | None) -> None:
        self.schedule_uid = str(value or "")

    class Meta:
        ordering = ["scheduled_date", "target_date", "id"]
        indexes = [
            models.Index(fields=["status", "scheduled_date"]),
            models.Index(fields=["target_date"]),
            models.Index(
                fields=["household_uid"],
                name="imports_ser_legacy__babdc7_idx",
            ),
            models.Index(fields=["record_origin", "source_table"]),
            models.Index(fields=["is_demo_data"]),
        ]

    def save(self, *args, **kwargs):  # type: ignore[override]
        return model_operational_sync.save_service_schedule(self, ServiceSchedule, *args, **kwargs)

    def __str__(self) -> str:
        subject = self.subject_name or self.person_name_snapshot
        household = self.household_name_snapshot or self.household_uid
        if subject:
            return f"{household}:{self.service_label}:{subject}"
        return f"{household}:{self.service_label}"


class GoogleCalendarSyncBinding(TimestampedModel):
    class SyncStatus(models.TextChoices):
        PENDING = "pending", "未同期"
        SYNCED = "synced", "同期済み"
        ERROR = "error", "エラー"
        CONFLICT = "conflict", "競合"

    calendar_id = models.CharField(max_length=255, blank=True)
    sync_key = models.CharField(max_length=255, unique=True)
    primary_schedule = models.ForeignKey(
        "imports.ServiceSchedule",
        on_delete=models.SET_NULL,
        related_name="google_calendar_sync_bindings",
        null=True,
        blank=True,
    )
    google_event_id = models.CharField(max_length=255, blank=True)
    google_etag = models.CharField(max_length=255, blank=True)
    pending_event_deletions = models.JSONField(default=list, blank=True)
    last_pushed_fingerprint = models.CharField(max_length=64, blank=True)
    sync_status = models.CharField(
        max_length=16,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["sync_key"]
        indexes = [
            models.Index(fields=["sync_status", "last_synced_at"]),
            models.Index(fields=["calendar_id"]),
        ]

    def __str__(self) -> str:
        return self.sync_key


class VisitNote(ImportedOperationalMixin):
    class SyncState(models.TextChoices):
        LOCAL_ONLY = "local_only", "ローカルのみ"
        READY = "ready", "同期待ち"
        SYNCED = "synced", "同期済み"

    service_schedule = models.ForeignKey(
        "imports.ServiceSchedule",
        on_delete=models.SET_NULL,
        related_name="visit_notes",
        null=True,
        blank=True,
    )
    visited_on = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    next_action = models.TextField(blank=True)
    author_label = models.CharField(max_length=100, blank=True)
    sync_state = models.CharField(
        max_length=16,
        choices=SyncState.choices,
        default=SyncState.LOCAL_ONLY,
    )
    pinned_for_household = models.BooleanField(default=False)

    class Meta:
        ordering = ["-visited_on", "-created_at"]
        indexes = [
            models.Index(fields=["visited_on"]),
            models.Index(
                fields=["household_uid"],
                name="imports_vis_legacy__ed7ac3_idx",
            ),
            models.Index(fields=["sync_state"]),
            models.Index(fields=["is_demo_data"]),
        ]

    def __str__(self) -> str:
        household = self.household_name_snapshot or self.household_uid
        return self.title or f"{household}:{self.visited_on}"


class OfferingPayment(ImportedOperationalMixin):
    class Category(models.TextChoices):
        OFFERING = "offering", "お布施"
        EITAIKYO = "eitaikyo", "永代経"
        OZENRYO = "ozenryo", "お膳料"
        KURUMADAI = "kurumadai", "お車代"
        HANADAI = "hanadai", "お花代"
        NOKOTSUDAN = "nokotsudan", "納骨壇"
        OTHER = "other", "その他"

    class Method(models.TextChoices):
        CASH = "cash", "現金"
        BANK_TRANSFER = "bank_transfer", "振込"
        OTHER = "other", "その他"

    service_schedule = models.ForeignKey(
        "imports.ServiceSchedule",
        on_delete=models.SET_NULL,
        related_name="offering_payments",
        null=True,
        blank=True,
    )
    received_on = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    payment_category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OFFERING,
    )
    payment_method = models.CharField(
        max_length=32,
        choices=Method.choices,
        default=Method.CASH,
    )
    received_by = models.CharField(max_length=100, blank=True)
    payer_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    exported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_on", "-created_at"]
        indexes = [
            models.Index(fields=["received_on"]),
            models.Index(
                fields=["household_uid"],
                name="imports_off_legacy__fdfc48_idx",
            ),
            models.Index(fields=["payment_category"]),
            models.Index(fields=["is_demo_data"]),
        ]

    def __str__(self) -> str:
        household = self.household_name_snapshot or self.household_uid
        return f"{household}:{self.amount}"

    def _sync_import_references(self) -> None:
        model_operational_sync.sync_offering_payment_references(self)


class AnnualMembershipFeeSetting(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="annual_membership_fee_settings",
    )
    year = models.PositiveIntegerField()
    default_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["source__source_id", "-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "year"],
                name="imports_annualmembershipfeesetting_unique_source_year",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.year}"


class AnnualMembershipFeePayment(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="annual_membership_fee_payments",
    )
    household_uid = models.CharField(max_length=255)
    household_name_snapshot = models.CharField(max_length=255, blank=True)
    delivery_method_snapshot = models.CharField(max_length=16, blank=True)
    district_name_snapshot = models.CharField(max_length=100, blank=True)
    year = models.PositiveIntegerField()
    received_on = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    is_exception = models.BooleanField(default=False)
    received_by = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["source__source_id", "-year", "household_uid"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "household_uid", "year"],
                name="imports_annualmembershipfeepayment_unique_source_household_year",
            )
        ]
        indexes = [
            models.Index(fields=["source", "year"]),
            models.Index(
                fields=["household_uid", "year"],
                name="imports_ann_legacy__cd19fd_idx",
            ),
            models.Index(fields=["delivery_method_snapshot"]),
            models.Index(fields=["district_name_snapshot"]),
        ]

    @property
    def legacy_household_id(self) -> str:
        return self.household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str | None) -> None:
        self.household_uid = str(value or "")

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.year}:{self.household_uid}:{self.amount}"


class AnnualMembershipFeeCheckSheetScan(TimestampedModel):
    class Status(models.TextChoices):
        REVIEW = "review", "確認中"
        CONFIRMED = "confirmed", "受領反映済み"

    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="annual_membership_fee_check_sheet_scans",
    )
    year = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REVIEW)
    file_storage_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100)
    threshold = models.FloatField(default=0.06)
    image_width = models.PositiveIntegerField(default=0)
    image_height = models.PositiveIntegerField(default=0)
    alignment_source = models.CharField(max_length=32, blank=True)
    detected_marker_count = models.PositiveSmallIntegerField(default=0)
    result_payload = models.JSONField(default=dict, blank=True)
    uploaded_by = models.CharField(max_length=100, blank=True)
    confirmed_payload = models.JSONField(default=dict, blank=True)
    confirmed_by = models.CharField(max_length=100, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["source__source_id", "-year", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "year", "file_sha256"],
                name="imports_ann_check_unique_source_year_sha",
            )
        ]
        indexes = [
            models.Index(
                fields=["source", "year", "status"],
                name="imports_ann_check_s_63f27d_idx",
            ),
            models.Index(
                fields=["file_sha256"],
                name="imports_ann_check_h_b5a25c_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.year}:{self.status}:{self.original_filename}"


class AnnualMembershipFeePostalScan(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "未処理"
        NEEDS_REVIEW = "needs_review", "確認待ち"
        CHECKED = "checked", "処理済み"
        MOVE_ERROR = "move_error", "移動失敗"

    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="annual_membership_fee_postal_scans",
    )
    year = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    pdf_storage_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    pdf_sha256 = models.CharField(max_length=64)
    pdf_size_bytes = models.PositiveBigIntegerField(default=0)
    page_number = models.PositiveIntegerField(default=1)
    page_count = models.PositiveIntegerField(default=1)
    statement_date = models.DateField(null=True, blank=True)
    page_image_storage_key = models.CharField(max_length=500, blank=True)
    page_image_sha256 = models.CharField(max_length=64, blank=True)
    crop_storage_key = models.CharField(max_length=500, blank=True)
    crop_sha256 = models.CharField(max_length=64, blank=True)
    crop_box = models.JSONField(default=dict, blank=True)
    recognized_text = models.TextField(blank=True)
    candidate_payload = models.JSONField(default=dict, blank=True)
    selected_household_uid = models.CharField(
        "selected legacy household id",
        max_length=255,
        blank=True,
    )
    selected_household_name_snapshot = models.CharField(max_length=255, blank=True)
    payment = models.ForeignKey(
        "imports.AnnualMembershipFeePayment",
        on_delete=models.SET_NULL,
        related_name="postal_scans",
        null=True,
        blank=True,
    )
    confirmed_by = models.CharField(max_length=100, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    move_error = models.TextField(blank=True)

    class Meta:
        ordering = ["source__source_id", "-year", "status", "original_filename", "page_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "year", "pdf_sha256", "page_number"],
                name="imports_annualmembershipfeepostalscan_unique_source_year_pdf_page",
            )
        ]
        indexes = [
            models.Index(fields=["source", "year", "status"]),
            models.Index(fields=["pdf_sha256", "page_number"]),
            models.Index(
                fields=["selected_household_uid", "year"],
                name="imports_ann_selecte_b430f3_idx",
            ),
            models.Index(fields=["payment"]),
        ]

    @property
    def selected_legacy_household_id(self) -> str:
        """Compatibility alias for callers using the former instance attribute."""

        return self.selected_household_uid

    @selected_legacy_household_id.setter
    def selected_legacy_household_id(self, value: str | None) -> None:
        self.selected_household_uid = str(value or "")

    def __str__(self) -> str:
        return (
            f"{self.source.source_id}:{self.year}:{self.status}:"
            f"{self.original_filename}:p{self.page_number}"
        )


class MemoTag(TimestampedModel):
    class Origin(models.TextChoices):
        SEED = "seed", "初期"
        AI = "ai", "AI"
        MANUAL = "manual", "手動"

    slug = models.SlugField(max_length=64, unique=True, allow_unicode=True)
    label = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    origin = models.CharField(max_length=16, choices=Origin.choices, default=Origin.SEED)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class MemoTagAssignment(TimestampedModel):
    class SourceKind(models.TextChoices):
        RULE = "rule", "キーワード"
        AI = "ai", "AI"
        MANUAL = "manual", "手動"

    tag = models.ForeignKey(
        "imports.MemoTag",
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="imports_memo_tag_assignments",
    )
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    field_name = models.CharField(max_length=64)
    note_type = models.CharField(max_length=64)
    note_label = models.CharField(max_length=100)
    legacy_source_id = models.CharField(max_length=100, blank=True)
    legacy_household_id = models.CharField(max_length=255, blank=True)
    legacy_person_id = models.CharField(max_length=255, blank=True)
    legacy_schedule_id = models.CharField(max_length=255, blank=True)
    source_kind = models.CharField(max_length=16, choices=SourceKind.choices, default=SourceKind.RULE)
    confidence = models.FloatField(null=True, blank=True)
    note_checksum = models.CharField(max_length=64, blank=True)
    note_excerpt = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["tag__label", "note_type", "content_type_id", "object_id", "field_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tag", "content_type", "object_id", "field_name"],
                name="imports_memotagassignment_unique_tag_target_field",
            )
        ]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["note_type", "field_name"]),
            models.Index(fields=["legacy_household_id"]),
            models.Index(fields=["legacy_person_id"]),
            models.Index(fields=["legacy_schedule_id"]),
            models.Index(fields=["tag", "source_kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.tag.label}:{self.note_label}:{self.object_id}"


class RecordEditLog(TimestampedModel):
    class RecordType(models.TextChoices):
        HOUSEHOLD = "household", "戸主"
        PERSON = "person", "家族"
        SERVICE_SCHEDULE = "service_schedule", "予定"
        OFFERING_PAYMENT = "offering_payment", "入金"
        ANNUAL_MEMBERSHIP_FEE_PAYMENT = "annual_membership_fee_payment", "護持会費"
        ANNUAL_MEMBERSHIP_FEE_SETTING = "annual_membership_fee_setting", "護持会費設定"
        DISTRICT = "district", "地区"
        DISTRICT_MEMBER_SHEET = "district_member_sheet", "地区メンバー表"

    class ActionKind(models.TextChoices):
        UPDATE = "update", "更新"
        DELETE = "delete", "削除"
        RESTORE = "restore", "復元"
        RESET_SCHEDULE = "reset_schedule", "予定リセット"
        LINK_UPDATE = "link_update", "法要リンク調整"

    record_type = models.CharField(max_length=32, choices=RecordType.choices)
    action_kind = models.CharField(
        max_length=32,
        choices=ActionKind.choices,
        default=ActionKind.UPDATE,
    )
    record_id = models.PositiveBigIntegerField()
    legacy_source_id = models.CharField(max_length=100, blank=True)
    legacy_household_id = models.CharField(max_length=255, blank=True)
    legacy_person_id = models.CharField(max_length=255, blank=True)
    legacy_schedule_id = models.CharField(max_length=255, blank=True)
    record_label = models.CharField(max_length=255, blank=True)
    changed_fields = models.JSONField(default=list, blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    editor_label = models.CharField(max_length=100, blank=True)
    change_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["record_type", "record_id"]),
            models.Index(fields=["action_kind"]),
            models.Index(fields=["legacy_household_id"]),
            models.Index(fields=["legacy_person_id"]),
            models.Index(fields=["legacy_schedule_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.record_type}:{self.record_id}:{self.created_at:%Y-%m-%d %H:%M}"


class RecordFieldChange(models.Model):
    record_edit_log = models.ForeignKey(
        "imports.RecordEditLog",
        on_delete=models.CASCADE,
        related_name="field_changes",
    )
    field_path = models.CharField(max_length=255)
    before_value = models.JSONField(default=None, null=True, blank=True)
    after_value = models.JSONField(default=None, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["record_edit_log_id", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["record_edit_log", "field_path"],
                name="imports_recordfieldchange_unique_log_path",
            )
        ]
        indexes = [
            models.Index(fields=["record_edit_log", "sort_order"]),
            models.Index(fields=["field_path"]),
        ]

    def __str__(self) -> str:
        return f"{self.record_edit_log_id}:{self.field_path}"


__all__ = [
    "AnnualMembershipFeeCheckSheetScan",
    "AnnualMembershipFeePayment",
    "AnnualMembershipFeePostalScan",
    "AnnualMembershipFeeSetting",
    "GoogleCalendarSyncBinding",
    "ImportedOperationalMixin",
    "MemoTag",
    "MemoTagAssignment",
    "OfferingPayment",
    "RecordEditLog",
    "RecordFieldChange",
    "ServiceSchedule",
    "VisitNote",
]
