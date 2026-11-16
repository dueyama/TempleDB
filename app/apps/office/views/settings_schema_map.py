from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.services import schema_map as schema_map_services
from apps.office.views.common import _ensure_superuser


def schema_map(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    context = {
        "database_schema": schema_map_services.build_database_catalog(),
    }
    return render(request, "office/schema_map.html", context)


__all__ = ["schema_map"]
