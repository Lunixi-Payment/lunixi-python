"""Validated client configuration.

Validated in the constructor so a missing base URL or key id fails at start-up
with the field name, rather than on the first request with a 401.

🔴 The private key is handed to :class:`~lunixi.auth.ed25519_signer.Ed25519Signer`
and is NOT kept on this object. Configuration ends up in log lines, crash
reports and ``repr`` output; signing key material must not.
"""

from __future__ import annotations

from typing import Optional

from .errors import ConfigurationError
from .http.transport import HttpTransport, UrllibTransport

__all__ = ["Configuration", "DEFAULT_AUTH_TOKEN_PATH"]

DEFAULT_AUTH_TOKEN_PATH = "/api/v1/auth/token"

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
        base_url: Gateway origin, for example ``https://api.lunixi.com``. A
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
    ) -> None:
        self.base_url = _required(base_url, "base_url").rstrip("/")
        self.key_id = _required(key_id, "key_id")
        self.auth_token_path = _required(auth_token_path, "auth_token_path")

        if not str(self.base_url).startswith(("http://", "https://")):
            raise ConfigurationError(
                "Configuration field 'base_url' must start with http:// or https://."
            )
        if not self.auth_token_path.startswith("/"):
            raise ConfigurationError("Configuration field 'auth_token_path' must start with '/'.")

        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ConfigurationError("Configuration field 'timeout_seconds' must be positive.")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ConfigurationError(
                "Configuration field 'max_retries' must be an integer of 0 or more."
            )

        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max_retries
        self.user_agent = user_agent or f"lunixi-sdk/{_package_version()}"
        self.transport: HttpTransport = transport or UrllibTransport()

        # `private_key` is accepted here for a single-argument construction, but
        # is deliberately not stored: the caller's value is consumed by
        # LunixiClient when it builds the signer.
        del private_key

    def url_for(self, path: str) -> str:
        """Absolute URL for a gateway path (which must start with ``/``)."""
        return self.base_url + path

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"Configuration(base_url={self.base_url!r}, key_id={self.key_id!r}, "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries})"
        )


def _required(value: Optional[str], field: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"Configuration field '{field}' is required.")
    return value.strip()
