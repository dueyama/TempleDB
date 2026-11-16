from __future__ import annotations

from urllib.parse import unquote

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.office import services


def person_search(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    ledger = request.GET.get("ledger", "all")
    context = services.build_person_search_context(query=query, ledger=ledger)
    context.pop("selected_source_id", None)
    context["current_url"] = unquote(request.get_full_path())
    return render(request, "office/person_search.html", context)
