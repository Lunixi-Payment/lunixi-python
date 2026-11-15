"""Bank accounts (``/api/v1/bank-connect``, product ``BANK_CONNECT``) — value sets, filters and routes.

:data:`BANK_CONNECT_FILTERS` lists the query filters of each read route;
:data:`BANK_TRANSFER_ROUTES` is the single description of the transfer and
currency-exchange routes (method, path, body fields, query fields and the
``Idempotency-Key`` rule). Both are the same lists as the Node SDK and the
shared catalog (``contracts/products/bank-connect.json``).
"""

from __future__ import annotations

from types import MappingProxyType

from .._routes import freeze_routes

__all__ = [
    "BankConnectionStatus",
    "BankAccountStatus",
    "BankTransactionDirection",
    "BankTransactionType",
    "BankAvailability",
    "BankCapability",
    "BankSyncStatus",
    "BankConnectEvents",
    "BANK_CONNECT_EVENT_PATTERN",
    "BANK_CONNECT_EVENT_TYPES",
    "BANK_CONNECT_FILTERS",
    "BANK_CONNECT_MAX_LIMIT",
    "BANK_CONNECT_MAX_ACCOUNT_FILTER",
    "BANK_CONNECT_BOOKED_RANGE_MAX_DAYS",
    "BANK_CONNECT_CURSOR_MAX_LENGTH",
    "BankTransferStatus",
    "BankTransferRail",
    "BankTransferInitiatedVia",
    "BankFxOrderStatus",
    "BankFxRequestedSide",
    "BankTransferEvents",
    "BANK_TRANSFER_EVENT_PATTERN",
    "BANK_TRANSFER_EVENT_TYPES",
    "BANK_TRANSFER_ROUTES",
    "BANK_TRANSFER_IDEMPOTENCY_KEY_PATTERN",
    "BANK_TRANSFER_DESCRIPTION_MAX",
    "BANK_TRANSFER_RECEIVER_NAME_MIN",
    "BANK_TRANSFER_RECEIVER_NAME_MAX",
    "BANK_TRANSFER_IBAN_MAX",
    "BANK_TRANSFER_PAYMENT_PURPOSE_PATTERN",
]


class BankConnectionStatus:
    """Status of a bank connection.

    Data is read only while a connection is ``ACTIVE`` or ``DEGRADED``
    (``DEGRADED``: the last reads from the bank failed, so the data may be
    older; see the account's ``freshness``). ``request_sync()`` on any other
    status is 409 ``bank_connect.connection.not_active``.
    """

    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    DISCONNECTED = "DISCONNECTED"
    ALL = (
        PENDING_DOCUMENTS,
        UNDER_REVIEW,
        PENDING_SETUP,
        ACTIVE,
        DEGRADED,
        SUSPENDED,
        DISCONNECTED,
    )


class BankAccountStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ALL = (ACTIVE, INACTIVE)


class BankTransactionDirection:
    """Money in (``CREDIT``) or out (``DEBIT``). ``amountMinor`` is always positive."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    ALL = (CREDIT, DEBIT)


class BankTransactionType:
    """Lunixi's bank-independent transaction type (``canonicalType``)."""

    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    INTERNAL_IN = "INTERNAL_IN"
    INTERNAL_OUT = "INTERNAL_OUT"
    POS_SETTLEMENT = "POS_SETTLEMENT"
    POS_SETTLEMENT_REFUND = "POS_SETTLEMENT_REFUND"
    FEE = "FEE"
    TAX = "TAX"
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    CARD = "CARD"
    LOAN = "LOAN"
    FX = "FX"
    INTEREST = "INTEREST"
    OTHER = "OTHER"
    ALL = (
        TRANSFER_IN,
        TRANSFER_OUT,
        INTERNAL_IN,
        INTERNAL_OUT,
        POS_SETTLEMENT,
        POS_SETTLEMENT_REFUND,
        FEE,
        TAX,
        CASH_IN,
        CASH_OUT,
        CARD,
        LOAN,
        FX,
        INTEREST,
        OTHER,
    )


class BankAvailability:
    """``AVAILABLE``: the bank can be connected (connections are started in the Lunixi dashboard)."""

    AVAILABLE = "AVAILABLE"
    COMING_SOON = "COMING_SOON"
    ALL = (AVAILABLE, COMING_SOON)


