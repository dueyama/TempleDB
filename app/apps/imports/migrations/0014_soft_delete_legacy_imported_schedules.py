from django.db import migrations
from django.utils import timezone

LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES = (
    "UTM010_予定明細",
    "UTY020_初盆予定作成",
)


def soft_delete_legacy_imported_schedules(apps, schema_editor):
    ServiceSchedule = apps.get_model("imports", "ServiceSchedule")
    ServiceSchedule.objects.filter(
        record_origin="imported",
        source_table__in=LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES,
        deleted_at__isnull=True,
    ).update(
        deleted_at=timezone.now(),
        deleted_by="migration",
        deletion_note="旧予定は canonical に取り込まない方針へ変更",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0013_backfill_missing_head_people"),
    ]

    operations = [
        migrations.RunPython(
            soft_delete_legacy_imported_schedules,
            migrations.RunPython.noop,
        ),
    ]
