"""Closed dictionaries for the fraud decision request.

These mirror the gateway's own dictionaries. The gateway validates every
declared value against them, so a value outside a dictionary is a 400 and never
reaches the engine. They are published here as constants so an integration can
reference a name instead of repeating a string literal, and so the SDK can
reject an impossible value before the round trip.

Reference: the platform's fraud taxonomy and the decision endpoint's request
object.
"""

from __future__ import annotations

import re
from typing import Tuple

__all__ = [
    "Channel",
    "Surface",
    "Stage",
    "OperationKind",
    "AuthMode",
    "ProductContext",
    "Decision",
    "INTEGRATION_MODE_STANDALONE",
    "CHANNEL_VALUES",
    "SURFACE_VALUES",
    "STAGE_VALUES",
    "OPERATION_KIND_VALUES",
    "AUTH_MODE_VALUES",
    "PRODUCT_CONTEXT_VALUES",
    "DECISION_VALUES",
    "TRANSACTION_REF_MAX_LENGTH",
    "SUBJECT_ID_MAX_LENGTH",
    "SUB_MERCHANT_REF_PATTERN",
]


class Channel:
    """Channels an external caller may declare.

    🔴 The platform's own channels — its hosted checkout and its wallet — are
    NOT declarable from outside. Declaring one would be a way to trigger flows
    bound to a platform channel, so the gateway answers 400
    (``FRAUD_CHANNEL_NOT_DECLARABLE``).
    """

    MERCHANT_FORM = "merchant_form"
    STANDALONE_API = "standalone_api"


class Surface:
    """The decision surface inside a channel."""

    FORM_GATE = "form_gate"
    TRANSACTION = "transaction"
    WITHDRAWAL_GATE = "withdrawal_gate"
    SETTLEMENT = "settlement"


class Stage:
    """The moment in the transaction lifecycle at which you are asking."""

    PRE_AUTHORIZATION = "pre_authorization"
    POST_AUTHENTICATION = "post_authentication"
    POST_HOC = "post_hoc"
    ASYNC_EVENT = "async_event"
    SCHEDULED = "scheduled"


class OperationKind:
    """The business operation being evaluated."""

    CARD_SALE = "card_sale"
    CARD_PREAUTH = "card_preauth"
    W2W_TRANSFER = "w2w_transfer"
    W2IBAN_WITHDRAWAL = "w2iban_withdrawal"
    BULK_PAYOUT = "bulk_payout"
    AGENT_CASH_OUT = "agent_cash_out"
    BILL_PAYMENT = "bill_payment"
    MERCHANT_PAYMENT = "merchant_payment"
    QR_PAYMENT = "qr_payment"
    CARD_TOPUP = "card_topup"
    AGENT_TOPUP = "agent_topup"
    BANK_TRANSFER_TOPUP = "bank_transfer_topup"
    OUTBOUND_TRANSFER = "outbound_transfer"
    INBOUND_TRANSFER = "inbound_transfer"


class AuthMode:
    """Authentication mode.

    Requested and applied travel in SEPARATE fields
    (``auth_mode_requested`` / ``auth_mode_applied``) so a rule can see that a
    3-D Secure step was asked for and a 2-D authorisation happened anyway.
    """

    TWO_D = "2d"
    THREE_D = "3d"


class ProductContext:
    """Product contexts an external caller may declare.

    The contexts reserved for the platform's own senders — simulation,
    backfill and manual review, which run on an unbilled lane — are rejected
    from outside.
    """

    LIVE_SESSION = "live_session"
    PAYMENT_FORM = "payment_form"
    HOSTED_PAYMENT_FORM = "hosted_payment_form"
    DIRECT_API = "direct_api"


class Decision:
    """The outcomes the decision endpoint returns.

    ``FORCE_3D`` is not a refusal: it asks you to re-run the payment with 3-D
    Secure. Treating it as a block turns a recoverable transaction into a lost
    sale.
    """

    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"
    FORCE_3D = "force_3d"


#: The only integration mode an external caller may declare. Anything else is
#: a 400 — the other value belongs to the platform's internal senders.
INTEGRATION_MODE_STANDALONE = "standalone"

CHANNEL_VALUES: Tuple[str, ...] = (Channel.MERCHANT_FORM, Channel.STANDALONE_API)
SURFACE_VALUES: Tuple[str, ...] = (
    Surface.FORM_GATE,
    Surface.TRANSACTION,
    Surface.WITHDRAWAL_GATE,
    Surface.SETTLEMENT,
)
STAGE_VALUES: Tuple[str, ...] = (
    Stage.PRE_AUTHORIZATION,
    Stage.POST_AUTHENTICATION,
    Stage.POST_HOC,
    Stage.ASYNC_EVENT,
    Stage.SCHEDULED,
)
OPERATION_KIND_VALUES: Tuple[str, ...] = (
    OperationKind.CARD_SALE,
    OperationKind.CARD_PREAUTH,
    OperationKind.W2W_TRANSFER,
    OperationKind.W2IBAN_WITHDRAWAL,
    OperationKind.BULK_PAYOUT,
    OperationKind.AGENT_CASH_OUT,
    OperationKind.BILL_PAYMENT,
    OperationKind.MERCHANT_PAYMENT,
    OperationKind.QR_PAYMENT,
    OperationKind.CARD_TOPUP,
    OperationKind.AGENT_TOPUP,
    OperationKind.BANK_TRANSFER_TOPUP,
    OperationKind.OUTBOUND_TRANSFER,
    OperationKind.INBOUND_TRANSFER,
)
AUTH_MODE_VALUES: Tuple[str, ...] = (AuthMode.TWO_D, AuthMode.THREE_D)
PRODUCT_CONTEXT_VALUES: Tuple[str, ...] = (
    ProductContext.LIVE_SESSION,
    ProductContext.PAYMENT_FORM,
    ProductContext.HOSTED_PAYMENT_FORM,
    ProductContext.DIRECT_API,
)
DECISION_VALUES: Tuple[str, ...] = (
    Decision.ALLOW,
    Decision.REVIEW,
    Decision.BLOCK,
    Decision.FORCE_3D,
)

#: Maximum length of ``transaction_ref`` and ``subject_id``.
TRANSACTION_REF_MAX_LENGTH = 180
SUBJECT_ID_MAX_LENGTH = 180

#: ``sub_merchant_ref`` format: letters, digits and ``. _ : @ -``, 1-180 chars.
SUB_MERCHANT_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:@-]{1,180}$")
