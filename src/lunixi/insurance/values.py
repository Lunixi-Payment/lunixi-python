"""Insurance (``/api/v1/insurance``, product ``INSURANCE_SERVICE``) — value sets, request fields, filters.

The field and filter lists are the same lists as the Node SDK and the shared
catalog (``contracts/products/insurance.json``). The field rules of an
insurance type's own object (``insured``, ``tickets`` …) are NOT repeated
here: the insurance service owns them and answers a violation with 422
``insurance.validation.invalid`` and every ``details.errors[{field, reason}]``
at once.
"""

from __future__ import annotations

from types import MappingProxyType

__all__ = [
    "InsurancePremiumCollectedBy",
    "InsuranceQuoteStatus",
    "InsuranceOrderStatus",
    "InsuranceCollectionStatus",
    "InsurancePolicyStatus",
    "InsuranceRefundStatus",
    "InsuranceDocumentStatus",
    "InsurancePaymentMode",
    "InsuranceOrderSurface",
    "InsuranceLeadStatus",
    "InsuranceReferenceKind",
    "InsuranceEvents",
    "INSURANCE_EVENT_PATTERN",
    "INSURANCE_EVENT_TYPES",
    "INSURANCE_TYPE_OBJECT_FIELDS",
    "INSURANCE_QUOTE_FIELDS",
    "INSURANCE_LEAD_FIELDS",
    "INSURANCE_PRODUCT_SEARCH_FIELDS",
    "INSURANCE_ORDER_FIELDS",
    "INSURANCE_CONSENT_FIELDS",
    "INSURANCE_EXTERNAL_PAYMENT_FIELDS",
    "INSURANCE_EXTERNAL_REFUND_FIELDS",
    "INSURANCE_FILTERS",
    "INSURANCE_IDEMPOTENCY_KEY_PATTERN",
    "INSURANCE_MAX_LIMIT",
    "INSURANCE_MAX_CONTEXT_ITEMS",
    "INSURANCE_EXPORT_ORDER_CAP",
    "INSURANCE_LEAD_NOTE_MAX_LENGTH",
    "INSURANCE_CURSOR_MAX_LENGTH",
]


class InsurancePremiumCollectedBy:
    """Who collects the premium. ``PROVIDER`` orders cannot be completed through this API yet."""

    MERCHANT = "MERCHANT"
    PROVIDER = "PROVIDER"
    ALL = (MERCHANT, PROVIDER)


class InsuranceQuoteStatus:
    """Status of a quote option. Only a ``QUOTED`` option that has not expired becomes an order."""

    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    ALL = (REQUESTED, QUOTED, EXPIRED, REJECTED, ERROR)


class InsuranceOrderStatus:
    """The order's overall status, derived on every read from the four axes.

    In this order: ``REFUNDED``, ``CANCELLED``, ``FAILED``,
    ``ACTION_REQUIRED``, ``PROCESSING``, ``PARTIALLY_ACTIVE``, ``ACTIVE``,
    ``CREATED``.
    """

    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    PARTIALLY_ACTIVE = "PARTIALLY_ACTIVE"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    ALL = (
        CREATED,
        PROCESSING,
        ACTION_REQUIRED,
        PARTIALLY_ACTIVE,
        ACTIVE,
        FAILED,
        CANCELLED,
        REFUNDED,
    )


class InsuranceCollectionStatus:
    """Premium collection axis (``collectionStatus``)."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    COLLECTED = "COLLECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    ALL = (NOT_STARTED, PENDING, ACTION_REQUIRED, COLLECTED, FAILED, UNKNOWN)


class InsurancePolicyStatus:
    """Policy axis (``policyStatus``) of an order and of each of its policies."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    PARTIALLY_ISSUED = "PARTIALLY_ISSUED"
    ISSUED = "ISSUED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    UNKNOWN = "UNKNOWN"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    ALL = (
        NOT_REQUESTED,
        PENDING,
        PARTIALLY_ISSUED,
        ISSUED,
        FAILED_RETRYABLE,
        FAILED_FINAL,
        UNKNOWN,
        CANCEL_PENDING,
        CANCELLED,
    )


class InsuranceRefundStatus:
    """Premium refund axis (``refundStatus``)."""

    NONE = "NONE"
    REQUIRED = "REQUIRED"
    PENDING = "PENDING"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"
    ALL = (NONE, REQUIRED, PENDING, REFUNDED, FAILED)


