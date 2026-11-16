from __future__ import annotations

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import F, Model, Q, QuerySet
from django.db.models.fields.reverse_related import ForeignObjectRel

from .models import (
    DeceasedProfile,
    Household,
    ImportBatch,
    ImportIssue,
    MemoTagAssignment,
    Person,
    RecordEditLog,
    SourceOperationLog,
)

CANONICAL_MODELS = (Household, Person, DeceasedProfile)
CANONICAL_BATCH_RELATIONS = {
    (Household._meta.label, "batch"),
    (Person._meta.label, "batch"),
}
INTERNAL_CANONICAL_RELATIONS = {
    (Person._meta.label, "household", Household._meta.label),
    (Household._meta.label, "head_person", Person._meta.label),
    (DeceasedProfile._meta.label, "person", Person._meta.label),
}
PRESERVED_BATCH_RELATIONS = {
    (ImportIssue._meta.label, "batch"),
    (SourceOperationLog._meta.label, "target_batch"),
}
SOFT_IDENTITY_FIELDS = {
    Household: (
        "household_uid",
        "legacy_household_id",
        "selected_legacy_household_id",
        "selected_household_uid",
    ),
    Person: ("person_uid", "legacy_person_id", "mailing_person_uid"),
}
SUPPORTED_GENERIC_FOREIGN_KEYS = {
    ("imports.MemoTagAssignment", "content_object", "content_type", "object_id"),
}
SUPPORTED_CONTENT_TYPE_OBJECT_ID_PAIRS = {
    ("admin.LogEntry", "content_type", "object_id"),
    ("imports.MemoTagAssignment", "content_type", "object_id"),
}
SUPPORTED_TYPED_NAKED_ID_PAIRS = {
    ("imports.RecordEditLog", "record_type", "record_id"),
}
RECORD_EDIT_LOG_TARGETS: dict[str, type[Model] | None] = {
    RecordEditLog.RecordType.HOUSEHOLD.value: Household,
    RecordEditLog.RecordType.PERSON.value: Person,
    RecordEditLog.RecordType.SERVICE_SCHEDULE.value: None,
    RecordEditLog.RecordType.OFFERING_PAYMENT.value: None,
    RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_PAYMENT.value: None,
    RecordEditLog.RecordType.ANNUAL_MEMBERSHIP_FEE_SETTING.value: None,
    RecordEditLog.RecordType.DISTRICT.value: None,
    RecordEditLog.RecordType.DISTRICT_MEMBER_SHEET.value: None,
}
TERMINAL_BATCH_STATUSES = {
    ImportBatch.Status.SUCCEEDED,
    ImportBatch.Status.FAILED,
}


def _relation_key(*, related_model: type[Model], field_name: str, target_model: type[Model]) -> str:
    return f"{related_model._meta.label}.{field_name}->{target_model._meta.label}"


def _reverse_relations(target_model: type[Model]) -> list[ForeignObjectRel]:
    return [
        field
        for field in target_model._meta.get_fields(include_parents=True, include_hidden=True)
        if isinstance(field, ForeignObjectRel)
    ]


def _count_reverse_relations(
    target_model: type[Model],
    target_rows: QuerySet,
) -> tuple[dict[str, int], list[str]]:
    counts: dict[str, int] = {}
    unclassified_canonical_relations: list[str] = []
    for relation in _reverse_relations(target_model):
        related_model = relation.related_model
        field = relation.field
        signature = (related_model._meta.label, field.name, target_model._meta.label)
        key = _relation_key(
            related_model=related_model,
            field_name=field.name,
            target_model=target_model,
        )
        if signature in INTERNAL_CANONICAL_RELATIONS:
            continue
        if related_model in CANONICAL_MODELS:
            unclassified_canonical_relations.append(key)
        counts[key] = related_model._base_manager.filter(
            **{f"{field.name}__in": target_rows.values("pk")}
        ).count()
    return dict(sorted(counts.items())), sorted(unclassified_canonical_relations)


