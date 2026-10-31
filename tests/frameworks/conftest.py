from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest

django = pytest.importorskip("django")
_test_root = Path(tempfile.mkdtemp(prefix="lunixi-django-framework-tests-"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integrations.django_app.settings")
os.environ.setdefault("LUNIXI_SESSION_SECRET", "synthetic_django_session_secret_0123456789")
os.environ.setdefault("LUNIXI_PUBLIC_ORIGIN", "https://testserver")
os.environ.setdefault("LUNIXI_DATABASE", str(_test_root / "native.sqlite3"))

django.setup()
settings = importlib.import_module("django.conf").settings

settings.DATABASES["default"].setdefault("TEST", {}).update(
    NAME=str(_test_root / "acceptance.sqlite3")
)
