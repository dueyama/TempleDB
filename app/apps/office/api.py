from __future__ import annotations

from django.http import HttpRequest

from apps.office import services as office_services
from apps.office.services.district_history import (
    record_district_change as record_district_change,
)
from apps.office.services.district_history import (
    serialize_district as serialize_district,
)
from apps.office.services.household_postal_assignments import (
    apply_household_postal_assignment as apply_household_postal_assignment,
)
from apps.office.services.household_postal_assignments import (
    record_postal_household_creation as record_postal_household_creation,
)
from apps.office.services.monto_sodai_assignments import (
    assign_monto_sodai_to_person as assign_monto_sodai_to_person,
)
from apps.office.web_support import _request_actor_label

__all__ = [
    "apply_household_postal_assignment",
    "assign_monto_sodai_to_person",
    "build_data_quality_context",
    "record_district_change",
    "record_postal_household_creation",
    "request_actor_label",
    "serialize_district",
]


def build_data_quality_context(
    source_id: str | None = None,
    query: str = "",
    data_backend: str = "auto",
) -> dict:
    return office_services.build_data_quality_context(
        source_id=source_id,
        query=query,
        data_backend=data_backend,
    )


def request_actor_label(request: HttpRequest) -> str:
    return _request_actor_label(request)
