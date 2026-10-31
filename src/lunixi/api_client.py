"""The authenticated request path: headers, retries, error mapping.

Every feature client goes through :meth:`ApiClient.request`, so the signing
rules, the retry policy and the status-to-exception mapping exist in exactly
one place.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping, Optional

from .auth.canonical_request import (
    HEADER_DATE,
    HEADER_DIGEST,
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    build_canonical_request,
    digest_for_body,
)
from .auth.ed25519_signer import Ed25519Signer
from .auth.token_manager import TokenManager, new_nonce, utc_timestamp
from .configuration import Configuration
from .errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from .http.transport import TransportError, build_path, serialize_body
from .validation import header_value

__all__ = ["ApiClient"]

_JSON_ACCEPT = "application/json"
_MAX_BACKOFF_SECONDS = 2.0
_QUOTA_HEADERS = {
    "rate_limit": "x-ratelimit-limit",
    "rate_remaining": "x-ratelimit-remaining",
    "rate_reset": "x-ratelimit-reset",
    "daily_limit": "x-quota-limit",
    "daily_remaining": "x-quota-remaining",
    "daily_reset": "x-quota-reset",
}


class ApiClient:
    """Sends authenticated gateway requests.

    Two authentication levels exist and they are not interchangeable:

    * **Bearer only** (default) — the access token. This covers the decision
      and decision-log routes.
    * **Bearer plus a per-request Ed25519 signature** (``step_up=True``) — adds
      ``X-Key-Id``, ``X-Date``, ``X-Nonce``, ``X-Signature`` and, when a body
      is present, ``Digest``. The event-ingest routes accept nothing less: the
      signature is what binds an event to your account, so a body value cannot
      claim a different one. Calling such a route without ``step_up`` fails
      with a 401.
    """

    def __init__(
        self,
        config: Configuration,
        signer: Ed25519Signer,
        token_manager: TokenManager,
    ) -> None:
        self._config = config
        self._signer = signer
        self._tokens = token_manager

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        query: Optional[Mapping[str, Any]] = None,
        step_up: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends one request and returns the decoded response envelope.

        The envelope is returned whole rather than unwrapped, so a caller that
        needs ``pageInfo`` (a sibling of ``data``) or ``requestId`` can reach
        them. Use :mod:`lunixi.http.envelope` to read it.

        Args:
            method: HTTP method.
            path: Gateway path INCLUDING the ``/api/v1`` prefix.
            body: Any JSON-serializable value, or ``None``.
            query: Query parameters; empty values are dropped.
            step_up: Adds the per-request Ed25519 signature.
            idempotency_key: Value for the ``Idempotency-Key`` header. Supplying
                one also makes the request eligible for automatic retry.

        Raises:
            ValidationError: on 400.
            AuthenticationError: on 401 or 403, after one token refresh.
            RateLimitError: on 429.
            ServiceUnavailableError: on 503.
            ApiError: on any other non-2xx status, or when no response arrived.
        """
        if not isinstance(method, str) or method.upper() not in (
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        ):
            raise ConfigurationError("Unsupported HTTP method.")
        if idempotency_key is not None:
            header_value(idempotency_key, "idempotency_key")
        if (
            isinstance(body, Mapping)
            and path.startswith("/api/v1/payments/")
            and method.upper() == "POST"
            and ("price" in body or "paidPrice" in body)
        ):
            raise ConfigurationError("Removed amount fields are not accepted; use amount.")
        financial = path.split("?", 1)[0]
        financial_write = method.upper() == "POST" and (
            financial
            in (
                "/api/v1/payments/intents",
                "/api/v1/payments/direct/payment",
                "/api/v1/payments/split",
            )
            or (
                financial.startswith("/api/v1/payments/")
                and financial.endswith(("/capture", "/refund", "/void"))
            )
        )
        if financial_write and idempotency_key is None:
            raise ConfigurationError(
                "A stable idempotency_key is required for a financial mutation."
            )
        amount_route = financial in (
            "/api/v1/payments/intents",
            "/api/v1/payments/direct/payment",
        ) or (
            financial.startswith("/api/v1/payments/")
            and financial.endswith(("/capture", "/refund"))
        )
        if financial_write and amount_route:
            from .validation import amount_minor

            if not isinstance(body, Mapping):
                raise ConfigurationError("Financial mutation requires an integer amount body.")
            amount_minor(body.get("amount"))
        upper_method = method.upper()
        signed_path = build_path(path, query)
        url = self._config.url_for(signed_path)
        raw_body = serialize_body(body)

        # 🔴 A write is retried ONLY with an idempotency key. Replaying an
        # unkeyed POST after a timeout can record the same event twice, and the
        # SDK cannot tell a lost request from a lost response.
        retryable = upper_method in ("GET", "HEAD") or idempotency_key is not None

        reauthenticated = False
        attempt = 0
        while True:
            attempt += 1
            headers = self._build_headers(
                upper_method, signed_path, raw_body, step_up, idempotency_key
            )

            try:
                response = self._config.transport.send(
                    upper_method, url, headers, raw_body, self._config.timeout_seconds
                )
            except TransportError:
                if retryable and attempt <= self._config.max_retries:
                    _backoff(attempt)
                    continue
                raise ApiError("Gateway request failed without a confirmed response.") from None

            if len(response.body) > self._config.max_response_bytes:
                raise ApiError("Gateway response exceeds the configured limit.")
            if response.ok:
                return response.json()

            # One refresh-and-retry for an expired token. Bounded by the flag:
            # a second 401 is the account's answer, not a stale cache.
            if response.status_code == 401 and not reauthenticated and retryable:
                self._tokens.invalidate()
                reauthenticated = True
                continue

            if response.status_code >= 500 and retryable and attempt <= self._config.max_retries:
                _backoff(attempt)
                continue

            raise _to_api_error(response)

    def _build_headers(
        self,
        method: str,
        signed_path: str,
        raw_body: Optional[str],
        step_up: bool,
        idempotency_key: Optional[str],
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": _JSON_ACCEPT,
            "User-Agent": self._config.user_agent,
            "Authorization": f"Bearer {header_value(self._tokens.get_token(), 'access_token', 8192)}",
        }
        if raw_body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        if step_up:
            date = utc_timestamp()
            nonce = new_nonce()
            digest = digest_for_body(raw_body)
            canonical = build_canonical_request(method, signed_path, date, nonce, digest)

            headers[HEADER_KEY_ID] = self._config.key_id
            headers[HEADER_DATE] = date
            headers[HEADER_NONCE] = nonce
            headers[HEADER_SIGNATURE] = self._signer.sign(canonical)
            if digest:
                headers[HEADER_DIGEST] = digest

        return headers