def _canonical_rows(batch: ImportBatch) -> dict[type[Model], QuerySet]:
    return {
        Household: Household.objects.filter(batch=batch),
        Person: Person.objects.filter(batch=batch),
        DeceasedProfile: DeceasedProfile.objects.filter(person__batch=batch),
    }


def _content_types_for_canonical_models() -> tuple[dict[type[Model], ContentType], list[str]]:
    query = Q(pk__in=[])
    models_by_natural_key: dict[tuple[str, str], type[Model]] = {}
    for model in CANONICAL_MODELS:
        natural_key = (model._meta.app_label, model._meta.model_name)
        models_by_natural_key[natural_key] = model
        query |= Q(app_label=natural_key[0], model=natural_key[1])

    content_types: dict[type[Model], ContentType] = {}
    for content_type in ContentType.objects.filter(query):
        model = models_by_natural_key.get((content_type.app_label, content_type.model))
        if model is not None:
            content_types[model] = content_type
    missing = sorted(model._meta.label for model in CANONICAL_MODELS if model not in content_types)
    return content_types, missing


def _unsupported_generic_foreign_keys() -> list[str]:
    unsupported: list[str] = []
    for model in apps.get_models():
        for field in model._meta.private_fields:
            if not isinstance(field, GenericForeignKey):
                continue
            signature = (
                model._meta.label,
                field.name,
                field.ct_field,
                field.fk_field,
            )
            if signature not in SUPPORTED_GENERIC_FOREIGN_KEYS:
                unsupported.append(".".join(signature))
    return sorted(unsupported)


def _unsupported_content_type_object_id_pairs() -> list[str]:
    unsupported: list[str] = []
    for model in apps.get_models():
        fields = {field.name: field for field in model._meta.fields}
        object_id_fields = [
            field
            for field in fields.values()
            if not field.is_relation and (field.name == "object_id" or field.name.endswith("_object_id"))
        ]
        for content_type_field in fields.values():
            if not (
                content_type_field.is_relation
                and content_type_field.remote_field.model._meta.label == "contenttypes.ContentType"
            ):
                continue
            for object_id_field in object_id_fields:
                signature = (
                    model._meta.label,
                    content_type_field.name,
                    object_id_field.name,
                )
                if signature not in SUPPORTED_CONTENT_TYPE_OBJECT_ID_PAIRS:
                    unsupported.append(".".join(signature))
    return sorted(unsupported)


def _unsupported_typed_naked_id_pairs() -> list[str]:
    integer_field_types = {
        "AutoField",
        "BigAutoField",
        "BigIntegerField",
        "IntegerField",
        "PositiveBigIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
        "SmallAutoField",
        "SmallIntegerField",
    }
    unsupported: list[str] = []
    for model in apps.get_models():
        fields = {field.name: field for field in model._meta.fields}
        for id_field in fields.values():
            if (
                id_field.is_relation
                or not id_field.name.endswith("_id")
                or id_field.get_internal_type() not in integer_field_types
            ):
                continue
            type_field_name = f"{id_field.name[:-3]}_type"
            type_field = fields.get(type_field_name)
            if type_field is None or type_field.is_relation:
                continue
            signature = (model._meta.label, type_field_name, id_field.name)
            if signature not in SUPPORTED_TYPED_NAKED_ID_PAIRS:
                unsupported.append(".".join(signature))
    return sorted(unsupported)


def _generic_reference_counts(
    rows: dict[type[Model], QuerySet],
    content_types: dict[type[Model], ContentType],
) -> dict[str, int | None]:
    return {
        model._meta.label: (
            MemoTagAssignment.objects.filter(
                content_type=content_types[model],
                object_id__in=queryset.values("pk"),
            ).count()
            if model in content_types
            else None
        )
        for model, queryset in rows.items()
    }


