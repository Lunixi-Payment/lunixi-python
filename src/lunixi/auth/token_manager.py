"""Signed token exchange and the access-token cache.

Flow: an Ed25519-signed ``POST /api/v1/auth/token`` returns a short-lived
opaque access token; every subsequent call carries it as a bearer token. The
private key signs only the exchange (and the few routes that require a
per-request signature), so the key is used rarely and the token does the
routine work.

The exchange request carries NO body, therefore no ``Digest`` header and no
``Digest`` line in the canonical string.
"""

from __future__ import annotations

import binascii
import os
import threading
import time
from typing import Any, Dict, Mapping, Optional

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover - unreachable on supported versions
    from typing_extensions import Protocol  # type: ignore[assignment]

from ..configuration import Configuration
from ..errors import ApiError, AuthenticationError
from ..http.envelope import data_of
from ..http.transport import TransportError
from .canonical_request import (
    HEADER_DATE,
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    build_canonical_request,
)
from .ed25519_signer import Ed25519Signer

__all__ = ["TokenStore", "InMemoryTokenStore", "TokenManager", "utc_timestamp", "new_nonce"]

#: Seconds shaved off the advertised lifetime before a token is considered
#: stale. Without it a token fetched at the very end of its window can expire
#: in flight and the request fails with a 401 that no retry explains.
_EXPIRY_SKEW_SECONDS = 30

_DEFAULT_TTL_SECONDS = 300


def utc_timestamp() -> str:
    """Returns ``X-Date`` in the format the gateway's ±5 minute check parses.

    Second precision, explicit ``Z``: ``2026-10-11T08:30:00Z``.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_nonce() -> str:
    """Returns a fresh 32-character hex nonce.

    The gateway remembers used nonces and rejects a repeat with
    ``NONCE_REPLAY``, so this must come from the OS entropy source — a
    pseudo-random value shared by two processes starting at the same moment
    would lock one of them out.
    """
    return binascii.hexlify(os.urandom(16)).decode("ascii")


class TokenStore(Protocol):
    """Where a cached access token lives.

    The default store keeps the token in memory, which means one exchange per
    process. In a multi-process deployment (several workers, serverless
    invocations), implement this against a shared cache so the workers share
    one token instead of each burning its own exchange.
    """

    def get(self) -> Optional[str]:
        """Returns a still-valid token, or ``None``."""
        ...  # pragma: no cover - protocol declaration

    def set(self, token: str, ttl_seconds: int) -> None:
        """Stores a token with its remaining lifetime in seconds."""
        ...  # pragma: no cover - protocol declaration

    def clear(self) -> None:
        """Drops the cached token."""
        ...  # pragma: no cover - protocol declaration


class InMemoryTokenStore:
    """Process-local token cache, safe to share between threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def get(self) -> Optional[str]:
        with self._lock:
            if self._token is None or self._expires_at <= time.time():
                return None
            return self._token

    def set(self, token: str, ttl_seconds: int) -> None:
        with self._lock:
            self._token = token
            self._expires_at = time.time() + max(1, ttl_seconds) - _EXPIRY_SKEW_SECONDS

    def clear(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0


class TokenManager:
    """Exchanges the signed request for a bearer token and caches it."""

    def __init__(
        self,
        config: Configuration,
        signer: Ed25519Signer,
        store: Optional[TokenStore] = None,
    ) -> None:
        self._config = config
        self._signer = signer
        self._store: TokenStore = store if store is not None else InMemoryTokenStore()
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """Returns a usable access token, fetching one if the cache is empty."""
        cached = self._store.get()
        if cached:
            return cached

        # One exchange at a time per manager: without this, a burst of threads
        # starting cold would each fetch a token and the later ones would
        # overwrite the cache entry the earlier ones just stored.
        with self._lock:
            cached = self._store.get()
            if cached:
                return cached
            token, ttl = self._exchange()
            self._store.set(token, ttl)
            return token

    def invalidate(self) -> None:
        """Drops the cached token so the next call exchanges a fresh one."""
        self._store.clear()

    def signed_token_headers(self) -> Dict[str, str]:
        """Headers for the token exchange: signature, no body, no digest."""
        date = utc_timestamp()
        nonce = new_nonce()
        canonical = build_canonical_request("POST", self._config.auth_token_path, date, nonce)
        return {
            "Accept": "application/json",
            "User-Agent": self._config.user_agent,
            HEADER_KEY_ID: self._config.key_id,
            HEADER_DATE: date,
            HEADER_NONCE: nonce,
            HEADER_SIGNATURE: self._signer.sign(canonical),
        }

    def _exchange(self) -> "tuple[str, int]":
        url = self._config.url_for(self._config.auth_token_path)
        try:
            response = self._config.transport.send(
                "POST",
                url,
                self.signed_token_headers(),
                None,
                self._config.timeout_seconds,
            )
        except TransportError as error:
            # Not retried: the nonce has been spent and the ±5 minute window is
            # already running, so a blind retry of the same signed request
            # could be refused as a replay. The caller retries the call, which
            # signs afresh.
            raise ApiError(f"Token request failed: {error}") from error

        body = response.json()
        if not response.ok:
            message = _message_of(body) or f"Authentication failed (HTTP {response.status_code})."
            error_kwargs: Dict[str, Any] = {
                "status_code": response.status_code,
                "code": _code_of(body),
                "response": body,
                "request_id": response.header("x-request-id"),
            }
            if response.status_code in (401, 403):
                raise AuthenticationError(message, **error_kwargs)
            raise ApiError(message, **error_kwargs)

        token = _read_token(body)
        if token is None:
            raise ApiError(
                "The authentication response carried no access token.",
                status_code=response.status_code,
                response=body,
                request_id=response.header("x-request-id"),
            )
        return token, _read_ttl(body)


def _read_token(body: Mapping[str, Any]) -> Optional[str]:
    """Reads the access token from the envelope or from a plain body.

    ``POST /api/v1/auth/token`` answers ``access_token`` (snake_case, OAuth
    style) while the rest of the gateway is camelCase, and the response may or
    may not be wrapped in the standard envelope depending on deployment. Both
    spellings and both shapes are read here so a caller never has to care.
    """
    for source in (body, data_of(body)):
        if not isinstance(source, Mapping):
            continue
        for key in ("access_token", "accessToken", "token"):
            value = source.get(key)
            if isinstance(value, str) and value != "":
                return value
    return None


def _read_ttl(body: Mapping[str, Any]) -> int:
    for source in (body, data_of(body)):
        if not isinstance(source, Mapping):
            continue
        for key in ("expires_in", "expiresIn"):
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, (float, str)):
                try:
                    return int(float(value))
                except ValueError:
                    continue
    return _DEFAULT_TTL_SECONDS


def _message_of(body: Mapping[str, Any]) -> Optional[str]:
    message = body.get("message") if isinstance(body, Mapping) else None
    return message if isinstance(message, str) and message != "" else None


def _code_of(body: Mapping[str, Any]) -> Optional[str]:
    code = body.get("code") if isinstance(body, Mapping) else None
    return code if isinstance(code, str) and code != "" else None
