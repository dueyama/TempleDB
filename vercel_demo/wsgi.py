"""Serialize the preview's tenant switch; never shares a browser's DB or files."""
import os
import re
import secrets
import threading
from http.cookies import SimpleCookie

from django.core.wsgi import get_wsgi_application

os.environ["DJANGO_SETTINGS_MODULE"] = "vercel_demo.settings"
handler = get_wsgi_application()

from django.conf import settings  # noqa: E402
from django.core import signing  # noqa: E402
from django.db import connections  # noqa: E402

from vercel_demo.runtime import copy_seed, state_root  # noqa: E402

LOCK = threading.Lock()
COOKIE = "templedb_demo_sandbox"
SIGNER = signing.TimestampSigner(salt="templedb-vercel-synthetic")


def browser_id(environ):
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
        value = SIGNER.unsign(cookies[COOKIE].value, max_age=14400)
        if re.fullmatch(r"[a-f0-9]{32}", value):
            return value
    except (KeyError, signing.BadSignature):
        pass
    return secrets.token_hex(16)


def select_tenant(tenant):
    from config import runtime_paths, source_registry

    connections.close_all()
    previous = runtime_paths.TENANT_ROOT
    for name, value in vars(runtime_paths).copy().items():
        if name == "BASE_DIR" or not name.isupper():
            continue
        if hasattr(value, "is_relative_to") and value.is_relative_to(previous):
            setattr(runtime_paths, name, tenant / value.relative_to(previous))
    source_registry.RUNTIME_REGISTRY_PATH = runtime_paths.RUNTIME_SOURCE_REGISTRY_PATH
    settings.TEMPLEDB_TENANT_ROOT = tenant
    database = str(tenant / "data/runtime/demo.sqlite3")
    settings.DATABASES["default"]["NAME"] = database
    connections["default"].settings_dict["NAME"] = database


def application(environ, start_response):
    # The lock remains held through streaming and callbacks as well as rendering.
    with LOCK:
        identifier = browser_id(environ)
        tenant = state_root() / identifier
        copy_seed(tenant)
        select_tenant(tenant)
        token = SIGNER.sign(identifier)

        def respond(status, headers, exc_info=None):
            headers.append(("Set-Cookie", f"{COOKIE}={token}; Path=/; Max-Age=14400; Secure; HttpOnly; SameSite=Lax"))
            return start_response(status, headers, exc_info)

        response = handler(environ, respond)
        try:
            yield from response
        finally:
            response.close()
            connections.close_all()