def _record_edit_log_counts(rows: dict[type[Model], QuerySet]) -> dict[str, int]:
    return {
        model._meta.label: RecordEditLog.objects.filter(
            record_type=record_type,
            record_id__in=rows[model].values("pk"),
        ).count()
        for record_type, model in RECORD_EDIT_LOG_TARGETS.items()
        if model is not None
    }


def _record_edit_log_type_inventory() -> dict[str, list[str] | int]:
    choice_values = {value for value, _label in RecordEditLog.RecordType.choices}
    configured_values = set(RECORD_EDIT_LOG_TARGETS)
    return {
        "unclassified_choice_values": sorted(choice_values - configured_values),
        "stale_configured_values": sorted(configured_values - choice_values),
        "stored_unknown_count": RecordEditLog.objects.exclude(
            record_type__in=configured_values
        ).count(),
    }


def _admin_log_counts(
    rows: dict[type[Model], QuerySet],
    content_types: dict[type[Model], ContentType],
) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for model, queryset in rows.items():
        if model not in content_types:
            counts[model._meta.label] = None
            continue
        object_ids = [str(pk) for pk in queryset.values_list("pk", flat=True)]
        counts[model._meta.label] = LogEntry.objects.filter(
            content_type=content_types[model],
            object_id__in=object_ids,
        ).count()
    return counts


def _cross_batch_reference_counts(batch: ImportBatch) -> dict[str, int]:
    return {
        "target_person_with_other_batch_household": Person.objects.filter(batch=batch)
        .exclude(household__batch=batch)
        .count(),
        "other_batch_person_with_target_household": Person.objects.filter(household__batch=batch)
        .exclude(batch=batch)
        .count(),
        "target_household_with_other_batch_head": Household.objects.filter(
            batch=batch,
            head_person__isnull=False,
        )
        .exclude(head_person__batch=batch)
        .count(),
        "other_batch_household_with_target_head": Household.objects.filter(
            head_person__batch=batch,
        )
        .exclude(batch=batch)
        .count(),
    }


def _canonical_provenance_mismatch_counts(batch: ImportBatch) -> dict[str, int]:
    return {
        "household_vs_batch_source": Household.objects.filter(batch=batch)
        .exclude(legacy_source_id=batch.source.source_id)
        .count(),
        "person_vs_batch_source": Person.objects.filter(batch=batch)
        .exclude(legacy_source_id=batch.source.source_id)
        .count(),
        "person_vs_household_source": Person.objects.filter(batch=batch)
        .exclude(legacy_source_id=F("household__legacy_source_id"))
        .count(),
        "household_vs_batch_snapshot": Household.objects.filter(batch=batch)
        .exclude(source_export_batch=batch.prepared_snapshot_id)
        .count(),
        "person_vs_batch_snapshot": Person.objects.filter(batch=batch)
        .exclude(source_export_batch=batch.prepared_snapshot_id)
        .count(),
    }


def _batch_relation_counts(batch: ImportBatch) -> tuple[dict[str, int], dict[str, int]]:
    preserved: dict[str, int] = {}
    operational: dict[str, int] = {}
    for relation in _reverse_relations(ImportBatch):
        related_model = relation.related_model
        field = relation.field
        signature = (related_model._meta.label, field.name)
        if signature in CANONICAL_BATCH_RELATIONS:
            continue
        count = related_model._base_manager.filter(**{field.name: batch}).count()
        key = f"{related_model._meta.label}.{field.name}"
        if signature in PRESERVED_BATCH_RELATIONS:
            preserved[key] = count
        else:
            operational[key] = count
    return dict(sorted(preserved.items())), dict(sorted(operational.items()))


