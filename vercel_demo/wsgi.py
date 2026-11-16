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

from vercel_demo.runtime import (  # noqa: E402
    SANDBOX_TTL,
    SandboxCapacityError,
    discard_sandbox,
    prepare_sandbox,
    sandbox_lock,
)

LOCK = threading.Lock()
COOKIE = "templedb_demo_sandbox"
SIGNER = signing.TimestampSigner(salt="templedb-vercel-synthetic")


def browser_id(environ):
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
        value = SIGNER.unsign(cookies[COOKIE].value, max_age=SANDBOX_TTL)
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
    with LOCK, sandbox_lock() as root:
        identifier = browser_id(environ)
        try:
            tenant = prepare_sandbox(root, identifier)
        except SandboxCapacityError:
            body = "現在デモが混み合っています。時間をおいて再度お試しください。".encode()
            start_response("503 Service Unavailable", [
                ("Content-Type", "text/plain; charset=utf-8"), ("Retry-After", "60"),
                ("Cache-Control", "no-store"), ("Content-Length", str(len(body))),
            ])
            yield body
            return
        select_tenant(tenant)
        token = SIGNER.sign(identifier)
        logged_out = False

        def respond(status, headers, exc_info=None):
            nonlocal logged_out
            logged_out = (
                environ.get("PATH_INFO") == "/logout/"
                and environ.get("REQUEST_METHOD") == "POST"
                and 300 <= int(status.split()[0]) < 400
            )
            # Dropping this browser's identifier starts a fresh copy next time.
            value = "; Max-Age=0" if logged_out else token
            headers.append(("Set-Cookie", f"{COOKIE}={value}; Path=/; Secure; HttpOnly; SameSite=Lax"))
            return start_response(status, headers, exc_info)

        response = None
        try:
            response = handler(environ, respond)
            yield from response
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                connections.close_all()
                if logged_out:
                    discard_sandbox(tenant)
