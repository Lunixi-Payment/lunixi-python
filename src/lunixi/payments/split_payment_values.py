"""Split payments: one payment funded by several legs.

A leg is a stored card or, when split payments with other methods are enabled
in your form settings, a non-card method (mobile billing, wallet, promissory
note).

* ``POST /api/v1/payments/split`` — create, and continue after a step
* ``GET  /api/v1/payments/split/{splitPaymentId}`` — detail with legs
* ``GET  /api/v1/payments/split`` — list, forward cursor
* ``POST /api/v1/payments/split/{splitPaymentId}/refund`` — refund of the main payment

The platform sets the order of the legs and returns it as ``steps``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Set, Tuple

from ..errors import ConfigurationError
from ..validation import amount_minor
from .payment_method_values import (
    PaymentMethod,
    block_name_of,
    normalize_payment_method,
    require_method_fields,
    require_provider_code,
)
from .promissory_note_values import require_note_count

__all__ = [
    "SplitPaymentStatus",
    "SPLIT_PAYMENT_IN_PROGRESS_STATUSES",
    "SplitPendingStep",
    "SplitPaymentEvents",
    "SPLIT_LEG_EVENTS_SUBSCRIPTION",
    "SPLIT_PAYMENT_FIELDS",
    "SPLIT_LEG_BLOCK_FIELDS",
    "SPLIT_PAYMENT_LEG_FIELDS",
    "LIST_SPLIT_PAYMENTS_FILTERS",
    "SPLIT_MIN_LEGS",
    "SPLIT_MAX_LEGS",
    "SPLIT_IDEMPOTENCY_KEY_MAX_LENGTH",
    "assert_split_payment_payload",
    "list_split_payments_query",
    "is_running_split_response",
]


class SplitPaymentStatus:
    """Status of a split payment (``status``)."""

    COMPOSING = "COMPOSING"
    AUTHORIZING = "AUTHORIZING"
    #: A card leg waits for the buyer's 3D Secure step (``pendingStep.redirectPath``).
    AWAITING_3DS = "AWAITING_3DS"
    #: A non-card leg waits for a step (``pendingStep``).
    AWAITING_ACTION = "AWAITING_ACTION"
    #: A credit leg waits for the lender's approval; no money has moved.
    AWAITING_CREDIT_APPROVAL = "AWAITING_CREDIT_APPROVAL"
    #: A card capture failed after the non-reversible leg; a new card is asked for the shortfall.
    AWAITING_REPLACEMENT_CARD = "AWAITING_REPLACEMENT_CARD"
    AUTHORIZED = "AUTHORIZED"
    CAPTURING = "CAPTURING"
    #: Every leg was charged: the order is paid.
    COMPLETED = "COMPLETED"
    #: A leg failed: holds are released and charged legs are refunded.
    COMPENSATING = "COMPENSATING"
    #: Failed without a charge left on any leg.
    VOIDED = "VOIDED"
    FAILED = "FAILED"
    #: The non-reversible leg was charged but the rest could not be collected.
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

    ALL: Tuple[str, ...] = (
        COMPOSING,
        AUTHORIZING,
        AWAITING_3DS,
        AWAITING_ACTION,
        AWAITING_CREDIT_APPROVAL,
        AWAITING_REPLACEMENT_CARD,
        AUTHORIZED,
        CAPTURING,
        COMPLETED,
        COMPENSATING,
        VOIDED,
        FAILED,
        RECONCILIATION_REQUIRED,
    )


#: Statuses in which the split payment is still running. The gateway answers
#: them with HTTP 400 and the status as ``code``;
#: ``payments().create_split_payment()`` returns that answer instead of raising.
SPLIT_PAYMENT_IN_PROGRESS_STATUSES: Tuple[str, ...] = (
    SplitPaymentStatus.COMPOSING,
    SplitPaymentStatus.AUTHORIZING,
    SplitPaymentStatus.AWAITING_3DS,
    SplitPaymentStatus.AWAITING_ACTION,
    SplitPaymentStatus.AWAITING_CREDIT_APPROVAL,
    SplitPaymentStatus.AWAITING_REPLACEMENT_CARD,
    SplitPaymentStatus.AUTHORIZED,
    SplitPaymentStatus.CAPTURING,
)


class SplitPendingStep:
    """What the split payment waits for (``pendingStep.step``)."""

    #: Send the buyer to ``pendingStep.redirectPath`` (card 3D Secure).
    THREE_DS = "THREE_DS"
    #: Send the same request again with the same idempotency key.
    START_METHOD = "START_METHOD"
    #: Complete the action with ``confirm_payment_action()`` (``pendingStep.paymentId``,
    #: ``pendingStep.actionId``), then send the same request again.
    ACTION = "ACTION"
    #: The result is being confirmed; read the split payment again later.
    RESULT_PENDING = "RESULT_PENDING"
    #: The lender's approval is awaited.
    CREDIT_APPROVAL = "CREDIT_APPROVAL"
    #: The buyer enters a card after the credit approval (Checkout Form).
    CARD_INPUT = "CARD_INPUT"
    #: The buyer enters a new card for the shortfall (Checkout Form).
    REPLACEMENT_CARD = "REPLACEMENT_CARD"


class SplitPaymentEvents:
    """Webhook event types of a split payment.

    The result of the main payment arrives as ``payment.captured`` /
    ``payment.failed`` with ``settlementMode: "SPLIT"`` and ``legs[]``; deliver
    the order on that event.
    """

    COMPLETED = "payment.split.completed"
    VOIDED = "payment.split.voided"
    COMPENSATING = "payment.split.compensating"
    #: The non-reversible leg's result is being confirmed; card holds are kept until then.
    OUTCOME_PENDING = "payment.split.outcome_pending"
    #: The order could not be fully collected (``shortfallAmountMinor``, ``reason``).
    RECONCILIATION_REQUIRED = "payment.split.reconciliation_required"
    #: Leg event: a charged leg is being refunded and retried until it succeeds.
    LEG_REFUND_PENDING = "payment.split.leg_refund_pending"


#: Add this key to a webhook endpoint's event types to also receive the events
#: of each leg. It is not an event type and ``payment.*`` does not include it.
SPLIT_LEG_EVENTS_SUBSCRIPTION = "payment.split.leg_events"

#: Body fields of ``POST /payments/split``.
SPLIT_PAYMENT_FIELDS: Tuple[str, ...] = (
    "totalAmount",
    "currency",
    "ownerRef",
    "legs",
    "orderId",
    "ownerScope",
    "callbackUrl",
)

#: Method blocks a non-card leg can carry. Meal card, open banking, shopping
#: loan and bank transfer cannot be split payment legs.
SPLIT_LEG_BLOCK_FIELDS: Tuple[str, ...] = ("mobileBilling", "wallet", "promissoryNote")

#: Fields of one leg.
SPLIT_PAYMENT_LEG_FIELDS: Tuple[str, ...] = (
    "paymentMethod",
    "cardToken",
    "amount",
    "force3D",
    "installment",
    "installmentQuoteToken",
) + SPLIT_LEG_BLOCK_FIELDS

_SPLIT_CARD_LEG_ONLY_FIELDS = ("cardToken", "force3D", "installmentQuoteToken")

#: Filters of ``GET /payments/split``.
LIST_SPLIT_PAYMENTS_FILTERS: Tuple[str, ...] = (
    "status",
    "currency",
    "createdFrom",
    "createdTo",
    "orderId",
    "ownerRef",
    "limit",
    "after",
)

SPLIT_MIN_LEGS = 1
SPLIT_MAX_LEGS = 5
SPLIT_LEG_MAX_INSTALLMENT = 36
#: Longest idempotency key the gateway accepts on the split endpoints.
SPLIT_IDEMPOTENCY_KEY_MAX_LENGTH = 200
_CARD_TOKEN_MAX_LENGTH = 256
_QUOTE_TOKEN_MAX_LENGTH = 4096
_CALLBACK_URL_MAX_LENGTH = 2048
_LIST_MAX_LIMIT = 100
_LIST_MAX_VALUES = 20
_FILTER_TEXT_MAX_LENGTH = 200
_OWNER_SCOPES = ("MERCHANT_CUSTOMER",)
_CURRENCY = re.compile(r"[A-Z]{3}")
_ISO_8601 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,9})?)?(Z|[+-][0-9]{2}:?[0-9]{2})?)?"
)


def _given(value: Any) -> bool:
    return value is not None


def _bounded_text(value: Any, path: str, max_length: int) -> str:
    if not isinstance(value, str) or value.strip() == "" or len(value) > max_length:
        raise ConfigurationError(
            f"{path} must be a non-empty string of at most {max_length} characters."
        )
    return value


def _is_card_leg(leg: Mapping[str, Any]) -> bool:
    method = leg.get("paymentMethod")
    return method is None or method == "" or method == PaymentMethod.CARD


def _assert_card_leg(leg: Mapping[str, Any], path: str) -> None:
    _bounded_text(leg.get("cardToken"), f"{path}.cardToken", _CARD_TOKEN_MAX_LENGTH)
    block = next((name for name in SPLIT_LEG_BLOCK_FIELDS if _given(leg.get(name))), None)
    if block:
        raise ConfigurationError(f"{path} is a card leg and cannot carry the '{block}' block.")
    force3d = leg.get("force3D")
    if _given(force3d) and not isinstance(force3d, bool):
        raise ConfigurationError(f"{path}.force3D must be a boolean; got {force3d!r}.")
    installment = leg.get("installment")
    if _given(installment) and (
        isinstance(installment, bool)
        or not isinstance(installment, int)
        or not 1 <= installment <= SPLIT_LEG_MAX_INSTALLMENT
    ):
        raise ConfigurationError(
            f"{path}.installment must be an integer from 1 to {SPLIT_LEG_MAX_INSTALLMENT}; "
            f"got {installment!r}."
        )
    quote = leg.get("installmentQuoteToken")
    if _given(quote):
        _bounded_text(quote, f"{path}.installmentQuoteToken", _QUOTE_TOKEN_MAX_LENGTH)
    if isinstance(installment, int) and installment >= 2 and not _given(quote):
        raise ConfigurationError(
            f"{path}: an installment of 2 or more needs installmentQuoteToken "
            "(POST /bin/installments with this leg's amount)."
        )


def _assert_method_leg(leg: Mapping[str, Any], path: str) -> str:
    """Checks a non-card leg and returns its provider code."""
    method = normalize_payment_method(leg.get("paymentMethod"))
    block_name = block_name_of(method)
    if block_name not in SPLIT_LEG_BLOCK_FIELDS:
        raise ConfigurationError(
            f"{path}: paymentMethod {method} cannot be a split payment leg; a non-card leg "
            f"carries one of the blocks {', '.join(SPLIT_LEG_BLOCK_FIELDS)}."
        )
    card_field = next((name for name in _SPLIT_CARD_LEG_ONLY_FIELDS if _given(leg.get(name))), None)
    if card_field:
        raise ConfigurationError(f"{path}: {card_field} can only be sent with a card leg.")
    if _given(leg.get("installment")) and leg.get("installment") != 1:
        raise ConfigurationError(f"{path}: installment can only be sent with a card leg.")
    other = next(
        (n for n in SPLIT_LEG_BLOCK_FIELDS if n != block_name and _given(leg.get(n))), None
    )
    if other:
        raise ConfigurationError(
            f"{path}: paymentMethod {method} takes only the '{block_name}' block; "
            f"'{other}' must not be sent."
        )
    block = leg.get(block_name)
    if not isinstance(block, Mapping):
        raise ConfigurationError(
            f"{path}: paymentMethod {method} requires the '{block_name}' block."
        )
    provider_code = block.get("providerCode")
    if provider_code is None:
        raise ConfigurationError(
            f"{path}.{block_name}.providerCode is required in a split payment leg (a provider "
            "with splitEligible: true from payments().list_payment_methods())."
        )
    require_provider_code(provider_code)
    fields = {key: value for key, value in block.items() if key != "providerCode"}
    require_method_fields(fields, f"{path}.{block_name}")
    if method == PaymentMethod.PROMISSORY_NOTE:
        if _given(fields.get("schedule")):
            raise ConfigurationError(
                f"{path}.{block_name}.schedule cannot be sent in a split payment leg; give "
                "the number of notes with noteCount."
            )
        require_note_count(fields.get("noteCount"), f"{path}.{block_name}.noteCount")
    return provider_code


def assert_split_payment_payload(body: Any) -> None:
    """Checks a ``POST /payments/split`` body before sending.

    Known fields only, 1–5 legs, canonical minor-unit amounts that add up to
    ``totalAmount``, a card leg with ``cardToken`` and no method block, a
    non-card leg with exactly its own block (``mobileBilling``, ``wallet`` or
    ``promissoryNote``, with ``providerCode``) and no card fields, one leg per
    provider and per card, ``callbackUrl`` when a card leg uses 3D Secure.
    """
    if not isinstance(body, Mapping):
        raise ConfigurationError(
            "A split payment needs a body. Use SplitPaymentRequest to build it."
        )
    unknown = [key for key in body if key not in SPLIT_PAYMENT_FIELDS]
    if unknown:
        raise ConfigurationError(f"Unknown split payment field(s): {', '.join(map(str, unknown))}.")
    total = amount_minor(body.get("totalAmount"))
    currency = body.get("currency")
    if not isinstance(currency, str) or _CURRENCY.fullmatch(currency) is None:
        raise ConfigurationError(
            f"currency must be an ISO 4217 code such as TRY; got {currency!r}."
        )
    owner_ref = body.get("ownerRef")
    if not isinstance(owner_ref, str) or owner_ref.strip() == "":
        raise ConfigurationError("ownerRef must be a non-empty string.")
    order_id = body.get("orderId")
    if _given(order_id) and (not isinstance(order_id, str) or order_id.strip() == ""):
        raise ConfigurationError("orderId must be a non-empty string.")
    scope = body.get("ownerScope")
    if _given(scope) and scope not in _OWNER_SCOPES:
        raise ConfigurationError(
            f"ownerScope can only be {', '.join(_OWNER_SCOPES)}; got {scope!r}."
        )
    callback_url = body.get("callbackUrl")
    if _given(callback_url):
        _bounded_text(callback_url, "callbackUrl", _CALLBACK_URL_MAX_LENGTH)
        if re.match(r"https?://", str(callback_url), re.IGNORECASE) is None:
            raise ConfigurationError(f"callbackUrl must be an http(s) URL; got {callback_url!r}.")
    legs = body.get("legs")
    if not isinstance(legs, (list, tuple)) or not SPLIT_MIN_LEGS <= len(legs) <= SPLIT_MAX_LEGS:
        raise ConfigurationError(
            f"legs must be a list of {SPLIT_MIN_LEGS} to {SPLIT_MAX_LEGS} legs."
        )
    providers: Set[str] = set()
    card_tokens: Set[str] = set()
    legs_total = 0
    for index, leg in enumerate(legs):
        path = f"legs[{index}]"
        if not isinstance(leg, Mapping):
            raise ConfigurationError(f"{path} must be an object.")
        unknown_leg = [key for key in leg if key not in SPLIT_PAYMENT_LEG_FIELDS]
        if unknown_leg:
            raise ConfigurationError(
                f"Unknown {path} field(s): {', '.join(map(str, unknown_leg))}."
            )
        legs_total += int(amount_minor(leg.get("amount")))
        if _is_card_leg(leg):
            _assert_card_leg(leg, path)
            if leg["cardToken"] in card_tokens:
                raise ConfigurationError(f"{path}: the same card is used in more than one leg.")
            card_tokens.add(leg["cardToken"])
            continue
        provider_code = _assert_method_leg(leg, path)
        if provider_code in providers:
            raise ConfigurationError(
                f"{path}: provider {provider_code} is used in more than one leg; "
                "one leg per provider."
            )
        providers.add(provider_code)
    if legs_total != int(total):
        raise ConfigurationError(
            f"The legs add up to {legs_total} but totalAmount is {total}; they must be equal."
        )
    if any(leg.get("force3D") is True for leg in legs) and not _given(callback_url):
        raise ConfigurationError(
            "callbackUrl is required when a card leg uses 3D Secure (force3D: true)."
        )


def _filter_values(value: Any, field: str) -> list:
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    if not 1 <= len(values) <= _LIST_MAX_VALUES:
        raise ConfigurationError(f"{field} takes 1 to {_LIST_MAX_VALUES} values.")
    return values


def list_split_payments_query(filters: Mapping[str, Any]) -> Dict[str, Any]:
    """Checks the filters of ``GET /payments/split`` and returns the query.

    ``status`` and ``currency`` may be a value or a list; a list is sent as
    repeated parameters (``?status=COMPLETED&status=VOIDED``).
    """
    unknown = [key for key in filters if key not in LIST_SPLIT_PAYMENTS_FILTERS]
    if unknown:
        raise ConfigurationError(
            f"list_splits does not take {', '.join(map(str, unknown))}; filters: "
            f"{', '.join(LIST_SPLIT_PAYMENTS_FILTERS)}."
        )
    query: Dict[str, Any] = {}
    for key in LIST_SPLIT_PAYMENTS_FILTERS:
        value = filters.get(key)
        if value is None or value == "":
            continue
        if key == "status":
            values = _filter_values(value, key)
            for entry in values:
                if entry not in SplitPaymentStatus.ALL:
                    raise ConfigurationError(
                        f"status must be one of {', '.join(SplitPaymentStatus.ALL)}; got {entry!r}."
                    )
            query[key] = values
        elif key == "currency":
            values = _filter_values(value, key)
            for entry in values:
                if not isinstance(entry, str) or _CURRENCY.fullmatch(entry) is None:
                    raise ConfigurationError(f"currency must be an ISO 4217 code; got {entry!r}.")
            query[key] = values
        elif key in ("createdFrom", "createdTo"):
            if not isinstance(value, str) or _ISO_8601.fullmatch(value) is None:
                raise ConfigurationError(f"{key} must be an ISO 8601 date-time; got {value!r}.")
            query[key] = value
        elif key == "limit":
            digits = isinstance(value, str) and value.isascii() and value.isdigit()
            number = int(value) if digits else value
            if (
                isinstance(number, bool)
                or not isinstance(number, int)
                or not 1 <= number <= _LIST_MAX_LIMIT
            ):
                raise ConfigurationError(
                    f"limit must be an integer from 1 to {_LIST_MAX_LIMIT}; got {value!r}."
                )
            query[key] = str(number)
        else:
            query[key] = _bounded_text(
                value, key, 2048 if key == "after" else _FILTER_TEXT_MAX_LENGTH
            )
    return query


def is_running_split_response(status_code: int, body: Mapping[str, Any]) -> bool:
    """True for the gateway's HTTP 400 answer to a split payment that is still running.

    Only a body that is the split payment itself (``data.splitPaymentId``) with
    a running status as ``code`` qualifies; that answer is a result, not an error.
    """
    if status_code != 400 or body.get("code") not in SPLIT_PAYMENT_IN_PROGRESS_STATUSES:
        return False
    data = body.get("data")
    return (
        isinstance(data, Mapping)
        and isinstance(data.get("splitPaymentId"), str)
        and data["splitPaymentId"] != ""
    )
