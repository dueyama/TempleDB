"""Read-only household-browser labels for virtual heads, based on recorded succession."""

from .household_head_runtime import VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE
from .models import Household, RecordEditLog


def virtual_head_browser_metadata(households: list[Household]) -> dict[str, dict]:
    virtual = {
        household.pk: household for household in households
        if household.head_person_id
        and household.head_person.deleted_at is None
        and household.head_person.source_table == VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE
    }
    result = {
        household.household_uid: {"is_virtual": True, "label": household.head_person.name,
                                  "search_terms": [household.head_person.name]}
        for household in virtual.values()
    }
    if not virtual:
        return result
    found = set()
    for log in RecordEditLog.objects.filter(
        record_type=RecordEditLog.RecordType.HOUSEHOLD, record_id__in=virtual,
    ).only("record_id", "before_data", "after_data").order_by("-id"):
        if log.record_id in found:
            continue
        household = virtual[log.record_id]
        before, after = log.before_data or {}, log.after_data or {}
        previous_name = str(before.get("head_name") or "").strip()
        if (str(after.get("head_person_id")) != str(household.head_person_id)
                or str(before.get("head_person_id")) == str(household.head_person_id)
                or not previous_name or previous_name.startswith("仮戸主")):
            continue
        previous_kana = str(before.get("head_name_kana") or "").strip()
        surname = previous_name.split()[0]
        result[household.household_uid].update(
            label=f"仮戸主（{surname}）", kana=previous_kana,
            search_terms=[household.head_person.name, previous_name, previous_kana],
        )
        found.add(log.record_id)
    return result