def _latest_succeeded_batch_state(batch: ImportBatch) -> dict[str, int | bool | None]:
    succeeded = ImportBatch.objects.filter(
        source=batch.source,
        status=ImportBatch.Status.SUCCEEDED,
    )
    latest_created_at = succeeded.order_by("-created_at").values_list(
        "created_at",
        flat=True,
    ).first()
    if latest_created_at is None:
        candidate_ids: list[int] = []
    else:
        candidate_ids = list(
            succeeded.filter(created_at=latest_created_at)
            .order_by("id")
            .values_list("id", flat=True)
        )
    ambiguous = len(candidate_ids) > 1
    return {
        "batch_id": candidate_ids[0] if len(candidate_ids) == 1 else None,
        "candidate_count": len(candidate_ids),
        "ambiguous": ambiguous,
        "target_is_candidate": batch.id in candidate_ids,
    }


def _soft_identity_reference_counts(
    batch: ImportBatch,
    rows: dict[type[Model], QuerySet],
    *,
    latest_succeeded_batch_id: int | None,
    target_is_latest_candidate: bool,
) -> dict:
    matching: dict[str, int] = {}
    for model in apps.get_models():
        if model in CANONICAL_MODELS:
            continue
        fields = {field.name: field for field in model._meta.fields}
        source_query = Q()
        has_source_discriminator = False
        if "legacy_source_id" in fields:
            source_query |= Q(legacy_source_id=batch.source.source_id)
            has_source_discriminator = True
        if (
            "source" in fields
            and fields["source"].is_relation
            and fields["source"].remote_field.model._meta.label == "imports.LegacySource"
        ):
            source_query |= Q(source=batch.source)
            has_source_discriminator = True
        if not has_source_discriminator:
            continue

        for target_model, candidate_field_names in SOFT_IDENTITY_FIELDS.items():
            target_identity_field = (
                "household_uid" if target_model is Household else "person_uid"
            )
            target_identities = rows[target_model].values(target_identity_field)
            for field_name in candidate_field_names:
                if field_name not in fields:
                    continue
                key = (
                    f"{model._meta.label}.{field_name}->"
                    f"{target_model._meta.label}.{target_identity_field}"
                )
                matching[key] = model._base_manager.filter(
                    source_query,
                    **{f"{field_name}__in": target_identities},
                ).count()

    matching = dict(sorted(matching.items()))
    matching_total = _positive_total(matching)
    is_latest_succeeded_batch = latest_succeeded_batch_id == batch.id
    return {
        "matching": matching,
        "matching_total": matching_total,
        "batch_is_latest_succeeded": is_latest_succeeded_batch,
        "batch_is_latest_succeeded_candidate": target_is_latest_candidate,
        "blocking_total": matching_total if target_is_latest_candidate else 0,
    }


def _unclassified_soft_identity_fields() -> list[str]:
    classified_field_names = {
        field_name
        for field_names in SOFT_IDENTITY_FIELDS.values()
        for field_name in field_names
    }
    unclassified: list[str] = []
    for model in apps.get_models():
        if model in CANONICAL_MODELS:
            continue
        fields = {field.name: field for field in model._meta.fields}
        has_source_discriminator = "legacy_source_id" in fields or (
            "source" in fields
            and fields["source"].is_relation
            and fields["source"].remote_field.model._meta.label == "imports.LegacySource"
        )
        if not has_source_discriminator:
            continue
        for field in fields.values():
            name = field.name
            looks_like_soft_identity = (
                not field.is_relation
                and name.endswith("_id")
                and ("household" in name or "person" in name)
            )
            if looks_like_soft_identity and name not in classified_field_names:
                unclassified.append(f"{model._meta.label}.{name}")
    return sorted(unclassified)


def _positive_total(counts: dict[str, int | None]) -> int:
    return sum(value for value in counts.values() if isinstance(value, int) and value > 0)


