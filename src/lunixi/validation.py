"""Shared boundary validation; caller-controlled inputs cannot change an origin."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from .errors import ConfigurationError

SAFE_INTEGER = 9007199254740991
CURRENCIES = frozenset(
    (
        "TRY",
        "USD",
        "EUR",
        "GBP",
        "RUB",
        "AED",
        "SAR",
        "QAR",
        "KWD",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "CNY",
        "AZN",
    )
)


def amount_minor(value: Any, *, positive: bool = True) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (1 if positive else 0)
        or value > SAFE_INTEGER
    ):
        raise ConfigurationError("Amount must be an integer in the safe minor-unit range.")
    return value


def currency_code(value: str) -> str:
    if not isinstance(value, str) or value not in CURRENCIES:
        raise ConfigurationError("A supported uppercase currency is required.")
    return value


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value):
        raise ConfigurationError("Invalid resource identifier.")
    return value


def header_value(value: str, field: str, max_length: int = 200) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > max_length
        or any(ord(c) < 32 or ord(c) > 126 for c in value)
    ):
        raise ConfigurationError(f"Invalid {field} header.")
    return value


def origin_url(value: str, allow_loopback_http: bool = False) -> str:
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise ConfigurationError("base_url must be a trusted HTTPS origin.")
    u = urlsplit(value)
    try:
        valid_port = u.port is None or 1 <= u.port <= 65535
    except ValueError:
        valid_port = False
    loopback = False
    try:
        loopback = ipaddress.ip_address(u.hostname or "").is_loopback
    except ValueError:
        pass
    if (
        not u.hostname
        or u.username is not None
        or u.password is not None
        or "?" in value
        or "#" in value
        or u.path not in ("", "/")
        or not valid_port
        or (u.scheme != "https" and not (allow_loopback_http and u.scheme == "http" and loopback))
    ):
        raise ConfigurationError(
            "base_url must be an HTTPS origin; HTTP requires explicit numeric-loopback test opt-in."
        )
    return value.rstrip("/")


def gateway_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/api/v1/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
    ):
        raise ConfigurationError("Path must remain under /api/v1/ on the configured origin.")
    u = urlsplit(value)
    if u.netloc or u.scheme or u.fragment:
        raise ConfigurationError("Invalid gateway path.")
    decoded = u.path
    for _ in range(8):
        current = unquote(decoded)
        if current == decoded:
            break
        decoded = current
    if (
        "%" in decoded
        or "\\" in decoded
        or any(p in (".", "..") for p in decoded.split("/"))
        or "//" in decoded
    ):
        raise ConfigurationError("Path normalization or traversal is not permitted.")
    return value
