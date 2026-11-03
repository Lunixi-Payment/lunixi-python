"""Verifying and reading a physical POS webhook.

:func:`parse_webhook_event` takes the RAW request body, the request headers
and your endpoint secret (or a configured
:class:`~lunixi.webhook.verifier.WebhookVerifier`), checks the signature with
the platform verifier and only then reads the event. There is no way to read
an envelope that was not verified here:

.. code-block:: python

    event = parse_webhook_event(raw_body, request.headers, secret)
    if event.type == PhysicalPosEvents.PAYMENT_APPROVED:
        ...

The payload is the envelope's ``data``. An envelope that carries it under
``payloadJson`` instead (an object, or that object as a JSON string) is read
from there.

⚠️ Delivery order is not guaranteed and an event can arrive more than once.
Deduplicate on :attr:`PhysicalPosWebhookEvent.id`, and ignore an event whose
``history_seq`` is not greater than the last one you applied for the same
``paymentId``. When in doubt, read the payment with ``get_payment``.

Amounts in webhook payloads are minor-unit STRINGS (``"4500"``); the HTTP API
also returns canonical minor-unit strings.

End-of-day events (``physical_pos.settlement.*``, category ``"settlement"``)
carry their own payload and no ``historySeq``; deduplicate them on the id.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from ..errors import ConfigurationError, WebhookVerificationError
from ..webhook.verifier import WebhookVerifier

__all__ = [
    "PhysicalPosWebhookEvent",
    "parse_webhook_event",
    "webhook_cashier",
    "webhook_category",
    "webhook_original",
]

_PREFIX = "physical_pos."
_DEVICE_SALE = "physical_pos.payment.device_sale"


class PhysicalPosWebhookEvent:
    """One physical POS webhook.

    Attributes:
        id: Event id — the same transition always carries the same id.
        type: ``physical_pos.payment.*``, ``physical_pos.fiscal_document.*``
            or ``physical_pos.settlement.*``.
        category: ``"payment"``, ``"fiscal_document"``, ``"settlement"`` or
            ``"other"`` (a type a later release may add).
        environment: ``"LIVE"`` or ``"TEST"`` when present.
        created_at: When the transition happened (ISO-8601), when present.
        history_seq: The payment's / document's ``historySeq``, or ``None``.
        original: A reversal's original payment ``{"paymentId", "origin"}``
            (``origin``: ``"API"`` or ``"DEVICE_DIRECT"``), ``None`` on a root.
        cashier: ``{"cashierId", "cashierCode"}`` for a payment started from
            a device cashier session, ``None`` otherwise (the key is absent).
        is_device_sale: ``True`` for ``physical_pos.payment.device_sale`` (a
            sale made directly on the device; ``data`` also carries
            ``origin`` and ``deviceOccurredAt``).
        data: The payload.
        raw: The whole envelope.
    """

    __slots__ = (
        "id",
        "type",
        "category",
        "environment",
        "created_at",
        "history_seq",
        "original",
        "cashier",
        "is_device_sale",
        "data",
        "raw",
    )

    def __init__(
        self,
        *,
        id: Optional[str],  # noqa: A002 - matches the envelope field name
        type: str,  # noqa: A002 - matches the envelope field name
        category: str,
        environment: Optional[str],
        created_at: Optional[str],
        history_seq: Optional[int],
        data: Dict[str, Any],
        raw: Mapping[str, Any],
    ) -> None:
        self.id = id
        self.type = type
        self.category = category
        self.environment = environment
        self.created_at = created_at
        self.history_seq = history_seq
        self.original = webhook_original(data)
        self.cashier = webhook_cashier(data)
        self.is_device_sale = type == _DEVICE_SALE
        self.data = data
        self.raw = raw

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return f"PhysicalPosWebhookEvent(id={self.id!r}, type={self.type!r})"


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value != "" else None


def webhook_original(data: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """The original payment of a reversal payload.

    ``{"paymentId": ..., "origin": ...}`` when ``data["original"]`` carries
    both as non-empty strings (other keys are dropped); otherwise ``None`` (a
    root payment).
    """
    original = data.get("original") if isinstance(data, Mapping) else None
    if not isinstance(original, Mapping):
        return None
    payment_id = _text(original.get("paymentId"))
    origin = _text(original.get("origin"))
    if payment_id is None or origin is None:
        return None
    return {"paymentId": payment_id, "origin": origin}


def webhook_cashier(data: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """The cashier of a payment payload.

    ``{"cashierId": ..., "cashierCode": ...}`` when ``data["cashier"]``
    carries both as non-empty strings (other keys are dropped); otherwise
    ``None`` (no cashier session).
    """
    cashier = data.get("cashier") if isinstance(data, Mapping) else None
    if not isinstance(cashier, Mapping):
        return None
    cashier_id = _text(cashier.get("cashierId"))
    cashier_code = _text(cashier.get("cashierCode"))
    if cashier_id is None or cashier_code is None:
        return None
    return {"cashierId": cashier_id, "cashierCode": cashier_code}


def webhook_category(event_type: str) -> str:
    """``"payment"``, ``"fiscal_document"``, ``"settlement"`` or ``"other"``."""
    if event_type.startswith(_PREFIX + "payment."):
        return "payment"
    if event_type.startswith(_PREFIX + "fiscal_document."):
        return "fiscal_document"
    if event_type.startswith(_PREFIX + "settlement."):
        return "settlement"
    return "other"


def _payload(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    data = envelope.get("data")
    if isinstance(data, Mapping) and data:
        return dict(data)
    carried = envelope.get("payloadJson")
    if isinstance(carried, str):
        try:
            carried = json.loads(carried)
        except (ValueError, RecursionError) as error:
            raise WebhookVerificationError(
                "The physical POS payloadJson is not valid JSON."
            ) from error
    if isinstance(carried, Mapping) and carried:
        return dict(carried)
    raise WebhookVerificationError("The physical POS webhook carries no payload.")


def parse_webhook_event(
    raw_body: "str | bytes",
    headers: Mapping[str, Any],
    secret_or_verifier: "str | list[str] | WebhookVerifier",
    *,
    tolerance_seconds: Optional[int] = 300,
) -> PhysicalPosWebhookEvent:
    """Verifies a physical POS webhook and reads it.

    Args:
        raw_body: The exact raw request body (bytes or the undecoded string).
        headers: The request headers (``x-lunixi-signature`` …).
        secret_or_verifier: Your endpoint secret (or up to five rotating
            secrets), or a configured :class:`WebhookVerifier`.
        tolerance_seconds: Replay window used when a secret is given; ignored
            when you pass a verifier (it carries its own).

    Raises:
        WebhookVerificationError: when the signature, timestamp or event
            identity does not verify, the type is not a physical POS type, or
            the envelope carries no payload.
        ConfigurationError: when neither a secret nor a verifier is given.
    """
    if isinstance(secret_or_verifier, WebhookVerifier):
        verifier = secret_or_verifier
    elif isinstance(secret_or_verifier, (str, list)):
        verifier = WebhookVerifier(secret_or_verifier, tolerance_seconds=tolerance_seconds)
    else:
        raise ConfigurationError("Pass your webhook secret or a WebhookVerifier.")
    verified = verifier.verify(raw_body, headers)
    envelope: Mapping[str, Any] = verified.raw

    event_type = _text(envelope.get("type")) or _text(envelope.get("eventType")) or verified.type
    if not isinstance(event_type, str) or not event_type.startswith(_PREFIX):
        raise WebhookVerificationError("This webhook is not a physical POS event.")
    data = _payload(envelope)
    from .money import validate_response_money

    validate_response_money(data)
    category = webhook_category(event_type)
    seq = data.get("historySeq")
    return PhysicalPosWebhookEvent(
        id=_text(envelope.get("id")) or _text(envelope.get("eventId")) or verified.id,
        type=event_type,
        category=category,
        environment=_text(envelope.get("environment")),
        created_at=_text(envelope.get("createdAt"))
        or _text(envelope.get("occurredAt"))
        or _text(envelope.get("timestamp")),
        history_seq=seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        data=data,
        raw=envelope,
    )
