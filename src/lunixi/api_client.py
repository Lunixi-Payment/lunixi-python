"""The authenticated request path: headers, retries, error mapping.

Every feature client goes through :meth:`ApiClient.request`, so the signing
rules, the retry policy and the status-to-exception mapping exist in exactly
one place.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

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
from .http.transport import HttpResponse, TransportError, build_path, serialize_body
from .validation import header_value

__all__ = ["ApiClient", "BinaryResponse"]

_JSON_ACCEPT = "application/json"
_BINARY_ACCEPT = "application/pdf, application/json"
_FIAT_BASES = (
    "/api/v1/payments",
    "/api/v1/wallet",
    "/api/v1/insurance",
    "/api/v1/bank-connect",
    "/api/v1/fraud",
)


@dataclass(frozen=True)
class BinaryResponse:
    """A 2xx answer that is a file (a PDF document), not the JSON envelope.

    ``content_type`` is the response's ``Content-Type`` header (``None`` when
    absent); ``content`` the raw body bytes.
    """

    content_type: Optional[str]
    content: bytes = field(repr=False)


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

    @property
    def max_retries(self) -> int:
        """The configured number of extra attempts for a retryable request."""
        return self._config.max_retries

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        query: Optional[Mapping[str, Any]] = None,
        step_up: bool = False,
        idempotency_key: Optional[str] = None,
        max_retries: Optional[int] = None,
        result_on_error: Optional[Callable[[int, Dict[str, Any]], bool]] = None,
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
            max_retries: Extra attempts for this request only; ``None`` (the
                default) uses the configured value. ``0`` sends exactly once,
                for a caller that runs its own attempt loop.
            result_on_error: Optional predicate over ``(status_code, body)`` of
                a non-2xx answer. When it returns ``True`` the decoded body is
                returned instead of raised — for a route whose documented
                non-2xx answer is a result (a split payment that is still
                running). Every other non-2xx answer raises as usual.

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
            if "amount" in body or financial.endswith(("/intents", "/direct/payment")):
                amount_minor(body.get("amount"))
        retry_limit = self._retry_limit(max_retries)
        upper_method = method.upper()
        signed_path = build_path(path, query)
        url = self._config.url_for(signed_path)
        from .validation import validate_money_fields

        fiat_route = _is_fiat_route(path)
        if fiat_route:
            validate_money_fields(body)
            validate_money_fields(query)
        raw_body = serialize_body(body)

        response = self._exchange(
            upper_method,
            url,
            signed_path,
            raw_body,
            step_up,
            idempotency_key,
            retry_limit,
            _JSON_ACCEPT,
            result_on_error,
        )
        result = response.json()
        if fiat_route:
            validate_money_fields(result, response=True)
        return result

    def request_binary(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        step_up: bool = False,
        accept: str = _BINARY_ACCEPT,
        max_retries: Optional[int] = None,
    ) -> BinaryResponse:
        """Sends one ``GET`` whose 2xx answer is a file and returns its bytes.

        The same signing, retry, size limit and error mapping as
        :meth:`request`; an error answer is still read as the JSON envelope and
        raised. ``accept`` is the ``Accept`` header (not part of the signature).
        """
        if not isinstance(method, str) or method.upper() != "GET":
            raise ConfigurationError("A binary request is a GET.")
        header_value(accept, "accept")
        retry_limit = self._retry_limit(max_retries)
        signed_path = build_path(path, query)
        url = self._config.url_for(signed_path)
        if _is_fiat_route(path):
            from .validation import validate_money_fields

            validate_money_fields(query)
        response = self._exchange(
            "GET", url, signed_path, None, step_up, None, retry_limit, accept, None
        )
        return BinaryResponse(response.header("content-type"), response.body)

    def _retry_limit(self, max_retries: Optional[int]) -> int:
        if max_retries is not None and (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 5
        ):
            raise ConfigurationError("max_retries must be an integer from 0 to 5.")
        return self._config.max_retries if max_retries is None else max_retries

    def _exchange(
        self,
        upper_method: str,
        url: str,
        signed_path: str,
        raw_body: Optional[str],
        step_up: bool,
        idempotency_key: Optional[str],
        retry_limit: int,
        accept: str,
        result_on_error: Optional[Callable[[int, Dict[str, Any]], bool]],
    ) -> HttpResponse:
        """The attempt loop: returns a 2xx response (or an accepted error answer), else raises."""
        # 🔴 A write is retried ONLY with an idempotency key. Replaying an
        # unkeyed POST after a timeout can record the same event twice, and the
        # SDK cannot tell a lost request from a lost response.
        retryable = upper_method in ("GET", "HEAD") or idempotency_key is not None

        reauthenticated = False
        attempt = 0
        while True:
            attempt += 1
            headers = self._build_headers(
                upper_method, signed_path, raw_body, step_up, idempotency_key, accept
            )

            try:
                response = self._config.transport.send(
                    upper_method, url, headers, raw_body, self._config.timeout_seconds
                )
            except TransportError:
                if retryable and attempt <= retry_limit:
                    _backoff(attempt)
                    continue
                raise ApiError("Gateway request failed without a confirmed response.") from None

            if len(response.body) > self._config.max_response_bytes:
                raise ApiError("Gateway response exceeds the configured limit.")
            if response.ok:
                return response

            # One refresh-and-retry for an expired token. Bounded by the flag:
            # a second 401 is the account's answer, not a stale cache.
            if response.status_code == 401 and not reauthenticated and retryable:
                self._tokens.invalidate()
                reauthenticated = True
                continue

            if response.status_code >= 500 and retryable and attempt <= retry_limit:
                _backoff(attempt)
                continue

            if result_on_error is not None and result_on_error(
                response.status_code, response.json()
            ):
                return response

            raise _to_api_error(response)

    def _build_headers(
        self,
        method: str,
        signed_path: str,
        raw_body: Optional[str],
        step_up: bool,
        idempotency_key: Optional[str],
        accept: str = _JSON_ACCEPT,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": accept,
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


def _is_fiat_route(path: str) -> bool:
    return any(path == base or path.startswith(base + "/") for base in _FIAT_BASES)


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
        "details": _safe_details(body.get("details")),
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


#: ``details`` keys kept on an error: machine-readable, never a submitted value.
_DETAIL_KEYS = ("field", "reason", "retryable", "retryAfterSeconds", "allowedOperation")


def _safe_details(details: Any) -> Optional[Dict[str, Any]]:
    """The scalar, value-free part of an error's ``details`` (field path, reason, retry hints)."""
    if not isinstance(details, Mapping):
        return None
    kept: Dict[str, Any] = {}
    for key in _DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, bool) or (isinstance(value, int) and 0 <= value <= 86400 * 31):
            kept[key] = value
        elif isinstance(value, str) and 0 < len(value) <= 200 and value.isprintable():
            kept[key] = value
    return kept or None


def _backoff(attempt: int) -> None:
    time.sleep(min(_MAX_BACKOFF_SECONDS, 0.1 * (2 ** (attempt - 1))))
