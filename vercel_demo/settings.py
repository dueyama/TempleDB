from vercel_demo.runtime import configure

configure()

from config.settings import *  # noqa: E402,F403

WSGI_APPLICATION = "vercel_demo.wsgi.application"
ASGI_APPLICATION = None
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
MIDDLEWARE = [  # noqa: F405
    item for item in MIDDLEWARE  # noqa: F405
    if item != "apps.core.middleware.DatabaseBackupScheduleMiddleware"
] + ["vercel_demo.banner.DemoBannerMiddleware"]
