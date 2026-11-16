from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.core.services import handoff_package
from apps.office.views.common import _ensure_superuser


def download_handoff_package(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    if request.method != "POST":
        return redirect(reverse("office:settings_home"))
    try:
        package_file, filename = handoff_package.create_handoff_package()
    except Exception as exc:
        messages.error(request, f"AI引き継ぎパッケージを作成できませんでした: {exc}")
        return redirect(reverse("office:settings_home"))
    response = FileResponse(
        package_file,
        as_attachment=True,
        filename=filename,
        content_type="application/gzip",
    )
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


__all__ = ["download_handoff_package"]