class InsuranceDocumentStatus:
    """Policy document axis (``documentStatus``); it does not change the overall status."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"
    ALL = (NOT_AVAILABLE, PENDING, AVAILABLE, FAILED)


class InsurancePaymentMode:
    """How the premium of an order is paid (``paymentMode``)."""

    LUNIXI_PAYMENT = "LUNIXI_PAYMENT"
    EXTERNAL_PAYMENT = "EXTERNAL_PAYMENT"
    NO_PAYMENT = "NO_PAYMENT"
    ALL = (LUNIXI_PAYMENT, EXTERNAL_PAYMENT, NO_PAYMENT)


class InsuranceOrderSurface:
    """Where an order was created (``surface``)."""

    MERCHANT_API = "MERCHANT_API"
    CHECKOUT_FORM = "CHECKOUT_FORM"
    PANEL = "PANEL"
    ALL = (MERCHANT_API, CHECKOUT_FORM, PANEL)


class InsuranceLeadStatus:
    """Status of a lead: what Lunixi knows about sending it to the insurance provider.

    ``PENDING``: the provider call is still running. ``SUBMITTED``: the
    provider received the lead (``insurance.lead.submitted``). ``UNKNOWN``:
    the request reached the provider but the outcome is not known; it is
    never sent again — open a new lead with a new ``Idempotency-Key`` if
    needed. ``FAILED``: the provider refused it or it never reached the
    provider (``errorCode``).
    """

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    ALL = (PENDING, SUBMITTED, UNKNOWN, FAILED)


class InsuranceReferenceKind:
    """Lunixi reference code lists (``list_reference_values(kind)``).

    ``DISTRICT``, ``DEVICE_MODEL``, ``VEHICLE_MODEL``, ``BANK_BRANCH`` and
    ``PET_BREED`` need ``parentCode`` (province, brand, bank, ``CAT`` |
    ``DOG``); ``COUNTRY``, ``CITY`` and ``BANK`` take none.
    """

    COUNTRY = "COUNTRY"
    CITY = "CITY"
    DISTRICT = "DISTRICT"
    DEVICE_BRAND = "DEVICE_BRAND"
    DEVICE_MODEL = "DEVICE_MODEL"
    VEHICLE_BRAND = "VEHICLE_BRAND"
    VEHICLE_MODEL = "VEHICLE_MODEL"
    VEHICLE_TYPE = "VEHICLE_TYPE"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"
    VEHICLE_USAGE = "VEHICLE_USAGE"
    LIABILITY_LIMIT = "LIABILITY_LIMIT"
    OCCUPATION = "OCCUPATION"
    PET_BREED = "PET_BREED"
    DWELLING_TYPE = "DWELLING_TYPE"
    DWELLING_FLOOR = "DWELLING_FLOOR"
    BANK = "BANK"
    BANK_BRANCH = "BANK_BRANCH"
    FINANCE_INSTITUTION = "FINANCE_INSTITUTION"
    MEDICAL_PROCEDURE_COVER = "MEDICAL_PROCEDURE_COVER"
    ALL = (
        COUNTRY,
        CITY,
        DISTRICT,
        DEVICE_BRAND,
        DEVICE_MODEL,
        VEHICLE_BRAND,
        VEHICLE_MODEL,
        VEHICLE_TYPE,
        PRODUCT_CATEGORY,
        VEHICLE_USAGE,
        LIABILITY_LIMIT,
        OCCUPATION,
        PET_BREED,
        DWELLING_TYPE,
        DWELLING_FLOOR,
        BANK,
        BANK_BRANCH,
        FINANCE_INSTITUTION,
        MEDICAL_PROCEDURE_COVER,
    )


class InsuranceEvents:
    """Insurance webhook event types (subscription ``insurance.*``).

    Verified with :class:`~lunixi.webhook.verifier.WebhookVerifier`;
    deduplicate on the event id (``data.eventId`` is the same value).
    """

    #: The order's policies were issued.
    POLICY_ISSUED = "insurance.policy.issued"
    #: The policy could not be issued or the premium was not collected; ``data.errorCode`` says why.
    POLICY_FAILED = "insurance.policy.failed"
    #: The collected premium has to be refunded; ``data.errorCode`` says why.
    REFUND_REQUIRED = "insurance.refund.required"
    #: A policy document can be downloaded (``policies[].documentUrl``).
    POLICY_DOCUMENT_READY = "insurance.policy.document_ready"
    #: The provider confirmed the cancellation.
    POLICY_CANCELLED = "insurance.policy.cancelled"
    #: The premium refund completed.
    REFUND_COMPLETED = "insurance.refund.completed"
    #: The insurance provider received a lead. ``data`` is a lead summary, not an order.
    LEAD_SUBMITTED = "insurance.lead.submitted"
    #: Subscription pattern covering every insurance event.
    ALL_EVENTS = "insurance.*"
    ORDER_EVENTS = (
        POLICY_ISSUED,
        POLICY_FAILED,
        REFUND_REQUIRED,
        POLICY_DOCUMENT_READY,
        POLICY_CANCELLED,
        REFUND_COMPLETED,
    )
    LEAD_EVENTS = (LEAD_SUBMITTED,)
    ALL = (*ORDER_EVENTS, *LEAD_EVENTS)


INSURANCE_EVENT_PATTERN = InsuranceEvents.ALL_EVENTS
INSURANCE_EVENT_TYPES = InsuranceEvents.ALL

#: The type objects of the gateway's type body, one per insurance type (``typeObject``).
INSURANCE_TYPE_OBJECT_FIELDS = (
    "tickets",
    "stay",
    "device",
    "product",
    "vehicle",
    "trip",
    "rental",
    "instrument",
    "event",
    "accident",
    "procedure",
    "pet",
    "residence",
    "abroadStay",
)

#: Top-level fields of ``create_quote()`` (the gateway answers any other with 400).
INSURANCE_QUOTE_FIELDS = (
    "insuranceType",
    "schemaVersion",
    "currency",
    "paymentIntentId",
    "context",
    "merchantOrderId",
    "policyholder",
    "insured",
    *INSURANCE_TYPE_OBJECT_FIELDS,
)

#: Top-level fields of ``create_lead()``: the type body of a quote without the
#: basket, currency and order fields, plus ``shipment``, ``company`` and ``note``.
INSURANCE_LEAD_FIELDS = (
    "insuranceType",
    "schemaVersion",
    "policyholder",
    "insured",
    *INSURANCE_TYPE_OBJECT_FIELDS,
    "shipment",
    "company",
    "note",
)

#: Fields of ``search_products()``.
INSURANCE_PRODUCT_SEARCH_FIELDS = ("currency", "insuranceType", "context")

#: Fields of ``create_order()``.
INSURANCE_ORDER_FIELDS = ("quoteId", "merchantOrderId", "consent")

#: Fields of ``consent`` (``create_order()``).
INSURANCE_CONSENT_FIELDS = ("termsVersion", "termsSha256", "acceptedAt")

#: Fields of ``confirm_payment()`` (a premium collected outside Lunixi).
INSURANCE_EXTERNAL_PAYMENT_FIELDS = (
    "externalPaymentId",
    "paidAmount",
    "paidCurrency",
    "paidAt",
    "paymentProvider",
)

#: Fields of ``externalRefund`` (``refund_premium()`` for a premium collected outside Lunixi).
INSURANCE_EXTERNAL_REFUND_FIELDS = ("externalRefundId", "refundedAt")

_RECONCILIATION = ("from", "to", "connectionId", "insuranceType", "currency")

#: Query filters each read accepts (the gateway rejects any other with 400).
INSURANCE_FILTERS = MappingProxyType(
    {
        "listProducts": ("currency", "paymentIntentId", "insuranceType"),
        "listReferenceValues": ("parentCode", "limit", "cursor"),
        "listOrders": ("limit", "cursor", "paymentIntentId", "merchantOrderId"),
        "getReconciliationSummary": _RECONCILIATION,
        "listReconciliationOrders": (*_RECONCILIATION, "limit", "cursor"),
        "exportReconciliation": (*_RECONCILIATION, "cursor"),
        "listLeads": ("limit", "cursor", "insuranceType", "status"),
    }
)

#: ``Idempotency-Key`` of the insurance routes: 8–200 printable ASCII characters, no spaces.
INSURANCE_IDEMPOTENCY_KEY_PATTERN = r"^[\x21-\x7E]{8,200}$"
#: Largest page (``limit`` 1–100).
INSURANCE_MAX_LIMIT = 100
#: Most basket items one ``context.items`` may carry.
INSURANCE_MAX_CONTEXT_ITEMS = 100
#: Orders in one reconciliation CSV file; a longer export ends with a continuation line.
INSURANCE_EXPORT_ORDER_CAP = 20000
#: Longest lead ``note`` (characters).
INSURANCE_LEAD_NOTE_MAX_LENGTH = 1000
#: Longest cursor the insurance lists hand out.
INSURANCE_CURSOR_MAX_LENGTH = 512
