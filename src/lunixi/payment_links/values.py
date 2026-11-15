"""Closed value sets of the payment-link API (``/api/v1/payments/links``).

The gateway validates each of these against a fixed list and answers an
unknown value with 400, so they are constants instead of strings typed at each
call site.
"""

from __future__ import annotations

import re

__all__ = [
    "PaymentLinkUsage",
    "PaymentLinkAmountMode",
    "PaymentLinkState",
    "PaymentLinkAttemptState",
    "PaymentLinkEnvironment",
    "BuyerFieldRequirement",
    "CustomFieldType",
    "PaymentLinkButtonLabel",
    "PaymentLinkDeliveryChannel",
    "PaymentLinkQrFormat",
    "PaymentLinkLocale",
    "PaymentLinkImageContentType",
    "PAYMENT_LINK_SPEC_FIELDS",
    "PAYMENT_LINK_IMMUTABLE_FIELDS",
    "PAYMENT_LINK_LIST_FILTERS",
    "PAYMENT_LINK_ATTEMPT_LIST_FILTERS",
    "PAYMENT_LINK_PAYMENT_LIST_FILTERS",
    "PAYMENT_LINK_ACTIONS",
    "IDEMPOTENCY_KEY_PATTERN",
    "ASSET_ID_PATTERN",
    "QR_MIN_SIZE",
    "QR_MAX_SIZE",
]


class PaymentLinkUsage:
    #: Can be paid once: an invoice or a personal payment request.
    SINGLE_USE = "SINGLE_USE"
    #: Can be paid many times: donations, tickets, a product page.
    MULTI_USE = "MULTI_USE"
    ALL = (SINGLE_USE, MULTI_USE)


class PaymentLinkAmountMode:
    #: You set the amount (``amountMinor``).
    FIXED = "FIXED"
    #: The buyer enters the amount, within ``minAmountMinor`` / ``maxAmountMinor``.
    OPEN = "OPEN"
    #: The buyer picks quantities from ``items``; the amount is the sum of the lines.
    ITEMIZED = "ITEMIZED"
    ALL = (FIXED, OPEN, ITEMIZED)


class PaymentLinkState:
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    DEACTIVATED = "DEACTIVATED"
    #: Removed by Lunixi; every write on the link answers 409 ``payment_link.link.taken_down``.
    TAKEN_DOWN = "TAKEN_DOWN"
    ALL = (ACTIVE, PAUSED, COMPLETED, EXPIRED, DEACTIVATED, TAKEN_DOWN)


class PaymentLinkAttemptState:
    OPEN = "OPEN"
    BOUND = "BOUND"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ALL = (OPEN, BOUND, SUCCEEDED, FAILED, EXPIRED, ABANDONED, NEEDS_REVIEW)


class PaymentLinkEnvironment:
    TEST = "TEST"
    LIVE = "LIVE"
    ALL = (TEST, LIVE)


class BuyerFieldRequirement:
    HIDDEN = "HIDDEN"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"
    ALL = (HIDDEN, OPTIONAL, REQUIRED)


class CustomFieldType:
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    DATE = "DATE"
    SELECT = "SELECT"
    CHECKBOX = "CHECKBOX"
    TCKN = "TCKN"
    VKN = "VKN"
    ALL = (TEXT, NUMBER, EMAIL, PHONE, DATE, SELECT, CHECKBOX, TCKN, VKN)


class PaymentLinkButtonLabel:
    PAY = "PAY"
    DONATE = "DONATE"
    BUY = "BUY"
    BOOK = "BOOK"
    ALL = (PAY, DONATE, BUY, BOOK)


class PaymentLinkDeliveryChannel:
    EMAIL = "EMAIL"
    SMS = "SMS"
    ALL = (EMAIL, SMS)


class PaymentLinkQrFormat:
    SVG = "svg"
    PNG = "png"
    ALL = (SVG, PNG)


class PaymentLinkLocale:
    TR = "tr"
    EN = "en"
    ALL = (TR, EN)


class PaymentLinkImageContentType:
    """Types a link image can be declared as; SVG is never accepted.

    On confirmation the stored file's own bytes are checked against the
    declared type.
    """

    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    ALL = (PNG, JPEG, WEBP)


#: Every field of a payment-link definition, in the gateway's spelling. Create
#: and update bodies carry only these keys (plus ``environment`` on create and
#: ``expectedRowVersion`` on update); the gateway refuses any other with 400.
PAYMENT_LINK_SPEC_FIELDS = (
    "usage",
    "amountMode",
    "currency",
    "amountMinor",
    "minAmountMinor",
    "maxAmountMinor",
    "suggestedAmountsMinor",
    "quantityEnabled",
    "minQuantity",
    "maxQuantity",
    "items",
    "capacity",
    "title",
    "description",
    "imageAssetId",
    "successMessage",
    "successRedirectUrl",
    "taxNote",
    "locale",
    "startsAt",
    "expiresAt",
    "eventAt",
    "buttonLabelKey",
    "requireTermsAcceptance",
    "buyerFields",
    "customFields",
    "recipient",
    "prefill",
    "verification",
    "reminders",
    "checkout",
    "reference",
    "tags",
    "branchCode",
    "salesChannel",
    "campaign",
    "agentCode",
    "merchantNotifyEmails",
    "metadata",
)

#: Fixed at creation; an update naming one answers 422 ``payment_link.link.immutable_field``.
PAYMENT_LINK_IMMUTABLE_FIELDS = ("usage", "amountMode", "currency")

#: Query filters of ``list()``.
PAYMENT_LINK_LIST_FILTERS = (
    "limit",
    "cursor",
    "includeTotal",
    "state",
    "usage",
    "amountMode",
    "environment",
    "tag",
    "branchCode",
    "createdById",
    "query",
    "createdFrom",
    "createdTo",
)

#: Query filters of ``list_attempts()``.
PAYMENT_LINK_ATTEMPT_LIST_FILTERS = ("limit", "cursor", "includeTotal", "state")

#: Query filters of ``list_payments()``.
PAYMENT_LINK_PAYMENT_LIST_FILTERS = ("limit", "cursor", "includeTotal")

#: The state changes of ``action()``.
PAYMENT_LINK_ACTIONS = ("pause", "resume", "deactivate")

#: ``Idempotency-Key`` format the gateway accepts: 8–200 printable ASCII characters, no spaces.
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[\x21-\x7E]{8,200}")

#: Shape of a media asset id (a UUID; ownership and state are checked by the gateway).
ASSET_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

QR_MIN_SIZE = 128
QR_MAX_SIZE = 2048
