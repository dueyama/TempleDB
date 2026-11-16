from django.db import migrations
from django.db.models import Exists, OuterRef


def validate_retired_active_batch_values(apps, schema_editor) -> None:
    legacy_source = apps.get_model("imports", "LegacySource")
    import_batch = apps.get_model("imports", "ImportBatch")
    valid_active_batch = import_batch.objects.filter(
        id=OuterRef("active_import_batch_id"),
        source_id=OuterRef("id"),
        status="succeeded",
    )
    invalid = (
        legacy_source.objects.exclude(active_import_batch_id__isnull=True)
        .annotate(active_batch_is_valid=Exists(valid_active_batch))
        .filter(active_batch_is_valid=False)
    )
    invalid_rows = list(
        invalid.order_by("id").values_list(
            "source_id",
            "active_import_batch_id",
        )[:20]
    )
    if invalid_rows:
        raise RuntimeError(
            "Cannot retire LegacySource.active_import_batch because invalid "
            f"references remain: {invalid_rows}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0066_rename_operational_person_uid_columns"),
    ]

    operations = [
        migrations.RunPython(
            validate_retired_active_batch_values,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="legacysource",
            name="active_import_batch",
        ),
    ]
