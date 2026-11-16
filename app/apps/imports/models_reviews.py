from __future__ import annotations

from django.db import models

from .models_shared import TimestampedModel


class PostalReviewResolution(TimestampedModel):
    class ResolutionKind(models.TextChoices):
        REPLACE_HEAD = "replace_head", "戸主差し替え"
        MAILING_OVERRIDE = "mailing_override", "別郵送先設定"
        CREATE_HOUSEHOLD = "create_household", "新しい家を作成"

    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="postal_review_resolutions",
    )
    folder_name = models.CharField(max_length=255, blank=True)
    row_number = models.PositiveIntegerField()
    resolution_kind = models.CharField(max_length=32, choices=ResolutionKind.choices)
    selected_household_uid = models.CharField(max_length=255, blank=True)
    entry_head_name = models.CharField(max_length=255, blank=True)
    target_household_name_snapshot = models.CharField(max_length=255, blank=True)
    editor_label = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["source__source_id", "folder_name", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "folder_name", "row_number"],
                name="imports_postalreviewresolution_unique_row",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.folder_name}:{self.row_number}"

    @property
    def legacy_household_id(self) -> str:
        """Compatibility alias for callers that still use the old instance attribute."""

        return self.selected_household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str) -> None:
        self.selected_household_uid = value


class HandDeliveryReviewResolution(TimestampedModel):
    class ResolutionKind(models.TextChoices):
        REPLACE_HEAD = "replace_head", "戸主差し替え"
        CREATE_HOUSEHOLD = "create_household", "新しい家を作成"

    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="hand_delivery_review_resolutions",
    )
    folder_name = models.CharField(max_length=255, blank=True)
    row_number = models.PositiveIntegerField()
    resolution_kind = models.CharField(max_length=32, choices=ResolutionKind.choices)
    selected_household_uid = models.CharField(max_length=255, blank=True)
    entry_head_name = models.CharField(max_length=255, blank=True)
    target_household_name_snapshot = models.CharField(max_length=255, blank=True)
    editor_label = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["source__source_id", "folder_name", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "folder_name", "row_number"],
                name="imports_handdeliveryreviewresolution_unique_row",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.folder_name}:{self.row_number}"

    @property
    def legacy_household_id(self) -> str:
        """Compatibility alias for callers that still use the old instance attribute."""

        return self.selected_household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str) -> None:
        self.selected_household_uid = value


class MemorialNoticeTemplate(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="memorial_notice_templates",
    )
    target_year = models.PositiveIntegerField()
    intro_text = models.TextField(blank=True)
    outro_text = models.TextField(blank=True)
    signature_text = models.TextField(blank=True)
    recipient_font_size = models.FloatField(null=True, blank=True)
    body_font_size = models.FloatField(null=True, blank=True)
    signature_font_size = models.FloatField(null=True, blank=True)
    table_font_size = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["source__source_id", "-target_year"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target_year"],
                name="imports_memorialnoticetemplate_unique_source_year",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source.source_id}:{self.target_year}"


__all__ = [
    "HandDeliveryReviewResolution",
    "MemorialNoticeTemplate",
    "PostalReviewResolution",
]
