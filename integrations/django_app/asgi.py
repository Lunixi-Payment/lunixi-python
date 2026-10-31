"""ASGI application; serve behind a trusted HTTPS boundary."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integrations.django_app.settings")
application = get_asgi_application()
