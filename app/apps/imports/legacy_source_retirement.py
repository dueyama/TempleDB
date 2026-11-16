from __future__ import annotations

import hashlib
import json

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Model, Q, QuerySet

from config import source_registry

from . import source_runtime
from .import_batch_retirement_audit import audit_batch_retirement
from .models import (
    AnnualMembershipFeeCheckSheetScan,
    AnnualMembershipFeePayment,
    AnnualMembershipFeePostalScan,
    AnnualMembershipFeeSetting,
    DeceasedProfile,
    DistrictMemberSheetState,
    ExportSnapshot,
    GoogleCalendarSyncBinding,
    HandDeliveryReviewResolution,
    Household,
    HouseholdProfile,
    ImportBatch,
    ImportIssue,
    LegacySource,
    MemorialNoticeTemplate,
    MemoTag,
    MemoTagAssignment,
    OfferingPayment,
    Person,
    PostalReviewResolution,
    RecordEditLog,
    RecordFieldChange,
    ServiceSchedule,
    SourceOperationLog,
    VisitNote,
)

SCHEMA_VERSION = 2
TERMINAL_BATCH_STATUSES = {
    ImportBatch.Status.SUCCEEDED,
    ImportBatch.Status.FAILED,
}
ALLOWED_PRE_CLEANUP_BATCH_BLOCKERS = {
    "LATEST_BATCH_SOFT_IDENTITY_REFERENCE",
    "MEMO_TAG_ASSIGNMENT_REFERENCE",
}

EXPECTED_SOURCE_RELATIONS = {
    "imports.AnnualMembershipFeeCheckSheetScan.source",
    "imports.AnnualMembershipFeePayment.source",
    "imports.AnnualMembershipFeePostalScan.source",
    "imports.AnnualMembershipFeeSetting.source",
    "imports.DistrictMemberSheetState.source",
    "imports.ExportSnapshot.source",
    "imports.HandDeliveryReviewResolution.source",
    "imports.HouseholdProfile.source",
    "imports.ImportBatch.source",
    "imports.MemorialNoticeTemplate.source",
    "imports.PostalReviewResolution.source",
    "imports.SourceOperationLog.source",
}
EXPECTED_BATCH_RELATIONS = {
    "imports.Household.batch",
    "imports.ImportIssue.batch",
    "imports.OfferingPayment.related_batch",
    "imports.Person.batch",
    "imports.ServiceSchedule.related_batch",
    "imports.SourceOperationLog.target_batch",
    "imports.VisitNote.related_batch",
}
EXPECTED_LEGACY_SOURCE_ID_MODELS = {
    "imports.Household",
    "imports.MemoTagAssignment",
    "imports.OfferingPayment",
    "imports.Person",
    "imports.RecordEditLog",
    "imports.ServiceSchedule",
    "imports.VisitNote",
}

BLOCKED_SOURCE_MODELS = {
    "annual_membership_fee_check_sheet_scans": AnnualMembershipFeeCheckSheetScan,
    "annual_membership_fee_payments": AnnualMembershipFeePayment,
    "annual_membership_fee_postal_scans": AnnualMembershipFeePostalScan,
    "annual_membership_fee_settings": AnnualMembershipFeeSetting,
    "district_member_sheet_states": DistrictMemberSheetState,
    "hand_delivery_review_resolutions": HandDeliveryReviewResolution,
    "memorial_notice_templates": MemorialNoticeTemplate,
    "postal_review_resolutions": PostalReviewResolution,
}
BLOCKED_SOFT_SOURCE_MODELS = {
    "offering_payments": OfferingPayment,
    "record_edit_logs": RecordEditLog,
    "service_schedules": ServiceSchedule,
    "visit_notes": VisitNote,
}


class LegacySourceRetirementError(RuntimeError):
    pass


def _model_relation_inventory(target_model: type[Model]) -> set[str]:
    inventory: set[str] = set()
    for model in apps.get_models():
        for field in model._meta.fields:
            if field.is_relation and field.remote_field.model is target_model:
                inventory.add(f"{model._meta.label}.{field.name}")
    return inventory


