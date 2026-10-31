"""Shared setup for the samples.

Settings come from the environment, so no credential is written into a file in
this repository. Export them in your shell, or load them from your secret
manager before running a sample:

    export LUNIXI_BASE_URL="https://api-gateway.lunixi.com"
    export LUNIXI_KEY_ID="kid_..."
    export LUNIXI_PRIVATE_KEY_FILE="/secure/path/lunixi-private-key.pem"

`LUNIXI_PRIVATE_KEY` is read as an alternative when your platform injects the
PEM directly rather than as a file.
"""

from __future__ import annotations

import os
import sys

from lunixi import LunixiClient


def build_client() -> LunixiClient:
    """Builds a client from the environment, or exits with what is missing."""
    base_url = os.environ.get("LUNIXI_BASE_URL")
    key_id = os.environ.get("LUNIXI_KEY_ID")
    private_key = _read_private_key()

    missing = [
        name
        for name, value in (
            ("LUNIXI_BASE_URL", base_url),
            ("LUNIXI_KEY_ID", key_id),
            ("LUNIXI_PRIVATE_KEY_FILE or LUNIXI_PRIVATE_KEY", private_key),
        )
        if not value
    ]
    if missing:
        sys.exit("Set these environment variables first: " + ", ".join(missing))

    return LunixiClient(base_url=base_url, key_id=key_id, private_key=private_key)


def _read_private_key() -> "str | None":
    path = os.environ.get("LUNIXI_PRIVATE_KEY_FILE")
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    return os.environ.get("LUNIXI_PRIVATE_KEY")
