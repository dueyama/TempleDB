from __future__ import annotations

from datetime import date, timedelta

from apps.core.services import memorial_dates

KIJITSU_STEPS = memorial_dates.KIJITSU_STEPS


def _runtime_module():
    from . import household_memorial_candidates_runtime

    return household_memorial_candidates_runtime


def _effective_memorial_rules(memorial_rules: list[dict]) -> list[dict]:
    return memorial_dates._effective_memorial_rules(memorial_rules)


def _build_memorial_candidates(
    memorial_members: list[dict],
    memorial_rules: list[dict],
    period_start: date,
    period_end: date,
) -> list[dict]:
    runtime = _runtime_module()
    candidates = []
    for person in memorial_members:
        death_date = runtime._parse_iso_date(person.get("death_date_iso"))
        if death_date is None:
            continue
        for label, offset in (("臨終勤行", 0), ("通夜", 1)):
            wake_date = runtime._parse_iso_date(person.get("wake_target_date")) if label == "通夜" else None
            target = wake_date or (death_date + timedelta(days=offset))
            if period_start <= target <= period_end:
                candidates.append({
                    "candidate_type": label, "label": label,
                    "target_date": target.isoformat(),
                    "household_id": person.get("household_id", ""),
                    "household_name": person.get("household_name", ""),
                    "person_name": person["name"], "person_id": person["person_id"],
                    "relationship": person["relationship"], "kaimyo": person["kaimyo"],
                    "death_date": person["death_date"],
                    "age_at_death": person.get("age_at_death", ""),
                    "age_unit": person.get("age_unit", "歳"),
                    "note": (
                        "登録済み葬儀の日程からの候補です。実際の日程に合わせて登録してください。"
                        if wake_date else "命日からの候補です。実際の日程に合わせて登録してください。"
                    ),
                })
        funeral_target_date_text = runtime._clean_value(person.get("funeral_target_date")) or (death_date + timedelta(days=2)).isoformat()
        funeral_target_date_value = runtime._parse_iso_date(funeral_target_date_text)
        if funeral_target_date_value is not None and period_start <= funeral_target_date_value <= period_end:
            candidates.append(
                {
                    "candidate_type": "葬儀",
                    "label": "葬儀",
                    "target_date": funeral_target_date_value.isoformat(),
                    "household_id": person.get("household_id", ""),
                    "household_name": person.get("household_name", ""),
                    "person_name": person["name"],
                    "relationship": person["relationship"],
                    "kaimyo": person["kaimyo"],
                    "death_date": person["death_date"],
                    "person_id": person["person_id"],
                    "age_at_death": person.get("age_at_death", ""),
                    "age_unit": person.get("age_unit", "歳"),
                    "note": (
                        f"葬儀予定日 {funeral_target_date_text} を表示"
                        if person.get("funeral_has_schedule")
                        else f"命日 {person['death_date']} の翌々日を葬儀候補日として表示"
                    ),
                }
            )
        funeral_date = runtime._parse_iso_date(person.get("reisan_funeral_date"))
        if funeral_date is not None:
            reisan_date = funeral_date + timedelta(days=1)
            if period_start <= reisan_date <= period_end:
                candidates.append({
                    "candidate_type": "礼参",
                    "label": "礼参",
                    "target_date": reisan_date.isoformat(),
                    "household_id": person.get("household_id", ""),
                    "household_name": person.get("household_name", ""),
                    "person_name": person["name"],
                    "relationship": person["relationship"],
                    "kaimyo": person["kaimyo"],
                    "death_date": person["death_date"],
                    "person_id": person["person_id"],
                    "age_at_death": person.get("age_at_death", ""),
                    "age_unit": person.get("age_unit", "歳"),
                    "note": f"葬儀日 {funeral_date.isoformat()} の翌日",
                })
        seen_memorial_dates: set[str] = set()
        for rule in memorial_rules:
            target_date = runtime._add_memorial_offset_years(death_date, rule["years"])
            if period_start <= target_date <= period_end:
                target_key = target_date.isoformat()
                if target_key in seen_memorial_dates:
                    continue
                seen_memorial_dates.add(target_key)
                candidates.append(
                    {
                        "candidate_type": "回忌",
                        "label": rule["label"] or runtime._to_memorial_label_from_offset(rule["years"]),
                        "target_date": target_date.isoformat(),
                        "household_id": person.get("household_id", ""),
                        "household_name": person.get("household_name", ""),
                        "person_name": person["name"],
                        "relationship": person["relationship"],
                        "kaimyo": person["kaimyo"],
                        "death_date": person["death_date"],
                        "person_id": person["person_id"],
                        "age_at_death": person.get("age_at_death", ""),
                        "age_unit": person.get("age_unit", "歳"),
                        "note": f"命日 {person['death_date']} から計算",
                    }
                )
        hatsubon_date = runtime._first_obon_date(death_date)
        if period_start <= hatsubon_date <= period_end:
            candidates.append(
                {
                    "candidate_type": "初盆",
                    "label": "初盆",
                    "target_date": hatsubon_date.isoformat(),
                    "household_id": person.get("household_id", ""),
                    "household_name": person.get("household_name", ""),
                    "person_name": person["name"],
                    "relationship": person["relationship"],
                    "kaimyo": person["kaimyo"],
                    "death_date": person["death_date"],
                    "person_id": person["person_id"],
                    "age_at_death": person.get("age_at_death", ""),
                    "age_unit": person.get("age_unit", "歳"),
                    "note": "四十九日を過ぎる最初の8/13を初盆候補として計算。",
                }
            )
        for kijitsu_step in KIJITSU_STEPS:
            kijitsu_date = death_date + timedelta(days=kijitsu_step["offset_days"])
            if period_start <= kijitsu_date <= period_end:
                candidates.append(
                    {
                        "candidate_type": "中陰",
                        "label": kijitsu_step["label"],
                        "target_date": kijitsu_date.isoformat(),
                        "household_id": person.get("household_id", ""),
                        "household_name": person.get("household_name", ""),
                        "person_name": person["name"],
                        "relationship": person["relationship"],
                        "kaimyo": person["kaimyo"],
                        "death_date": person["death_date"],
                        "person_id": person["person_id"],
                        "age_at_death": person.get("age_at_death", ""),
                        "age_unit": person.get("age_unit", "歳"),
                        "note": f"命日 {person['death_date']} から {kijitsu_step['label']} を計算",
                    }
                )
    candidates.sort(
        key=lambda item: (
            item["target_date"],
            item["candidate_type"] not in {"初盆", "中陰"},
            runtime._sort_text(item["person_name"]),
            runtime._int_sort(item["person_id"]),
        )
    )
    return candidates