def _read_quota(response: Any) -> Optional[Dict[str, Optional[int]]]:
    """Reads the quota headers, which are stamped on 429 and 503 only.

    The gateway omits a header rather than guessing its value, so every field
    may be ``None``; the whole dict is ``None`` when no header was sent.
    """
    quota = {name: response.int_header(header) for name, header in _QUOTA_HEADERS.items()}
    return quota if any(value is not None for value in quota.values()) else None


def _to_api_error(response: Any) -> ApiError:
    body = response.json()
    message = f"Gateway request failed (HTTP {response.status_code}); response content withheld."
    code = body.get("code")

    kwargs: Dict[str, Any] = {
        "status_code": response.status_code,
        "code": code if isinstance(code, str) and code != "" else None,
        "response": None,
        "request_id": response.header("x-request-id"),
    }

    if response.status_code == 400:
        return ValidationError(message, **kwargs)
    if response.status_code in (401, 403):
        return AuthenticationError(message, **kwargs)
    if response.status_code in (429, 503):
        kwargs["retry_after"] = response.int_header("retry-after")
        kwargs["quota"] = _read_quota(response)
        if response.status_code == 429:
            return RateLimitError(message, **kwargs)
        return ServiceUnavailableError(message, **kwargs)
    return ApiError(message, **kwargs)


def _backoff(attempt: int) -> None:
    time.sleep(min(_MAX_BACKOFF_SECONDS, 0.1 * (2 ** (attempt - 1))))
