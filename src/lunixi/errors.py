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
    "PhysicalPosCardDataRejectedError",
    "PhysicalPosRateLimitError",
    "PhysicalPosOutcomeUnknownError",
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
        details: The machine-readable part of the error's ``details`` —
            only ``field``, ``reason``, ``retryable``,
            ``retryAfterSeconds`` and ``allowedOperation`` when the gateway
            sent them (a field PATH, never a value), else ``None``.
        idempotency_key: The ``Idempotency-Key`` the failed write was sent
            with, when the client that raised it knows it. Retry the same
            operation with this key.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.response = response
        self.request_id = request_id
        self.details = details
        self.idempotency_key = idempotency_key

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


class PhysicalPosCardDataRejectedError(ValidationError):
    """A physical POS request carried card data — ``physical_pos.payment.card_data_rejected``.

    The API never takes a card number, security code, track, PIN or expiry:
    the card is read on the device. Raised before sending when a request or
    filter key looks like card data (``status_code`` 0 — nothing was sent), and
    when the gateway answers with this code (``status_code`` 400, for example
    a card number inside ``merchantReference``).

    Attributes:
        field: Path of the offending field (``items[1].name``, ``target.pan``);
            the value is never repeated.
    """

    CODE = "physical_pos.payment.card_data_rejected"

    def __init__(self, message: str, *, field: Optional[str] = None, **kwargs: Any) -> None:
        kwargs.setdefault("code", self.CODE)
        super().__init__(message, **kwargs)
        self.field = field


class PhysicalPosRateLimitError(RateLimitError):
    """429 on a physical POS route (payment writes are limited per key).

    ``retry_after`` is the ``Retry-After`` header, falling back to
    ``details.retryAfterSeconds``. Wait that long; a payment write may be
    repeated with the same ``idempotency_key``.
    """


class PhysicalPosVoidAfterSettlementError(ApiError):
    """409 ``physical_pos.payment.void_after_settlement`` — the payment is in a device end-of-day.

    It can no longer be voided: return the amount with a ``REFUND`` reversal
    on the same payment (with a new idempotency key).

    Attributes:
        allowed_operation: ``details.allowedOperation`` (``"REFUND"``), or
            ``None`` when the answer did not carry it.
    """

    CODE = "physical_pos.payment.void_after_settlement"

    def __init__(self, message: str, *, allowed_operation: Optional[str] = None, **kwargs: Any) -> None:
        kwargs.setdefault("code", self.CODE)
        super().__init__(message, **kwargs)
        self.allowed_operation = allowed_operation


class PhysicalPosOutcomeUnknownError(ApiError):
    """A payment write got no definite answer — the payment may or may not exist.

    Raised by ``create_payment``, ``create_reversal`` and ``cancel_payment``
    when any attempt of the call was uncertain: no HTTP answer (network,
    timeout, a body that could not be read), a 2xx without a usable
    ``payment``, or a 5xx without a "not started" code
    (``PHYSICAL_POS_NOT_STARTED_CODES``). Once one attempt was uncertain the
    call ends with this error whatever the last answer was — a later 429 or
    409 included — because the payment may exist under the key. The cause is
    the last error. Retry the SAME operation with
    :attr:`idempotency_key` — never with a new key, which can start a second
    payment — or find it with ``list_payments(merchant_reference=...)``.

    Attributes:
        retry_after: ``Retry-After`` seconds when the gateway sent one.
    """

    def __init__(self, message: str, *, retry_after: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
