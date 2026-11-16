from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def print_hub(request: HttpRequest) -> HttpResponse:
    return render(request, "office/print_hub.html")


__all__ = ["print_hub"]
