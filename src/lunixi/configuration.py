"""Validated client configuration.

Validated in the constructor so a missing base URL or key id fails at start-up
with the field name, rather than on the first request with a 401.

🔴 The private key is handed to :class:`~lunixi.auth.ed25519_signer.Ed25519Signer`
and is NOT kept on this object. Configuration ends up in log lines, crash
reports and ``repr`` output; signing key material must not.
"""

from __future__ import annotations

import math
from typing import Optional

from .errors import ConfigurationError
from .http.transport import HttpTransport, UrllibTransport
from .validation import gateway_path, header_value, origin_url

__all__ = ["Configuration", "DEFAULT_AUTH_TOKEN_PATH"]

AUTHENTICATION_PATH = "/api/v1/auth/token"
DEFAULT_AUTH_TOKEN_PATH = AUTHENTICATION_PATH

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2


def _package_version() -> str:
    """Reads the installed version so the User-Agent needs no second edit."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8
        return "0.0.0"
    try:
        return version("lunixi-sdk")
    except PackageNotFoundError:
        # Running from a source checkout that was never installed.
        return "0.0.0+local"


class Configuration:
    """Connection and credential settings for one Lunixi account.

    Args:
        base_url: Gateway origin, for example ``https://api-gateway.lunixi.com``. A
            trailing slash is stripped so paths concatenate cleanly.
        key_id: The key id (``kid``) shown next to your key in the console.
        private_key: Your Ed25519 private key. A PKCS#8 PEM block is the
            expected form; see :class:`~lunixi.auth.ed25519_signer.Ed25519Signer`
            for the other accepted shapes.
        auth_token_path: Token endpoint path. The default is correct; it is
            settable only so a gateway deployed under a different prefix can be
            reached without a new release.
        timeout_seconds: Per-request timeout.
        max_retries: Extra attempts for an IDEMPOTENT request after a transport
            failure or a 5xx. A request that is not idempotent is never
            retried automatically — see
            :class:`~lunixi.api_client.ApiClient`.
        user_agent: Overrides the default ``lunixi-sdk/<version>``. Append your
            own application name rather than replacing it, so a support request
            still shows which SDK version produced the call.
        transport: An :class:`~lunixi.http.transport.HttpTransport`. Defaults
            to the standard-library transport.
    """

    __slots__ = (
        "base_url",
        "key_id",
        "auth_token_path",
        "timeout_seconds",
        "max_retries",
        "user_agent",
        "transport",
        "max_response_bytes",
    )

    def __init__(
        self,
        *,
        base_url: str,
        key_id: str,
        private_key: Optional[str] = None,
        auth_token_path: str = DEFAULT_AUTH_TOKEN_PATH,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        user_agent: Optional[str] = None,
        transport: Optional[HttpTransport] = None,
        allow_loopback_http: bool = False,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.base_url = origin_url(_required(base_url, "base_url"), allow_loopback_http)
        self.key_id = header_value(_required(key_id, "key_id"), "key_id")
        self.auth_token_path = gateway_path(_required(auth_token_path, "auth_token_path"))

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 120
        ):
            raise ConfigurationError("timeout_seconds must be finite, positive and at most 120.")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 5
        ):
            raise ConfigurationError("max_retries must be an integer from 0 to 5.")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1024 <= max_response_bytes <= 32 * 1024 * 1024
        ):
            raise ConfigurationError("max_response_bytes must be between 1 KiB and 32 MiB.")
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max_retries
        self.user_agent = header_value(
            user_agent or f"lunixi-sdk/{_package_version()}", "user_agent"
        )
        self.transport: HttpTransport = transport or UrllibTransport(
            max_response_bytes=max_response_bytes
        )

        # `private_key` is accepted here for a single-argument construction, but
        # is deliberately not stored: the caller's value is consumed by
        # LunixiClient when it builds the signer.
        del private_key

    def url_for(self, path: str) -> str:
        """Absolute URL for a gateway path (which must start with ``/``)."""
        return self.base_url + gateway_path(path)

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"Configuration(base_url={self.base_url!r}, key_id=<redacted>, "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries})"
        )


def _required(value: Optional[str], field: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"Configuration field '{field}' is required.")
    return value.strip()
