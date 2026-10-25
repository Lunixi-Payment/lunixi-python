"""Typed error hierarchy.

Every failure raised by this package derives from :class:`LunixiError`, so one
``except LunixiError`` clause catches the whole SDK and nothing else.

Split by WHO can fix the failure:

* :class:`ConfigurationError` / :class:`SignatureError` — raised locally,
  before anything is sent. The caller's own code or key material is wrong.
* :class:`ApiError` and its subclasses — the gateway answered and refused. The
  HTTP status decides which subclass, so a caller can branch on the class
  instead of parsing a status code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = [
    "LunixiError",
    "ConfigurationError",
    "SignatureError",
    "WebhookVerificationError",
    "ApiError",
    "ValidationError",
    "AuthenticationError",
    "RateLimitError",
    "ServiceUnavailableError",
]


class LunixiError(Exception):
    """Base class for every error this package raises."""


class ConfigurationError(LunixiError):
    """A local argument or configuration value is unusable.

    Raised before any network call — nothing was sent.
    """


class SignatureError(LunixiError):
    """The Ed25519 private key could not be loaded, or signing failed."""


class WebhookVerificationError(LunixiError):
    """An inbound webhook did not verify.

    Verification is fail-closed: act on a payload only when ``verify`` returned
    without raising.
    """


class ApiError(LunixiError):
    """The gateway answered with a non-2xx status.

    Attributes:
        status_code: HTTP status, or ``0`` when the request never completed.
        code: Machine-readable code from the response envelope, when present.
        message: Human-readable message.
        response: The decoded response body, when it was JSON.
        request_id: Correlation id from the ``X-Request-Id`` header — quote it
            in a support request.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.response = response
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - formatting only
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.status_code:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"requestId={self.request_id}")
        return " ".join(parts)


class ValidationError(ApiError):
    """400 — the gateway rejected the request body.

    The fraud surface raises this for a declared value outside its dictionary:
    a ``channel`` outside the externally declarable set, an ``integration_mode``
    other than ``standalone``, or a ``product_context`` reserved for the
    platform's own senders. ``code`` carries the gateway error code.
    """


class AuthenticationError(ApiError):
    """401 — signature, key id, timestamp window or nonce was refused.

    A single retry after refreshing the access token is already attempted
    inside the client; this error means the retry was refused as well.
    """


class RateLimitError(ApiError):
    """429 — the request quota is exhausted.

    Attributes:
        retry_after: Seconds from the ``Retry-After`` header, or ``None`` when
            the gateway did not send one.
        quota: The ``X-RateLimit-*`` / ``X-Quota-*`` header values when
            present. The gateway omits a header rather than guessing, so any
            individual field may be ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[int] = None,
        quota: Optional[Dict[str, Optional[int]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.quota = quota


class ServiceUnavailableError(ApiError):
    """503 — the service, or the backend its quota check needs, is unavailable.

    Carries ``retry_after`` when the gateway sent a ``Retry-After`` header.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[int] = None,
        quota: Optional[Dict[str, Optional[int]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.quota = quota