def _legacy_source_id_model_inventory() -> set[str]:
    return {
        model._meta.label
        for model in apps.get_models()
        if any(field.name == "legacy_source_id" for field in model._meta.fields)
    }


def _queryset_fingerprint(queryset: QuerySet) -> dict[str, int | str]:
    model = queryset.model
    field_names = [field.attname for field in model._meta.concrete_fields]
    digest = hashlib.sha256()
    count = 0
    for row in queryset.order_by("pk").values(*field_names).iterator(chunk_size=500):
        encoded = json.dumps(
            row,
            cls=DjangoJSONEncoder,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return {"count": count, "sha256": digest.hexdigest()}


def _registry_state(source_id: str) -> tuple[dict, dict]:
    registry = source_registry.load_source_registry()
    encoded = json.dumps(
        registry,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    matching = [
        entry for entry in registry.get("sources", []) if entry.get("source_id") == source_id
    ]
    public_state = {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "default_source_id": registry.get("default_source_id") or "",
        "target_entry_count": len(matching),
        "target_entry_present": bool(matching),
        "target_entry_status": matching[0].get("status", "") if len(matching) == 1 else "",
    }
    return registry, public_state


def _content_type_map() -> tuple[dict[type[Model], ContentType], list[str]]:
    wanted = {
        (model._meta.app_label, model._meta.model_name): model
        for model in (Household, Person, DeceasedProfile)
    }
    content_types = {
        wanted[(row.app_label, row.model)]: row
        for row in ContentType.objects.filter(
            app_label="imports",
            model__in=[key[1] for key in wanted],
        )
        if (row.app_label, row.model) in wanted
    }
    missing = sorted(model._meta.label for model in wanted.values() if model not in content_types)
    return content_types, missing


def _preserved_memo_object_ids(
    assignment: MemoTagAssignment,
    *,
    current_source_id: str,
    content_types: dict[type[Model], ContentType],
) -> QuerySet:
    if assignment.content_type_id == getattr(content_types.get(Household), "id", None):
        return Household._base_manager.filter(
            legacy_source_id=current_source_id,
            household_uid=assignment.legacy_household_id,
        ).values("pk")
    if assignment.content_type_id == getattr(content_types.get(Person), "id", None):
        return Person._base_manager.filter(
            legacy_source_id=current_source_id,
            household__household_uid=assignment.legacy_household_id,
            person_uid=assignment.legacy_person_id,
        ).values("pk")
    if assignment.content_type_id == getattr(content_types.get(DeceasedProfile), "id", None):
        return DeceasedProfile._base_manager.filter(
            person__legacy_source_id=current_source_id,
            person__household__household_uid=assignment.legacy_household_id,
            person__person_uid=assignment.legacy_person_id,
        ).values("pk")
    return Household._base_manager.none().values("pk")


def _memo_assignment_state(
    source_id: str,
    current_source_id: str,
    households: QuerySet,
    persons: QuerySet,
    deceased_profiles: QuerySet,
) -> tuple[dict[str, int], QuerySet]:
    content_types, missing_content_types = _content_type_map()
    assignments = MemoTagAssignment._base_manager.filter(legacy_source_id=source_id)
    target_query = Q(pk__in=[])
    for model, rows in (
        (Household, households),
        (Person, persons),
        (DeceasedProfile, deceased_profiles),
    ):
        content_type = content_types.get(model)
        if content_type is not None:
            target_query |= Q(
                content_type=content_type,
                object_id__in=rows.values("pk"),
            )
    matching = assignments.filter(target_query)

    all_target_assignments = MemoTagAssignment._base_manager.filter(target_query)
    foreign_or_blank_target_count = all_target_assignments.exclude(
        legacy_source_id=source_id
    ).count()

    without_equivalent = 0
    for assignment in matching.iterator(chunk_size=100):
        equivalent = MemoTagAssignment._base_manager.filter(
            legacy_source_id=current_source_id,
            tag_id=assignment.tag_id,
            content_type_id=assignment.content_type_id,
            object_id__in=_preserved_memo_object_ids(
                assignment,
                current_source_id=current_source_id,
                content_types=content_types,
            ),
            field_name=assignment.field_name,
            note_type=assignment.note_type,
            note_checksum=assignment.note_checksum,
            legacy_household_id=assignment.legacy_household_id,
            legacy_person_id=assignment.legacy_person_id,
            legacy_schedule_id=assignment.legacy_schedule_id,
        )
        if not equivalent.exists():
            without_equivalent += 1

    return (
        {
            "source_assignment_count": assignments.count(),
            "matching_target_count": matching.count(),
            "foreign_or_blank_target_count": foreign_or_blank_target_count,
            "without_preserved_equivalent_count": without_equivalent,
            "missing_content_type_count": len(missing_content_types),
        },
        assignments,
    )


def _preserved_state(source: LegacySource) -> dict[str, dict[str, int | str]]:
    other_batches = ImportBatch._base_manager.exclude(source=source)
    return {
        "legacy_sources": _queryset_fingerprint(LegacySource._base_manager.exclude(pk=source.pk)),
        "export_snapshots": _queryset_fingerprint(
            ExportSnapshot._base_manager.exclude(source=source)
        ),
        "import_batches": _queryset_fingerprint(other_batches),
        "import_issues": _queryset_fingerprint(
            ImportIssue._base_manager.exclude(batch__source=source)
        ),
        "source_operation_logs": _queryset_fingerprint(
            SourceOperationLog._base_manager.exclude(source=source)
        ),
        "households": _queryset_fingerprint(Household._base_manager.exclude(batch__source=source)),
        "persons": _queryset_fingerprint(Person._base_manager.exclude(batch__source=source)),
        "deceased_profiles": _queryset_fingerprint(
            DeceasedProfile._base_manager.exclude(person__batch__source=source)
        ),
        "household_profiles": _queryset_fingerprint(
            HouseholdProfile._base_manager.exclude(source=source)
        ),
        "memo_tags": _queryset_fingerprint(MemoTag._base_manager.all()),
        "memo_tag_assignments": _queryset_fingerprint(
            MemoTagAssignment._base_manager.exclude(legacy_source_id=source.source_id)
        ),
        "record_edit_logs": _queryset_fingerprint(RecordEditLog._base_manager.all()),
        "record_field_changes": _queryset_fingerprint(RecordFieldChange._base_manager.all()),
        "service_schedules": _queryset_fingerprint(ServiceSchedule._base_manager.all()),
        "visit_notes": _queryset_fingerprint(VisitNote._base_manager.all()),
        "offering_payments": _queryset_fingerprint(OfferingPayment._base_manager.all()),
        "google_calendar_bindings": _queryset_fingerprint(
            GoogleCalendarSyncBinding._base_manager.all()
        ),
        "annual_membership_fee_settings": _queryset_fingerprint(
            AnnualMembershipFeeSetting._base_manager.all()
        ),
        "annual_membership_fee_payments": _queryset_fingerprint(
            AnnualMembershipFeePayment._base_manager.all()
        ),
        "annual_membership_fee_check_sheet_scans": _queryset_fingerprint(
            AnnualMembershipFeeCheckSheetScan._base_manager.all()
        ),
        "annual_membership_fee_postal_scans": _queryset_fingerprint(
            AnnualMembershipFeePostalScan._base_manager.all()
        ),
        "district_member_sheet_states": _queryset_fingerprint(
            DistrictMemberSheetState._base_manager.all()
        ),
        "postal_review_resolutions": _queryset_fingerprint(
            PostalReviewResolution._base_manager.all()
        ),
        "hand_delivery_review_resolutions": _queryset_fingerprint(
            HandDeliveryReviewResolution._base_manager.all()
        ),
        "memorial_notice_templates": _queryset_fingerprint(
            MemorialNoticeTemplate._base_manager.all()
        ),
    }


def _build_plan_in_transaction(
    source_id: str,
    *,
    expected_batch_ids: list[int] | None,
    lock: bool,
) -> tuple[dict, dict[str, QuerySet]]:
    source_query = LegacySource._base_manager
    if lock:
        source_query = source_query.select_for_update()
    try:
        source = source_query.get(source_id=source_id)
    except LegacySource.DoesNotExist as exc:
        raise LegacySourceRetirementError(f"LegacySource not found: {source_id}") from exc

    batch_query = ImportBatch._base_manager.filter(source=source).order_by("id")
    if lock:
        batch_query = batch_query.select_for_update()
    batches = list(batch_query)
    batch_ids = [batch.id for batch in batches]

    households = Household._base_manager.filter(batch__source=source)
    persons = Person._base_manager.filter(batch__source=source)
    deceased_profiles = DeceasedProfile._base_manager.filter(person__batch__source=source)
    profiles = HouseholdProfile._base_manager.filter(source=source)
    issues = ImportIssue._base_manager.filter(batch__source=source)
    snapshots = ExportSnapshot._base_manager.filter(source=source)
    operation_logs = SourceOperationLog._base_manager.filter(source=source)
    if lock:
        for queryset in (
            households,
            persons,
            deceased_profiles,
            profiles,
            issues,
            snapshots,
            operation_logs,
        ):
            list(queryset.select_for_update().values_list("pk", flat=True))

    _registry_payload, registry = _registry_state(source_id)
    runtime_source_id = source_runtime.runtime_source_id()
    primary_source_ids = list(
        LegacySource._base_manager.filter(is_primary=True)
        .order_by("source_id")
        .values_list("source_id", flat=True)
    )
    memo_state, memo_assignments = _memo_assignment_state(
        source_id,
        runtime_source_id,
        households,
        persons,
        deceased_profiles,
    )
    if lock:
        list(memo_assignments.select_for_update().values_list("pk", flat=True))

    direct_block_counts = {
        key: model._base_manager.filter(source=source).count()
        for key, model in BLOCKED_SOURCE_MODELS.items()
    }
    soft_block_counts = {
        key: model._base_manager.filter(legacy_source_id=source_id).count()
        for key, model in BLOCKED_SOFT_SOURCE_MODELS.items()
    }
    target_batch_ids = ImportBatch._base_manager.filter(source=source).values("pk")
    canonical_reference_counts = {
        "service_schedules": ServiceSchedule._base_manager.filter(
            Q(related_batch_id__in=target_batch_ids)
            | Q(household__batch__source=source)
            | Q(person__batch__source=source)
        ).count(),
        "visit_notes": VisitNote._base_manager.filter(
            Q(related_batch_id__in=target_batch_ids)
            | Q(household__batch__source=source)
            | Q(person__batch__source=source)
        ).count(),
        "offering_payments": OfferingPayment._base_manager.filter(
            Q(related_batch_id__in=target_batch_ids)
            | Q(household__batch__source=source)
            | Q(person__batch__source=source)
        ).count(),
        "other_source_operation_logs": SourceOperationLog._base_manager.filter(
            target_batch_id__in=target_batch_ids
        )
        .exclude(source=source)
        .count(),
        "source_logs_targeting_other_source": operation_logs.exclude(target_batch__isnull=True)
        .exclude(target_batch__source=source)
        .count(),
        "cross_source_export_snapshots": ImportBatch._base_manager.filter(source=source)
        .exclude(export_snapshot__isnull=True)
        .exclude(export_snapshot__source=source)
        .count(),
        "other_batches_targeting_source_snapshot": ImportBatch._base_manager.exclude(source=source)
        .filter(export_snapshot__source=source)
        .count(),
    }
    google_binding_count = GoogleCalendarSyncBinding._base_manager.filter(
        primary_schedule__in=ServiceSchedule._base_manager.filter(
            Q(legacy_source_id=source_id)
            | Q(related_batch_id__in=target_batch_ids)
            | Q(household__batch__source=source)
            | Q(person__batch__source=source)
        )
    ).count()
    record_field_change_count = RecordFieldChange._base_manager.filter(
        record_edit_log__legacy_source_id=source_id
    ).count()

    content_types, missing_content_types = _content_type_map()
    admin_log_count = 0
    for model, rows in (
        (Household, households),
        (Person, persons),
        (DeceasedProfile, deceased_profiles),
    ):
        content_type = content_types.get(model)
        if content_type is not None:
            admin_log_count += LogEntry.objects.filter(
                content_type=content_type,
                object_id__in=[str(pk) for pk in rows.values_list("pk", flat=True)],
            ).count()

    profile_without_household_count = profiles.exclude(
        household_uid__in=households.values("household_uid")
    ).count()
    profile_without_current_counterpart_count = profiles.exclude(
        household_uid__in=HouseholdProfile._base_manager.filter(
            source__source_id=runtime_source_id
        ).values("household_uid")
    ).count()
    batch_audits = [audit_batch_retirement(batch) for batch in batches]
    unexpected_audit_blockers = {
        f"batch_{audit['batch_id']}": sorted(
            set(audit["blocker_codes"]) - ALLOWED_PRE_CLEANUP_BATCH_BLOCKERS
        )
        for audit in batch_audits
        if set(audit["blocker_codes"]) - ALLOWED_PRE_CLEANUP_BATCH_BLOCKERS
    }

    blockers: list[str] = []
    if source_id == runtime_source_id:
        blockers.append("RUNTIME_SOURCE")
    if primary_source_ids != [runtime_source_id]:
        blockers.append("RUNTIME_PRIMARY_SOURCE_MISMATCH")
    if source.is_primary or source.status == "primary":
        blockers.append("PRIMARY_SOURCE")
    if not batches:
        blockers.append("SOURCE_HAS_NO_BATCHES")
    if any(batch.status not in TERMINAL_BATCH_STATUSES for batch in batches):
        blockers.append("NON_TERMINAL_BATCH")
    if expected_batch_ids is not None and sorted(set(expected_batch_ids)) != batch_ids:
        blockers.append("EXPECTED_BATCH_SET_MISMATCH")
    if registry["default_source_id"] == source_id:
        blockers.append("REGISTRY_DEFAULT_SOURCE")
    if registry["target_entry_count"] > 1:
        blockers.append("REGISTRY_DUPLICATE_SOURCE")
    if registry["target_entry_status"] == "primary":
        blockers.append("REGISTRY_PRIMARY_SOURCE")
    if _model_relation_inventory(LegacySource) != EXPECTED_SOURCE_RELATIONS:
        blockers.append("UNCLASSIFIED_SOURCE_RELATION")
    if _model_relation_inventory(ImportBatch) != EXPECTED_BATCH_RELATIONS:
        blockers.append("UNCLASSIFIED_BATCH_RELATION")
    if _legacy_source_id_model_inventory() != EXPECTED_LEGACY_SOURCE_ID_MODELS:
        blockers.append("UNCLASSIFIED_LEGACY_SOURCE_ID_MODEL")
    if any(direct_block_counts.values()):
        blockers.append("PROTECTED_SOURCE_RECORD")
    if any(soft_block_counts.values()):
        blockers.append("PROTECTED_OPERATIONAL_RECORD")
    if any(canonical_reference_counts.values()):
        blockers.append("EXTERNAL_CANONICAL_OR_BATCH_REFERENCE")
    if google_binding_count:
        blockers.append("GOOGLE_CALENDAR_BINDING")
    if record_field_change_count:
        blockers.append("RECORD_FIELD_CHANGE")
    if admin_log_count:
        blockers.append("DJANGO_ADMIN_LOG")
    if missing_content_types or memo_state["missing_content_type_count"]:
        blockers.append("CONTENT_TYPE_MISSING")
    if profile_without_household_count:
        blockers.append("PROFILE_WITHOUT_TARGET_HOUSEHOLD")
    if profile_without_current_counterpart_count:
        blockers.append("PROFILE_WITHOUT_CURRENT_COUNTERPART")
    if memo_state["source_assignment_count"] != memo_state["matching_target_count"]:
        blockers.append("MEMO_ASSIGNMENT_TARGET_MISMATCH")
    if memo_state["foreign_or_blank_target_count"]:
        blockers.append("FOREIGN_MEMO_ASSIGNMENT_TO_TARGET")
    if memo_state["without_preserved_equivalent_count"]:
        blockers.append("MEMO_ASSIGNMENT_WITHOUT_PRESERVED_EQUIVALENT")
    if unexpected_audit_blockers:
        blockers.append("BATCH_RETIREMENT_AUDIT_BLOCKER")

    delete_querysets = {
        "legacy_sources": LegacySource._base_manager.filter(pk=source.pk),
        "export_snapshots": snapshots,
        "import_batches": ImportBatch._base_manager.filter(source=source),
        "import_issues": issues,
        "source_operation_logs": operation_logs,
        "households": households,
        "persons": persons,
        "deceased_profiles": deceased_profiles,
        "household_profiles": profiles,
        "memo_tag_assignments": memo_assignments,
    }
    delete_fingerprints = {
        key: _queryset_fingerprint(queryset) for key, queryset in delete_querysets.items()
    }
    preserved = _preserved_state(source)
    plan_state = {
        "schema_version": SCHEMA_VERSION,
        "action": "delete_legacy_source",
        "database_vendor": connection.vendor,
        "database_name": connection.settings_dict.get("NAME") or "",
        "source_id": source_id,
        "runtime_source_id": runtime_source_id,
        "primary_source_ids": primary_source_ids,
        "source_state": {
            "pk": source.pk,
            "status": source.status,
            "is_primary": source.is_primary,
            "updated_at": source.updated_at,
        },
        "batch_state": [
            {
                "id": batch.id,
                "uuid": batch.batch_uuid,
                "snapshot_id": batch.prepared_snapshot_id,
                "status": batch.status,
                "created_at": batch.created_at,
                "updated_at": batch.updated_at,
            }
            for batch in batches
        ],
        "expected_batch_ids": sorted(set(expected_batch_ids or batch_ids)),
        "registry": registry,
        "delete": delete_fingerprints,
        "protected_source_counts": direct_block_counts,
        "protected_operational_counts": soft_block_counts,
        "reference_counts": {
            **canonical_reference_counts,
            "google_calendar_bindings": google_binding_count,
            "record_field_changes": record_field_change_count,
            "django_admin_logs": admin_log_count,
            "profiles_without_target_household": profile_without_household_count,
            "profiles_without_current_counterpart": (profile_without_current_counterpart_count),
        },
        "memo_assignments": memo_state,
        "batch_audits": [
            {
                "batch_id": audit["batch_id"],
                "blocker_codes": audit["blocker_codes"],
                "ready": audit["ready"],
            }
            for audit in batch_audits
        ],
        "unexpected_audit_blockers": unexpected_audit_blockers,
        "preserved": preserved,
        "blockers": sorted(set(blockers)),
    }
    encoded_plan = json.dumps(
        plan_state,
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan_hash = hashlib.sha256(encoded_plan).hexdigest()
    public_plan = {
        **plan_state,
        "ready": not blockers,
        "plan_hash": plan_hash,
    }
    return public_plan, delete_querysets


def build_legacy_source_retirement_plan(
    source_id: str,
    *,
    expected_batch_ids: list[int] | None = None,
) -> dict:
    can_enforce_read_only = connection.vendor == "postgresql" and not connection.in_atomic_block
    with transaction.atomic():
        if can_enforce_read_only:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        plan, _querysets = _build_plan_in_transaction(
            source_id,
            expected_batch_ids=expected_batch_ids,
            lock=False,
        )
        plan["read_only"] = True
        plan["database_read_only_enforced"] = can_enforce_read_only
        return plan


def _delete_exact(queryset: QuerySet, *, expected_count: int) -> None:
    model_label = queryset.model._meta.label
    deleted_count, deleted_by_model = queryset.delete()
    unexpected = {
        label: count for label, count in deleted_by_model.items() if label != model_label and count
    }
    if deleted_by_model.get(model_label, 0) != expected_count or unexpected:
        raise LegacySourceRetirementError(
            f"Unexpected delete closure for {model_label}: "
            f"expected={expected_count}, actual={deleted_by_model}"
        )
    if deleted_count != expected_count:
        raise LegacySourceRetirementError(
            f"Unexpected delete count for {model_label}: "
            f"expected={expected_count}, actual={deleted_count}"
        )


def _apply_database_retirement(
    *,
    source_id: str,
    plan: dict,
    querysets: dict[str, QuerySet],
) -> None:
    expected_counts = {key: int(value["count"]) for key, value in plan["delete"].items()}
    _delete_exact(
        querysets["memo_tag_assignments"],
        expected_count=expected_counts["memo_tag_assignments"],
    )
    _delete_exact(
        querysets["household_profiles"],
        expected_count=expected_counts["household_profiles"],
    )

    for batch in ImportBatch._base_manager.filter(
        source_id=plan["source_state"]["pk"]
    ).select_related("source"):
        audit = audit_batch_retirement(batch)
        if not audit["ready"]:
            raise LegacySourceRetirementError(
                f"Batch {batch.id} remained blocked after approved cleanup: "
                + ", ".join(audit["blocker_codes"])
            )

    Household._base_manager.filter(
        batch__source_id=plan["source_state"]["pk"],
        head_person__isnull=False,
    ).update(head_person=None)
    for key in (
        "deceased_profiles",
        "persons",
        "households",
        "import_issues",
        "source_operation_logs",
        "import_batches",
        "export_snapshots",
        "legacy_sources",
    ):
        _delete_exact(
            querysets[key],
            expected_count=expected_counts[key],
        )

    if LegacySource._base_manager.filter(source_id=source_id).exists():
        raise LegacySourceRetirementError("Legacy source still exists after retirement.")
    preserved_after = _preserved_state(
        LegacySource(
            pk=plan["source_state"]["pk"],
            source_id=source_id,
        )
    )
    if preserved_after != plan["preserved"]:
        raise LegacySourceRetirementError("Preserved data changed during legacy source retirement.")


def _execute_confirmed_plan_transaction(
    *,
    source_id: str,
    expected_batch_ids: list[int],
    confirm_plan: str,
    registry_recovery: dict,
) -> dict:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        plan, querysets = _build_plan_in_transaction(
            source_id,
            expected_batch_ids=expected_batch_ids,
            lock=True,
        )
        if not plan["ready"]:
            raise LegacySourceRetirementError(
                "Retirement plan is blocked: " + ", ".join(plan["blockers"])
            )
        if plan["plan_hash"] != confirm_plan:
            raise LegacySourceRetirementError(
                "The retirement plan changed. Run dry-run again and use the new plan hash."
            )

        registry_payload, registry_state = _registry_state(source_id)
        if registry_state != plan["registry"]:
            raise LegacySourceRetirementError(
                "The runtime source registry changed after planning. Run dry-run again."
            )
        original_registry_payload = json.loads(json.dumps(registry_payload, ensure_ascii=False))
        registry_recovery["original_payload"] = original_registry_payload
        registry_recovery["fallback_default_source_id"] = registry_state["default_source_id"]
        entries = registry_payload.get("sources", [])
        remaining = [entry for entry in entries if entry.get("source_id") != source_id]
        if len(remaining) != len(entries):
            registry_payload["sources"] = remaining
            registry_recovery["registry_write_attempted"] = True
            source_registry.save_source_registry_locked(registry_payload)

        registry_recovery["database_retirement_started"] = True
        _apply_database_retirement(
            source_id=source_id,
            plan=plan,
            querysets=querysets,
        )
        return plan


def _restore_registry_locked(original_payload: dict) -> None:
    source_registry.save_source_registry_locked(original_payload)
    if source_registry.load_source_registry() != original_payload:
        raise LegacySourceRetirementError(
            "Runtime source registry did not match its pre-retirement state after recovery."
        )


def _ensure_registry_target_absent_locked(
    source_id: str,
    *,
    fallback_default_source_id: str,
) -> None:
    registry = source_registry.load_source_registry()
    entries = registry.get("sources", [])
    remaining = [entry for entry in entries if entry.get("source_id") != source_id]
    changed = len(remaining) != len(entries)
    registry["sources"] = remaining
    if registry.get("default_source_id") == source_id:
        remaining_ids = {str(entry.get("source_id") or "") for entry in remaining}
        if fallback_default_source_id in remaining_ids:
            registry["default_source_id"] = fallback_default_source_id
        else:
            registry["default_source_id"] = remaining[0].get("source_id", "") if remaining else ""
        changed = True
    if changed:
        source_registry.save_source_registry_locked(registry)

    _payload, final_state = _registry_state(source_id)
    if final_state["target_entry_present"] or final_state["default_source_id"] == source_id:
        raise LegacySourceRetirementError(
            "Runtime source registry still references the retired source."
        )


def execute_legacy_source_retirement(
    source_id: str,
    *,
    expected_batch_ids: list[int],
    confirm_plan: str,
) -> dict:
    if not confirm_plan:
        raise LegacySourceRetirementError("--confirm-plan is required with --execute.")
    if not expected_batch_ids:
        raise LegacySourceRetirementError(
            "At least one --expect-batch-id is required with --execute."
        )
    if connection.vendor != "postgresql":
        raise LegacySourceRetirementError("Execution is supported only on PostgreSQL.")

    registry_recovery = {
        "registry_write_attempted": False,
        "database_retirement_started": False,
        "original_payload": None,
        "fallback_default_source_id": "",
    }
    with source_registry.source_registry_write_lock():
        try:
            plan = _execute_confirmed_plan_transaction(
                source_id=source_id,
                expected_batch_ids=expected_batch_ids,
                confirm_plan=confirm_plan,
                registry_recovery=registry_recovery,
            )
            _ensure_registry_target_absent_locked(
                source_id,
                fallback_default_source_id=registry_recovery["fallback_default_source_id"],
            )
        except Exception as exc:
            recovery_required = (
                registry_recovery["registry_write_attempted"]
                or registry_recovery["database_retirement_started"]
            )
            if not recovery_required:
                raise

            try:
                source_still_exists = LegacySource._base_manager.filter(
                    source_id=source_id
                ).exists()
            except Exception as status_exc:
                try:
                    _ensure_registry_target_absent_locked(
                        source_id,
                        fallback_default_source_id=registry_recovery["fallback_default_source_id"],
                    )
                except Exception as registry_exc:
                    raise LegacySourceRetirementError(
                        "Legacy source retirement failed and the database outcome is unknown; "
                        "runtime registry cleanup also failed. Inspect both states before retrying."
                    ) from registry_exc
                raise LegacySourceRetirementError(
                    "Legacy source retirement failed and the database outcome is unknown; "
                    "the runtime registry target was kept absent. Inspect the database before "
                    "retrying."
                ) from status_exc

            if source_still_exists:
                original_payload = registry_recovery["original_payload"]
                if not isinstance(original_payload, dict):
                    raise LegacySourceRetirementError(
                        "Database rollback is confirmed, but the registry recovery payload is "
                        "unavailable. Inspect the runtime registry before retrying."
                    ) from exc
                try:
                    _restore_registry_locked(original_payload)
                except Exception as registry_exc:
                    raise LegacySourceRetirementError(
                        "Database rollback is confirmed, but runtime registry restoration failed. "
                        "Repair the registry before retrying."
                    ) from registry_exc
                raise LegacySourceRetirementError(
                    f"Legacy source retirement failed ({exc}); database rollback is confirmed "
                    "and the runtime registry was restored."
                ) from exc

            try:
                _ensure_registry_target_absent_locked(
                    source_id,
                    fallback_default_source_id=registry_recovery["fallback_default_source_id"],
                )
            except Exception as registry_exc:
                raise LegacySourceRetirementError(
                    "The database retirement appears complete, but runtime registry cleanup "
                    "failed. Inspect both states before retrying."
                ) from registry_exc
            raise LegacySourceRetirementError(
                "The database retirement appears complete and the runtime registry target was "
                "kept absent, but the command reported an error. Verify the post-state before "
                "retrying."
            ) from exc

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "execute",
        "source_id": source_id,
        "expected_batch_ids": sorted(set(expected_batch_ids)),
        "confirmed_plan_hash": confirm_plan,
        "registry_quiesced": True,
        "deleted": True,
        "deleted_counts": {key: int(value["count"]) for key, value in plan["delete"].items()},
        "preserved": plan["preserved"],
    }


__all__ = [
    "LegacySourceRetirementError",
    "build_legacy_source_retirement_plan",
    "execute_legacy_source_retirement",
]