class BankCapability:
    """What a bank or a connection offers (``capabilities``).

    ``OUTGOING_TRANSFER`` and ``FX_EXCHANGE``: the connection can send
    transfers (``bank_connect().transfers``) and exchange currency
    (``bank_connect().fx``).
    """

    ACCOUNT_LIST = "ACCOUNT_LIST"
    BALANCE = "BALANCE"
    TRANSACTIONS = "TRANSACTIONS"
    OUTGOING_TRANSFER = "OUTGOING_TRANSFER"
    FX_EXCHANGE = "FX_EXCHANGE"
    ALL = (ACCOUNT_LIST, BALANCE, TRANSACTIONS, OUTGOING_TRANSFER, FX_EXCHANGE)


class BankSyncStatus:
    """``QUEUED``: the read starts now or is already waiting. ``SCHEDULED``: it runs at ``scheduledAt``."""

    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    ALL = (QUEUED, SCHEDULED)


class BankConnectEvents:
    """Bank-account webhook event types, verified with :class:`~lunixi.webhook.verifier.WebhookVerifier`."""

    #: A new transaction (CREDIT or DEBIT) was read from one of your connected
    #: accounts. Sent once per transaction first seen by a regular read after
    #: the connection became active; the history loaded when an account is
    #: first connected does not send it. Deduplicate on the event id.
    TRANSACTION_RECEIVED = "bank_account.transaction.received"
    #: Subscription pattern covering every bank-account event.
    ALL_EVENTS = "bank_account.*"
    ALL = (TRANSACTION_RECEIVED,)


BANK_CONNECT_EVENT_PATTERN = BankConnectEvents.ALL_EVENTS
BANK_CONNECT_EVENT_TYPES = BankConnectEvents.ALL


class BankTransferStatus:
    """Status of an outgoing transfer.

    ``PENDING_OTP``: started in the dashboard, waiting for the user's e-mail
    code (an API-key transfer never has it). ``SUBMITTED``: approved and queued
    or sent to the bank. ``PROCESSING``: the bank is processing it.
    ``COMPLETED``: the bank completed it; it can still become ``RETURNED``.
    ``FAILED``, ``RETURNED`` and ``CANCELED`` are final.
    """

    PENDING_OTP = "PENDING_OTP"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"
    CANCELED = "CANCELED"
    ALL = (PENDING_OTP, SUBMITTED, PROCESSING, COMPLETED, FAILED, RETURNED, CANCELED)


class BankTransferRail:
    """The rail the bank chose: own accounts, same bank, FAST, EFT; ``UNKNOWN`` until it says."""

    INTERNAL = "INTERNAL"
    INTRABANK = "INTRABANK"
    FAST = "FAST"
    EFT = "EFT"
    UNKNOWN = "UNKNOWN"
    ALL = (INTERNAL, INTRABANK, FAST, EFT, UNKNOWN)


class BankTransferInitiatedVia:
    """Where the transfer or exchange order was started."""

    PANEL = "PANEL"
    API = "API"
    ALL = (PANEL, API)


class BankFxOrderStatus:
    """Status of a currency exchange order. An order is created ``SUBMITTED``."""

    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ALL = (SUBMITTED, COMPLETED, FAILED)


class BankFxRequestedSide:
    """Which amount of a quote you fixed: ``SOURCE`` (sell amount) or ``TARGET`` (buy amount)."""

    SOURCE = "SOURCE"
    TARGET = "TARGET"
    ALL = (SOURCE, TARGET)


class BankTransferEvents:
    """Bank Connect transfer webhook event types (``bank_transfer.*``).

    One event per transfer and type; the event id is the same on every
    redelivery. Not to be confused with the ``payment.bank_transfer.*`` events
    of a payment (:class:`~lunixi.payments.PaymentBankTransferEvents`).
    Exchange orders have no webhook.
    """

    #: A transfer was created (API: ``SUBMITTED``; dashboard: ``PENDING_OTP``).
    CREATED = "bank_transfer.created"
    #: The bank completed the transfer.
    COMPLETED = "bank_transfer.completed"
    #: The transfer failed; ``failureCode`` says why.
    FAILED = "bank_transfer.failed"
    #: The receiving bank sent a completed transfer back.
    RETURNED = "bank_transfer.returned"
    #: Subscription pattern covering every transfer event.
    ALL_EVENTS = "bank_transfer.*"
    ALL = (CREATED, COMPLETED, FAILED, RETURNED)


