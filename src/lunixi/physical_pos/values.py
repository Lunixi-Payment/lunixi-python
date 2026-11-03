"""Physical POS value sets, webhook event types and request field lists.

The value classes are informative: every set is open on the wire (a later
gateway release may add a value), so the SDK never rejects a value it does not
list here. Decide on ``paymentStatus`` and ignore what you do not recognise.

The field lists are the gateway DTOs of ``/api/v1/physical-pos``. The gateway
rejects an undeclared body or query field with 400, so the SDK checks them
before anything is sent.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

__all__ = [
    "PhysicalPosEvents",
    "PHYSICAL_POS_EVENT_PATTERN",
    "PHYSICAL_POS_EVENT_TYPES",
    "PhysicalPosPaymentOperation",
    "PhysicalPosPaymentStatus",
    "PhysicalPosReversalStatus",
    "IDEMPOTENCY_KEY_PATTERN",
    "PAYMENT_FIELDS",
    "PAYMENT_TARGET_FIELDS",
    "SALE_ITEM_FIELDS",
    "REVERSAL_FIELDS",
    "REFUND_ITEM_FIELDS",
    "PHYSICAL_POS_FILTERS",
]


class PhysicalPosEvents:
    """Physical POS webhook event types, in catalogue order.

    Delivered in the signed platform envelope; verify with
    :class:`~lunixi.webhook.verifier.WebhookVerifier`, then read with
    :func:`~lunixi.physical_pos.webhook.parse_webhook_event`. Reversals (void,
    refund, pre-authorisation close) use the same payment events; tell them
    apart with ``operation`` and ``rootPaymentId``, and the original payment's
    source with ``original.origin``
    (:attr:`~lunixi.physical_pos.webhook.PhysicalPosWebhookEvent.original`).

    ``PAYMENT_DEVICE_SALE`` reports a sale made directly on the device
    (``origin: "DEVICE_DIRECT"``): it arrives approved with
    ``deviceOccurredAt``; no ``approved`` event is sent for it. Its refund
    comes with the usual payment events (``original.origin`` =
    ``"DEVICE_DIRECT"``).

    End-of-day events (``SETTLEMENT_*``) have their own payloads:
    ``COMPLETED`` (the device's result with its bank lines; any source),
    ``FAILED`` (a scheduled run could not finish in its window), ``OVERDUE``
    (no result within the policy's threshold) and ``SKIPPED`` (a scheduled run
    was skipped for a reason you can fix). They carry no ``historySeq``:
    deduplicate them on the event id.
    """

    PAYMENT_APPROVED = "physical_pos.payment.approved"
    PAYMENT_PARTIALLY_APPROVED = "physical_pos.payment.partially_approved"
    PAYMENT_DECLINED = "physical_pos.payment.declined"
    PAYMENT_CANCELLED = "physical_pos.payment.cancelled"
    #: Never started: the start window passed or you cancelled before dispatch.
    PAYMENT_EXPIRED = "physical_pos.payment.expired"
    #: Never started: the device or the service rejected the command.
    PAYMENT_FAILED = "physical_pos.payment.failed"
    #: The outcome is not known yet and money may have been taken. Do NOT
    #: charge again; the outcome is being verified.
    PAYMENT_UNKNOWN = "physical_pos.payment.unknown"
    PAYMENT_MANUAL_REVIEW = "physical_pos.payment.manual_review"
    #: A sale made directly on the device, recorded already approved.
    PAYMENT_DEVICE_SALE = "physical_pos.payment.device_sale"
    FISCAL_DOCUMENT_ISSUED = "physical_pos.fiscal_document.issued"
    FISCAL_DOCUMENT_FAILED = "physical_pos.fiscal_document.failed"
    FISCAL_DOCUMENT_CANCELLED = "physical_pos.fiscal_document.cancelled"
    FISCAL_DOCUMENT_ACTION_REQUIRED = "physical_pos.fiscal_document.action_required"
    SETTLEMENT_COMPLETED = "physical_pos.settlement.completed"
    SETTLEMENT_FAILED = "physical_pos.settlement.failed"
    SETTLEMENT_OVERDUE = "physical_pos.settlement.overdue"
    SETTLEMENT_SKIPPED = "physical_pos.settlement.skipped"


#: Subscription pattern covering every physical POS event.
PHYSICAL_POS_EVENT_PATTERN = "physical_pos.*"

#: Every physical POS webhook event type, in catalogue order.
PHYSICAL_POS_EVENT_TYPES: Tuple[str, ...] = (
    PhysicalPosEvents.PAYMENT_APPROVED,
    PhysicalPosEvents.PAYMENT_PARTIALLY_APPROVED,
    PhysicalPosEvents.PAYMENT_DECLINED,
    PhysicalPosEvents.PAYMENT_CANCELLED,
    PhysicalPosEvents.PAYMENT_EXPIRED,
    PhysicalPosEvents.PAYMENT_FAILED,
    PhysicalPosEvents.PAYMENT_UNKNOWN,
    PhysicalPosEvents.PAYMENT_MANUAL_REVIEW,
    PhysicalPosEvents.PAYMENT_DEVICE_SALE,
    PhysicalPosEvents.FISCAL_DOCUMENT_ISSUED,
    PhysicalPosEvents.FISCAL_DOCUMENT_FAILED,
    PhysicalPosEvents.FISCAL_DOCUMENT_CANCELLED,
    PhysicalPosEvents.FISCAL_DOCUMENT_ACTION_REQUIRED,
    PhysicalPosEvents.SETTLEMENT_COMPLETED,
    PhysicalPosEvents.SETTLEMENT_FAILED,
    PhysicalPosEvents.SETTLEMENT_OVERDUE,
    PhysicalPosEvents.SETTLEMENT_SKIPPED,
)


class PhysicalPosPaymentOperation:
    """``operation`` values. The first three start a payment, the rest reverse one."""

    SALE = "SALE"
    PREAUTH_OPEN = "PREAUTH_OPEN"
    REFUND_UNMATCHED = "REFUND_UNMATCHED"
    VOID = "VOID"
    REFUND = "REFUND"
    PREAUTH_CLOSE = "PREAUTH_CLOSE"
    PREAUTH_CANCEL = "PREAUTH_CANCEL"


class PhysicalPosPaymentStatus:
    """``paymentStatus`` values.

    ``APPROVED`` and ``PARTIALLY_APPROVED`` mean money was taken. ``UNKNOWN``
    means it may have been: never start the payment again with a new key.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class PhysicalPosReversalStatus:
    """``reversalStatus`` values of a root payment."""

    NONE = "NONE"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"
    PREAUTH_CLOSED = "PREAUTH_CLOSED"
    PREAUTH_CANCELLED = "PREAUTH_CANCELLED"
    PREAUTH_EXPIRED = "PREAUTH_EXPIRED"


#: ``Idempotency-Key``: 8–200 printable ASCII characters without spaces.
IDEMPOTENCY_KEY_PATTERN = r"[\x21-\x7E]{8,200}"

PAYMENT_FIELDS: Tuple[str, ...] = (
    "operation",
    "target",
    "amountMinor",
    "currency",
    "installmentCount",
    "instrument",
    "merchantReference",
    "allowDuplicateReference",
    "startTimeoutSeconds",
    "terminalAcquirerId",
    "items",
    "interaction",
    "terminalProviderId",
)
PAYMENT_TARGET_FIELDS: Tuple[str, ...] = ("deviceId", "vendorCode", "serialNumber", "externalRef")
SALE_ITEM_FIELDS: Tuple[str, ...] = (
    "lineNo",
    "name",
    "quantityMilli",
    "unitCode",
    "unitPriceMinor",
    "taxGroupCode",
    "lineTotalMinor",
    "barcode",
)
REVERSAL_FIELDS: Tuple[str, ...] = (
    "operation",
    "amountMinor",
    "currency",
    "merchantReference",
    "startTimeoutSeconds",
    "target",
    "items",
)
REFUND_ITEM_FIELDS: Tuple[str, ...] = ("lineNo", "quantityMilli", "amountMinor")

_PAGE = ("limit", "cursor")
_ENTITY_PAGE = ("limit", "cursor", "includeTotal")
_REPORT = ("dateFrom", "dateTo", "deviceId", "storeId")

#: Query fields per list / report route (wire names).
PHYSICAL_POS_FILTERS: Dict[str, Tuple[str, ...]] = {
    "list_payments": _PAGE
    + ("deviceId", "paymentStatus", "createdFrom", "createdTo", "merchantReference"),
    "list_transactions": _PAGE
    + (
        "deviceId",
        "storeId",
        "registerId",
        "paymentStatus",
        "createdFrom",
        "createdTo",
        "merchantReference",
        "amountFromMinor",
        "amountToMinor",
        "origin",
        "operation",
    ),
    "list_ambiguous_payments": _PAGE + ("deviceId", "paymentStatus"),
    "get_sales_summary": _REPORT + ("groupBy",),
    "get_tax_summary": _REPORT,
    "list_settlements": _PAGE + ("deviceId", "lineStatus", "createdFrom", "createdTo"),
    "list_settlement_runs": _ENTITY_PAGE
    + ("deviceId", "source", "runStatus", "createdFrom", "createdTo"),
    "list_device_models": ("vendorCode", "deviceType", "status"),
    "list_stores": _ENTITY_PAGE + ("status", "q"),
    "list_store_audit": _PAGE,
    "list_registers": _ENTITY_PAGE + ("status",),
    "list_register_audit": _PAGE,
    "list_terminals": _ENTITY_PAGE + ("status", "q"),
    "list_terminal_acquirers": _ENTITY_PAGE,
    "list_terminal_providers": _ENTITY_PAGE,
    "list_terminal_links": _PAGE,
    "list_terminal_audit": _PAGE,
    "list_devices": _ENTITY_PAGE
    + (
        "storeId",
        "registerId",
        "vendorCode",
        "deviceModelId",
        "deviceType",
        "lifecycleStatus",
        "ownershipStatus",
        "integrationChannel",
        "q",
    ),
    "list_device_assignments": _PAGE,
    "list_device_audit": _PAGE,
    "list_device_keys": _PAGE,
}

#: Free-text filters scanned for card numbers before sending (wire names).
PHYSICAL_POS_FREE_TEXT_FILTERS: Tuple[str, ...] = ("merchantReference", "q")

#: 5xx codes with which the gateway says nothing was written (the request
#: never started): a payment write that gets one of these is a definite
#: refusal, not an unknown outcome. Any other 5xx, a 504 included, leaves the
#: outcome unknown.
PHYSICAL_POS_NOT_STARTED_CODES: FrozenSet[str] = frozenset(
    (
        "physical_pos.presence.unavailable",
        "physical_pos.signing.unavailable",
        "physical_pos.service.busy",
        "physical_pos.service.clock_skew",
        "physical_pos.service.not_configured",
    )
)