def _notice_eligible_memorial_members(detail: dict) -> list[dict]:
    if (
        detail.get("household_general_notice_opt_out", False)
        or detail.get("household_memorial_notice_opt_out", False)
    ):
        return []
    return [
        member
        for member in detail.get("memorial_members", [])
        if not member.get("memorial_notice_opt_out", False)
    ]


def _decorate_memorial_members(
    memorial_members: list[dict],
    memorial_rules: list[dict],
    period_start: date,
    period_end: date,
    events: list[dict] | None = None,
) -> list[dict]:
    runtime = _runtime_module()
    today = runtime._runtime_timezone().localdate()
    events = events or []
    schedule_index: dict[tuple[str, str, str], dict] = {}
    funeral_index: dict[str, dict] = {}
    for event in events:
        if not runtime._service_event_is_actual(event):
            continue
        person_id = runtime._clean_value(event.get("person_id"))
        label = runtime._clean_value(event.get("schedule_type"))
        target_date = runtime._clean_value(event.get("target_date"))
        if not person_id or not label:
            continue
        if label == "葬儀":
            funeral_index.setdefault(person_id, event)
        schedule_index.setdefault((person_id, label, target_date), event)
        schedule_index.setdefault((person_id, label, ""), event)

    def attach_action(item: dict, *, person_id: str, category: str) -> dict:
        target_date_text = runtime._clean_value(item.get("target_date"))
        target_date_value = runtime._parse_iso_date(target_date_text)
        matched = schedule_index.get((person_id, runtime._clean_value(item.get("label")), target_date_text)) or schedule_index.get(
            (person_id, runtime._clean_value(item.get("label")), "")
        )
        if matched is None and (target_date_value is None or target_date_value < today):
            return {
                **item,
                "is_actionable": False,
                "has_schedule": False,
                "schedule_event_id": "",
                "schedule_source_table": "",
                "schedule_category": category,
                "schedule_status_label": "",
            }
        return {
            **item,
            "is_actionable": True,
            "has_schedule": matched is not None,
            "schedule_event_id": matched.get("event_id", "") if matched else "",
            "schedule_source_table": matched.get("source_table", "") if matched else "",
            "schedule_category": category,
            "schedule_status_label": matched.get("status_label", "") if matched else "",
        }

    decorated = []
    for person in memorial_members:
        person_id = person.get("person_id", "")
        death_date = runtime._parse_iso_date(person.get("death_date_iso"))
        calculated_memorials = []
        hatsubon = None
        funeral_event = funeral_index.get(person_id)
        wake_date = None
        if funeral_event and funeral_event.get("status") in {"scheduled", "completed"}:
            actual_funeral_date = runtime._parse_iso_date(
                (runtime._clean_value(funeral_event.get("completed_on")) if funeral_event.get("status") == "completed" else "")
                or runtime._clean_value(funeral_event.get("scheduled_date"))
                or runtime._clean_value(funeral_event.get("target_date"))
            )
            if death_date is not None and actual_funeral_date is not None and actual_funeral_date >= death_date:
                wake_date = max(death_date, actual_funeral_date - timedelta(days=1))
        funeral_target_date = (
            runtime._clean_value(funeral_event.get("scheduled_date")) if funeral_event is not None else ""
        ) or (
            runtime._clean_value(funeral_event.get("target_date")) if funeral_event is not None else ""
        ) or ((death_date + timedelta(days=2)).isoformat() if death_date else "")
        funeral_target_date_value = runtime._parse_iso_date(funeral_target_date)
        funeral_is_actionable = funeral_event is not None or (
            funeral_target_date_value is not None and funeral_target_date_value >= today
        )
        if death_date is not None:
            seen_memorial_dates: set[str] = set()
            for rule in memorial_rules:
                target_date = runtime._add_memorial_offset_years(death_date, rule["years"])
                target_key = target_date.isoformat()
                if target_key in seen_memorial_dates:
                    continue
                seen_memorial_dates.add(target_key)
                calculated_memorials.append(
                    attach_action(
                        {
                            "label": rule["label"] or runtime._to_memorial_label_from_offset(rule["years"]),
                            "target_date": target_date.isoformat(),
                            "in_range": period_start <= target_date <= period_end,
                        },
                        person_id=person_id,
                        category="memorial",
                    )
                )
            hatsubon_date = runtime._first_obon_date(death_date)
            hatsubon = attach_action(
                {
                    "label": "初盆",
                    "target_date": hatsubon_date.isoformat(),
                    "in_range": period_start <= hatsubon_date <= period_end,
                    "note": "四十九日を過ぎる最初の8/13を初盆候補として計算",
                },
                person_id=person_id,
                category="hatsubon",
            )
        decorated.append(
            {
                **person,
                "wake_target_date": wake_date.isoformat() if wake_date else "",
                "reisan_funeral_date": (
                    runtime._clean_value(funeral_event.get("completed_on"))
                    or runtime._clean_value(funeral_event.get("scheduled_date"))
                ) if funeral_event and funeral_event.get("status") not in {"cancelled", "deferred"} else "",
                "funeral_has_schedule": funeral_event is not None,
                "funeral_target_date": funeral_target_date,
                "funeral_is_actionable": funeral_is_actionable,
                "funeral_schedule_event_id": funeral_event.get("event_id", "") if funeral_event else "",
                "funeral_schedule_source_table": funeral_event.get("source_table", "") if funeral_event else "",
                "funeral_schedule_status_label": funeral_event.get("status_label", "") if funeral_event else "",
                "calculated_memorials": calculated_memorials,
                "calculated_hatsubon": hatsubon,
            }
        )
    return decorated