def audit_batch_retirement(batch: ImportBatch) -> dict:
    rows = _canonical_rows(batch)
    external_references: dict[str, int] = {}
    unclassified_canonical_relations: list[str] = []
    for model, queryset in rows.items():
        relation_counts, unclassified = _count_reverse_relations(model, queryset)
        external_references.update(relation_counts)
        unclassified_canonical_relations.extend(unclassified)

    content_types, missing_content_types = _content_types_for_canonical_models()
    unsupported_generic_foreign_keys = _unsupported_generic_foreign_keys()
    unsupported_content_type_object_id_pairs = _unsupported_content_type_object_id_pairs()
    unsupported_typed_naked_id_pairs = _unsupported_typed_naked_id_pairs()
    unclassified_soft_identity_fields = _unclassified_soft_identity_fields()
    generic_references = _generic_reference_counts(rows, content_types)
    edit_log_references = _record_edit_log_counts(rows)
    record_edit_log_type_inventory = _record_edit_log_type_inventory()
    admin_log_references = _admin_log_counts(rows, content_types)
    cross_batch_references = _cross_batch_reference_counts(batch)
    provenance_mismatches = _canonical_provenance_mismatch_counts(batch)
    preserved_batch_references, operational_batch_references = _batch_relation_counts(batch)
    latest_succeeded_batch_state = _latest_succeeded_batch_state(batch)
    latest_succeeded_batch_id = latest_succeeded_batch_state["batch_id"]
    soft_identity_references = _soft_identity_reference_counts(
        batch,
        rows,
        latest_succeeded_batch_id=latest_succeeded_batch_id,
        target_is_latest_candidate=bool(
            latest_succeeded_batch_state["target_is_candidate"]
        ),
    )

    blocker_codes: list[str] = []
    if batch.status not in TERMINAL_BATCH_STATUSES:
        blocker_codes.append("NON_TERMINAL_BATCH_STATUS")
    if batch.source.is_primary:
        blocker_codes.append("PRIMARY_SOURCE")
    if latest_succeeded_batch_state["ambiguous"]:
        blocker_codes.append("LATEST_SUCCEEDED_BATCH_AMBIGUOUS")
    if _positive_total(cross_batch_references):
        blocker_codes.append("CROSS_BATCH_CANONICAL_REFERENCE")
    if _positive_total(provenance_mismatches):
        blocker_codes.append("CANONICAL_PROVENANCE_MISMATCH")
    if unclassified_canonical_relations:
        blocker_codes.append("UNCLASSIFIED_CANONICAL_RELATION")
    if _positive_total(external_references):
        blocker_codes.append("EXTERNAL_FOREIGN_KEY_REFERENCE")
    if _positive_total(operational_batch_references):
        blocker_codes.append("OPERATIONAL_BATCH_REFERENCE")
    if _positive_total(generic_references):
        blocker_codes.append("MEMO_TAG_ASSIGNMENT_REFERENCE")
    if _positive_total(edit_log_references):
        blocker_codes.append("RECORD_EDIT_LOG_REFERENCE")
    if _positive_total(admin_log_references):
        blocker_codes.append("DJANGO_ADMIN_LOG_REFERENCE")
    if missing_content_types:
        blocker_codes.append("CONTENT_TYPE_MISSING")
    if unsupported_generic_foreign_keys:
        blocker_codes.append("UNSUPPORTED_GENERIC_FOREIGN_KEY")
    if unsupported_content_type_object_id_pairs:
        blocker_codes.append("UNSUPPORTED_CONTENT_TYPE_OBJECT_ID_PAIR")
    if unsupported_typed_naked_id_pairs:
        blocker_codes.append("UNSUPPORTED_TYPED_NAKED_ID_PAIR")
    if _positive_total(record_edit_log_type_inventory) or any(
        record_edit_log_type_inventory[key]
        for key in ("unclassified_choice_values", "stale_configured_values")
    ):
        blocker_codes.append("UNSUPPORTED_RECORD_EDIT_LOG_TYPE")
    if unclassified_soft_identity_fields:
        blocker_codes.append("UNCLASSIFIED_SOFT_IDENTITY_FIELD")
    if soft_identity_references["blocking_total"]:
        blocker_codes.append("LATEST_BATCH_SOFT_IDENTITY_REFERENCE")

    return {
        "batch_id": batch.id,
        "source_id": batch.source.source_id,
        "snapshot_id": batch.prepared_snapshot_id,
        "status": batch.status,
        "source_state": {
            "is_primary": batch.source.is_primary,
            "latest_succeeded_batch_id": latest_succeeded_batch_id,
            "is_latest_succeeded_batch": latest_succeeded_batch_id == batch.id,
            "latest_succeeded_candidate_count": latest_succeeded_batch_state[
                "candidate_count"
            ],
            "latest_succeeded_is_ambiguous": latest_succeeded_batch_state["ambiguous"],
            "is_latest_succeeded_candidate": latest_succeeded_batch_state[
                "target_is_candidate"
            ],
        },
        "canonical_counts": {
            model._meta.label: queryset.count() for model, queryset in rows.items()
        },
        "references": {
            "cross_batch_canonical": cross_batch_references,
            "canonical_provenance_mismatches": provenance_mismatches,
            "unclassified_canonical_relations": sorted(unclassified_canonical_relations),
            "external_foreign_keys": dict(sorted(external_references.items())),
            "operational_batch": operational_batch_references,
            "memo_tag_assignments": generic_references,
            "record_edit_logs": edit_log_references,
            "record_edit_log_type_inventory": record_edit_log_type_inventory,
            "django_admin_logs": admin_log_references,
            "missing_content_types": missing_content_types,
            "unsupported_generic_foreign_keys": unsupported_generic_foreign_keys,
            "unsupported_content_type_object_id_pairs": (
                unsupported_content_type_object_id_pairs
            ),
            "unsupported_typed_naked_id_pairs": unsupported_typed_naked_id_pairs,
            "unclassified_soft_identity_fields": unclassified_soft_identity_fields,
            "soft_identity": soft_identity_references,
        },
        "preserved_audit_references": preserved_batch_references,
        "ready": not blocker_codes,
        "blocker_codes": blocker_codes,
    }


