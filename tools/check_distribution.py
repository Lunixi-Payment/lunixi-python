"""Check built wheel/sdist portability, source examples and public-file boundaries."""

from __future__ import annotations

import re
import tarfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
match = re.search(
    r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', (root / "pyproject.toml").read_text(), re.M
)
assert match is not None, "Release metadata requires a semantic version"
version = match.group(1)
wheel = next((root / "dist").glob(f"lunixi_sdk-{version}-*.whl"))
sdist = root / f"dist/lunixi_sdk-{version}.tar.gz"
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert "lunixi/payments/__init__.py" in names
    assert "lunixi/commerce/service.py" in names
    assert "lunixi/py.typed" in names
    assert not any(n.startswith(("tests/", "integrations/", ".venv/")) for n in names)
    contents = [(name, archive.read(name)) for name in names]
with tarfile.open(sdist, "r:gz") as archive:
    names = archive.getnames()
    for suffix in (
        "integrations/flask_app.py",
        "integrations/fastapi_app.py",
        "integrations/django_app/shop/migrations/0001_initial.py",
        "docs/FRAMEWORKS.md",
        "docs/FRAMEWORKS.tr.md",
        "requirements-dev.lock",
        ".github/assets/lunixi-logo.svg",
    ):
        assert any(n.endswith("/" + suffix) for n in names), suffix
    contents.extend(
        (member.name, archive.extractfile(member).read())
        for member in archive.getmembers()
        if member.isfile()
    )
for name, value in contents:
    assert not name.startswith("/") and ".." not in Path(name).parts
    assert ".venv/" not in name and not name.endswith((".sqlite3", ".pem", ".key", ".pyc"))
    assert not re.search(
        rb"/(?:Users|home)/[A-Za-z0-9._-]{1,64}/|(?<![A-Za-z0-9_.])git@[a-z0-9.-]+[.][a-z]+[:/]|/tmp/"
        + rb"lunixi-",
        value,
    ), name
print("Wheel/sdist layout, native examples, typing, logos and public-path checks passed.")