BANK_TRANSFER_EVENT_PATTERN = BankTransferEvents.ALL_EVENTS
BANK_TRANSFER_EVENT_TYPES = BankTransferEvents.ALL

#: Query filters each read route accepts (the gateway rejects any other with 400).
BANK_CONNECT_FILTERS = MappingProxyType(
    {
        "listBanks": ("limit", "cursor"),
        "listConnections": ("limit", "cursor", "status", "bankId"),
        "listAccounts": ("limit", "cursor", "connectionId", "bankId", "currency", "status"),
        "listBalances": ("limit", "cursor", "accountId", "currency"),
        "listTransactions": (
            "limit",
            "cursor",
            "accountId",
            "bookedFrom",
            "bookedTo",
            "direction",
            "minAmountMinor",
            "maxAmountMinor",
            "canonicalType",
        ),
    }
)

#: Largest page (``limit`` 1–100; the gateway's default is 25).
BANK_CONNECT_MAX_LIMIT = 100
#: Most account ids one ``accountId`` filter may carry.
BANK_CONNECT_MAX_ACCOUNT_FILTER = 100
#: Widest ``bookedFrom`` … ``bookedTo`` window of one transaction request, in days.
BANK_CONNECT_BOOKED_RANGE_MAX_DAYS = 92
#: Longest cursor the gateway hands out.
BANK_CONNECT_CURSOR_MAX_LENGTH = 2048

_TRANSFER_BASE = "/api/v1/bank-connect"

#: Transfer and exchange routes (Node ``BANK_TRANSFER_ROUTES``). Every route
#: is signed and needs ``bank-connect:transfer`` plus a key with an IP allowlist.
BANK_TRANSFER_ROUTES = freeze_routes(
    {
        "listTransferPurposes": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/transfer-purposes",
            "idempotencyKey": False,
            "query": ["connectionId"],
        },
        "createTransfer": {
            "method": "POST",
            "path": f"{_TRANSFER_BASE}/transfers",
            "idempotencyKey": True,
            "required": ["accountId", "receiverIban", "receiverName", "amountMinor"],
            "optional": ["currency", "paymentPurpose", "description"],
        },
        "listTransfers": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/transfers",
            "idempotencyKey": False,
            "query": ["limit", "cursor", "accountId", "status", "createdFrom", "createdTo"],
        },
        "getTransfer": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/transfers/:transferId",
            "idempotencyKey": False,
        },
        "listFxRates": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/fx/rates",
            "idempotencyKey": False,
            "query": ["connectionId"],
        },
        "createFxQuote": {
            "method": "POST",
            "path": f"{_TRANSFER_BASE}/fx/quotes",
            "idempotencyKey": False,
            "required": ["sourceAccountId", "targetAccountId"],
            "optional": ["sourceAmountMinor", "targetAmountMinor"],
        },
        "createFxOrder": {
            "method": "POST",
            "path": f"{_TRANSFER_BASE}/fx/orders",
            "idempotencyKey": True,
            "required": ["quoteId"],
            "optional": ["description"],
        },
        "listFxOrders": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/fx/orders",
            "idempotencyKey": False,
            "query": ["limit", "cursor", "status"],
        },
        "getFxOrder": {
            "method": "GET",
            "path": f"{_TRANSFER_BASE}/fx/orders/:orderId",
            "idempotencyKey": False,
        },
    }
)

#: ``Idempotency-Key`` of ``transfers.create`` / ``fx.create_order``: 8–200 printable ASCII characters.
BANK_TRANSFER_IDEMPOTENCY_KEY_PATTERN = r"^[\x21-\x7E]{8,200}$"
#: Longest ``description`` of a transfer or an exchange order.
BANK_TRANSFER_DESCRIPTION_MAX = 140
#: ``receiverName`` length range (characters).
BANK_TRANSFER_RECEIVER_NAME_MIN = 2
BANK_TRANSFER_RECEIVER_NAME_MAX = 140
#: Longest ``receiverIban`` the gateway accepts (spaces included); the service checks the mod-97 sum.
BANK_TRANSFER_IBAN_MAX = 42
#: ``paymentPurpose``: a code from ``transfers.list_purposes()``.
BANK_TRANSFER_PAYMENT_PURPOSE_PATTERN = r"^[A-Za-z0-9_]{1,64}$"
