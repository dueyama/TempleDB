from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.services import starter_package
from apps.office.views.common import _ensure_superuser


@require_POST
def download_starter_package(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    if not starter_package.starter_package_available():
        raise Http404("スターターパッケージ作成機能を利用できません。")
    try:
        package_file, filename = starter_package.create_starter_package()
    except starter_package.StarterPackageBuildInProgressError:
        messages.error(request, "別のスターターパッケージ作成処理が実行中です。")
        return redirect(f"{reverse('office:settings_home')}#starter-package-card")
    except starter_package.StarterPackageError:
        messages.error(request, "TempleDBスターターパッケージを作成できませんでした。")
        return redirect(f"{reverse('office:settings_home')}#starter-package-card")
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


__all__ = ["download_starter_package"]
