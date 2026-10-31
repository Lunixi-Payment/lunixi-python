"""Secure defaults; provide server settings through the environment."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from lunixi.validation import origin_url

SECRET_KEY = os.environ["LUNIXI_SESSION_SECRET"]
if len(SECRET_KEY) < 32:
    raise RuntimeError("A separate session secret of at least 32 characters is required.")
PUBLIC_ORIGIN = origin_url(os.environ["LUNIXI_PUBLIC_ORIGIN"])
DEBUG = False
ALLOWED_HOSTS = [urlsplit(PUBLIC_ORIGIN).hostname]
ROOT_URLCONF = "integrations.django_app.urls"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "integrations.django_app.shop",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ["LUNIXI_DATABASE"],
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 10},
    }
}
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [Path(__file__).parent / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ]
        },
    }
]
LANGUAGE_CODE = os.environ.get("LUNIXI_LOCALE", "en")
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN]
SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
STATIC_URL = "/static/"

CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"