def _build_retirement_audit(batch_ids: list[int], *, database_read_only_enforced: bool) -> dict:
    unique_batch_ids = list(dict.fromkeys(batch_ids))
    if not unique_batch_ids:
        raise ValueError("At least one batch id is required.")
    batches_by_id = ImportBatch.objects.select_related("source").in_bulk(unique_batch_ids)
    missing_batch_ids = [batch_id for batch_id in unique_batch_ids if batch_id not in batches_by_id]
    if missing_batch_ids:
        missing = ", ".join(str(batch_id) for batch_id in missing_batch_ids)
        raise ImportBatch.DoesNotExist(f"ImportBatch not found: {missing}")

    batch_results = [audit_batch_retirement(batches_by_id[batch_id]) for batch_id in unique_batch_ids]
    return {
        "schema_version": 2,
        "read_only": True,
        "database_read_only_enforced": database_read_only_enforced,
        "isolation_level": "repeatable_read" if database_read_only_enforced else "database_default",
        "scope": {
            "retire": [
                Household._meta.label,
                Person._meta.label,
                DeceasedProfile._meta.label,
            ],
            "preserve": [
                "imports.LegacySource",
                "imports.ExportSnapshot",
                ImportBatch._meta.label,
                ImportIssue._meta.label,
                SourceOperationLog._meta.label,
            ],
        },
        "batch_ids": unique_batch_ids,
        "ready": all(result["ready"] for result in batch_results),
        "batches": batch_results,
    }


def build_retirement_audit(batch_ids: list[int]) -> dict:
    can_enforce_database_read_only = connection.vendor == "postgresql" and not connection.in_atomic_block
    with transaction.atomic():
        if can_enforce_database_read_only:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _build_retirement_audit(
            batch_ids,
            database_read_only_enforced=can_enforce_database_read_only,
        )


__all__ = ["audit_batch_retirement", "build_retirement_audit"]
