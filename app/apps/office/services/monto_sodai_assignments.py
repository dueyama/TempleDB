from __future__ import annotations

from django.db import transaction

from apps.imports.models import Person, RecordEditLog

from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import _serialize_person_record


@transaction.atomic
def assign_monto_sodai_to_person(
    person: Person,
    *,
    editor_label: str = "",
    change_note: str = "",
) -> bool:
    if person.is_monto_sodai:
        return False

    before_data = _serialize_person_record(person)
    person.is_monto_sodai = True
    person.save(update_fields=["is_monto_sodai", "updated_at"])
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.PERSON,
        record=person,
        before_data=before_data,
        after_data=_serialize_person_record(person),
        editor_label=(editor_label or "").strip() or "system",
        change_note=(change_note or "").strip() or "総代CSVから総代を指定",
    )
    return True
