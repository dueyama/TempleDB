from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from apps.core.realdata_preview_control import request_exit


@require_POST
@login_required
@csrf_protect
def exit_preview(request):
    if settings.ROOT_URLCONF != "config.urls_realdata_preview":
        raise Http404
    if not request.user.is_active or not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("管理者だけがテスト環境を終了できます。")
    action = request.POST.get("action", "")
    try:
        request_exit(action=action, run_id=request.POST.get("run_id", ""))
    except (OSError, ValueError, RuntimeError):
        return render(request, "core/realdata_preview_exit.html", {"exit_error": True}, status=409)
    return render(request, "core/realdata_preview_exit.html", {"confirmed": action == "finish"})

