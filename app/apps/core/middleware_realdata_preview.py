from __future__ import annotations

import re

from django.conf import settings
from django.http import HttpResponseForbidden
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils.html import format_html

from apps.core.context_processors import _realdata_preview_info

_BANNER_ID = re.compile(r"\bid\s*=\s*(['\"])realdata-preview-banner\1", re.IGNORECASE)
_BODY_TAG = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)
_TITLE_TAG = re.compile(r"<title\b[^>]*>", re.IGNORECASE)
_BACKUP_PATH = "/settings/backup"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RealDataPreviewMiddleware:
    """Safety and environment labels for the dedicated disposable Mac preview."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        preview_info = _realdata_preview_info()
        if preview_info is None:
            return self.get_response(request)

        if request.method not in _SAFE_METHODS and (
            request.path_info == _BACKUP_PATH
            or request.path_info.startswith(f"{_BACKUP_PATH}/")
        ):
            response = HttpResponseForbidden(
                "テスト環境ではバックアップ・復元の実行を停止しています。",
                content_type="text/plain; charset=utf-8",
            )
        else:
            response = self.get_response(request)

        response["Cache-Control"] = "no-store, private"
        response["X-TempleDB-Preview"] = settings.TEMPLEDB_PREVIEW_INFO.get("generation", "")
        if (
            response.streaming
            or response.get("Content-Type", "").split(";", 1)[0].strip().lower()
            != "text/html"
            or response.get("Content-Encoding")
        ):
            return response

        html = response.content.decode(response.charset)
        if _BANNER_ID.search(html) or not _BODY_TAG.search(html):
            return response

        stylesheet = str(
            format_html(
                '<link rel="stylesheet" href="{}">',
                static("office/realdata_preview.css"),
            )
        )
        banner = render_to_string(
            "core/_realdata_preview_banner.html",
            {"realdata_preview": preview_info, "request": request,
             "csrf_token": get_token(request)},
        )
        header = f'<div class="realdata-preview-header">{banner}</div>'
        if _HEAD_END.search(html):
            html = _HEAD_END.sub(lambda match: stylesheet + match.group(), html, count=1)
        else:
            header = stylesheet + header
        html = _TITLE_TAG.sub(lambda match: match.group() + "【テスト】", html, count=1)
        html = _BODY_TAG.sub(
            lambda match: match.group()[:-1] + ' data-realdata-preview="true">' + header,
            html,
            count=1,
        )
        response.content = html.encode(response.charset)
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        if response.has_header("ETag"):
            del response["ETag"]
        return response
