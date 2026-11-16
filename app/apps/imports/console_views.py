from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.office.api import request_actor_label

from . import (
    legacy_reimport_guard,
    pipeline_console_runtime,
    pipeline_execution_runtime,
    source_runtime,
)


def console(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "imports/console.html",
        pipeline_console_runtime.build_console_context(
            operator_is_superuser=request.user.is_superuser,
        ),
    )


@require_POST
def run_action(request: HttpRequest, action: str) -> HttpResponse:
    if action in legacy_reimport_guard.LEGACY_REIMPORT_ACTIONS and not request.user.is_superuser:
        raise PermissionDenied("旧データの再取込は管理者のみ実行できます。")
    result = pipeline_execution_runtime.run_action(
        action,
        source_id=source_runtime.runtime_source_id(),
        actor=request_actor_label(request),
    )
    if result.ok:
        verb = "started" if action == "start-import-pipeline" else "completed"
        messages.success(request, f"{action} {verb}: {result.summary}")
    else:
        messages.error(request, f"{action} failed: {result.summary}")
    return redirect(reverse("imports:console"))


@require_POST
def register_source(request: HttpRequest) -> HttpResponse:
    del request
    return redirect(reverse("imports:console"))


@require_POST
def set_default_source(request: HttpRequest) -> HttpResponse:
    del request
    return redirect(reverse("imports:console"))
