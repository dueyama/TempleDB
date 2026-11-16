from __future__ import annotations


def _office_module():
    from apps.office.services import role_reports

    return role_reports


def build_district_officer_roster_context(source_id: str) -> dict:
    return _office_module().build_district_officer_roster_context(source_id)


def build_responsible_officer_roster_context(source_id: str) -> dict:
    return _office_module().build_responsible_officer_roster_context(source_id)


__all__ = [
    "build_district_officer_roster_context",
    "build_responsible_officer_roster_context",
]
