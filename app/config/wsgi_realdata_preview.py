"""A separate startup guard; does not modify the production current selection."""
from django.core.wsgi import get_wsgi_application

from .realdata_preview_guard import verify_live_database

application = get_wsgi_application()
verify_live_database()
