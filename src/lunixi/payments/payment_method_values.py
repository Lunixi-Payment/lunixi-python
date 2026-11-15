"""Value sets and request rules of the payment-method endpoints.

* ``POST /api/v1/payments/direct/payment`` — start a payment with any method
* ``POST /api/v1/payments/{paymentId}/actions/{actionId}/confirm`` — OTP, consent, requested fields
* ``POST /api/v1/payments/{paymentId}/actions/{actionId}/resend`` — a new one-time code
* ``GET  /api/v1/payments/methods[?paymentMethod=]`` — the methods open for the merchant

The gateway refuses a body key outside its schema with 400, so the field lists
below are the gateway's and every SDK checks against the same lists.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from ..errors import ConfigurationError

__all__ = [
    "PaymentMethod",
    "PAYMENT_METHOD_ALIASES",
    "PaymentActionType",
    "ProviderSelection",
    "ProviderSelectionMode",
    "MethodInputFieldType",
    "DIRECT_METHOD_PAYMENT_FIELDS",
    "METHOD_BLOCK_FIELDS",
    "CARD_ONLY_FIELDS",
    "PAYMENT_ACTION_CONFIRM_FIELDS",
    "SHOPPING_LOAN_MAX_BASKET_ITEMS",
    "normalize_payment_method",
    "block_name_of",
    "require_provider_code",
    "require_method_fields",
    "assert_shopping_loan_basket",
]


class PaymentMethod:
    """Public payment method codes (``paymentMethod``).

    ``QR`` is accepted as an alias of :attr:`QR_CODE` and sent as ``QR_CODE``.
    """

    CARD = "CARD"
    BNPL = "BNPL"
    SHOPPING_LOAN = "SHOPPING_LOAN"
    PROMISSORY_NOTE = "PROMISSORY_NOTE"
    MEAL_CARD = "MEAL_CARD"
    GIFT_CARD = "GIFT_CARD"
    CASH = "CASH"
    CASH_ON_DELIVERY = "CASH_ON_DELIVERY"
    WALLET = "WALLET"
    #: Para Transferi: bank transfer (havale / EFT / FAST) to your own bank account.
    BANK_TRANSFER = "BANK_TRANSFER"
    OPEN_BANKING = "OPEN_BANKING"
    #: Faturana Yansıt: the amount is charged to the buyer's mobile phone bill.
    MOBILE_BILLING = "MOBILE_BILLING"
    QR_CODE = "QR_CODE"
    CRYPTO = "CRYPTO"
    OTHER = "OTHER"

    #: Every code above, in catalogue order.
    ALL: Tuple[str, ...] = (
        CARD,
        BNPL,
        SHOPPING_LOAN,
        PROMISSORY_NOTE,
        MEAL_CARD,
        GIFT_CARD,
        CASH,
        CASH_ON_DELIVERY,
        WALLET,
        BANK_TRANSFER,
        OPEN_BANKING,
        MOBILE_BILLING,
        QR_CODE,
        CRYPTO,
        OTHER,
    )


#: Accepted aliases and the code they are sent as.
PAYMENT_METHOD_ALIASES: Mapping[str, str] = {"QR": PaymentMethod.QR_CODE}


class PaymentActionType:
    """What the buyer must do when a payment response carries ``action`` (``action.type``)."""

    #: Send the one-time code with ``payments().confirm_payment_action(..., otp=...)``.
    OTP = "OTP"
    #: Send the buyer to ``action.redirect.url`` (for cards: the bank's 3D Secure page).
    REDIRECT = "REDIRECT"
    #: Show the buyer something to act on outside the page (transfer details, a code).
    DISPLAY = "DISPLAY"
    #: The buyer approves in the provider's app; the result arrives by webhook.
    APP_APPROVAL = "APP_APPROVAL"
    #: Send the fields listed in ``action.input.fields`` with
    #: ``confirm_payment_action(..., fields=...)``.
    INPUT = "INPUT"


class ProviderSelection:
    """``providerSelection`` of a method in ``payments().list_payment_methods()``."""

    #: Card: routing picks the provider; no provider code is sent.
    ROUTED = "ROUTED"
    #: The provider code may be omitted (one provider, or the platform picks it).
    OPTIONAL = "OPTIONAL"
    #: The buyer picks the brand and more than one provider is connected; send the provider code.
    REQUIRED = "REQUIRED"


class ProviderSelectionMode:
    """``providerSelectionMode`` of a method: who picks the provider."""

    #: The buyer picks the brand; with several providers the provider code is required.
    BUYER = "BUYER"
    #: The platform picks one of the connected providers when no provider code is sent.
    PLATFORM = "PLATFORM"


class MethodInputFieldType:
    """Value type of a provider's ``inputFields[].type``."""

    PHONE = "PHONE"
    TCKN = "TCKN"
    EMAIL = "EMAIL"
    DATE = "DATE"
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    SELECT = "SELECT"
    CONSENT = "CONSENT"
    #: 10-digit Turkish tax number.
    VKN = "VKN"
    #: ``{provinceCode, districtCode, neighborhoodCode, line}``; codes from ``client.reference()``.
    ADDRESS = "ADDRESS"
    #: A list of objects, each with the field's ``itemFields``.
    GROUP = "GROUP"


_FIELDS_WITHOUT_BLOCKS: Tuple[str, ...] = (
    "paymentMethod",
    "amount",
    "currency",
    "orderId",
    "paymentChannel",
    "paymentGroup",
    "callbackUrl",
    "locale",
    "description",
    "customerId",
    "preauth",
    "buyer",
    "shippingAddress",
    "billingAddress",
    "basketItems",
    "card",
    "installment",
    "installmentQuoteToken",
    "force3D",
    "metadata",
)

#: Method blocks the gateway accepts besides ``card``. The chosen method's block
#: is required; a block of another method is refused.
METHOD_BLOCK_FIELDS: Tuple[str, ...] = (
    "mobileBilling",
    "wallet",
    "promissoryNote",
    "mealCard",
    "openBanking",
    "shoppingLoan",
    "bankTransfer",
)

#: Body fields of ``POST /payments/direct/payment``.
DIRECT_METHOD_PAYMENT_FIELDS: Tuple[str, ...] = _FIELDS_WITHOUT_BLOCKS + METHOD_BLOCK_FIELDS

#: Fields that belong to a card payment only (``paymentMethod: CARD``).
CARD_ONLY_FIELDS: Tuple[str, ...] = ("card", "installment", "installmentQuoteToken", "force3D")

#: Body fields of an action confirm that a merchant server sends. The hosted
#: form's token fields are never sent with a signed request.
PAYMENT_ACTION_CONFIRM_FIELDS: Tuple[str, ...] = ("otp", "consentAccepted", "fields")

#: Most basket items of a shopping-loan payment; the basket is required.
SHOPPING_LOAN_MAX_BASKET_ITEMS = 100

METHOD_FIELDS_MAX_KEYS = 32
METHOD_FIELD_MAX_VALUE_LENGTH = 1024
METHOD_FIELD_MAX_GROUP_ITEMS = 10
METHOD_FIELD_MAX_NESTED_KEYS = 16
_FIELD_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
_PROVIDER_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_METHOD_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,31}")
_RESERVED_FIELD_KEYS = ("__proto__", "constructor", "prototype")


def normalize_payment_method(value: Any) -> str:
    """Returns the canonical method code; ``QR`` becomes ``QR_CODE``."""
    if not isinstance(value, str) or _METHOD_CODE.fullmatch(value) is None:
        raise ConfigurationError(
            "payment_method must be a payment method code such as "
            f"{PaymentMethod.MOBILE_BILLING}; got {value!r}."
        )
    return PAYMENT_METHOD_ALIASES.get(value, value)


def block_name_of(payment_method: Any) -> str:
    """The method's block name, the camelCase code (``BANK_TRANSFER`` → ``bankTransfer``)."""
    head, *rest = normalize_payment_method(payment_method).lower().split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def require_provider_code(value: Any) -> str:
    if not isinstance(value, str) or _PROVIDER_CODE.fullmatch(value) is None:
        raise ConfigurationError(
            "provider_code must be a provider code from payments().list_payment_methods() "
            f"(letters, digits, _ and -); got {value!r}."
        )
    return value


def _is_scalar(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= METHOD_FIELD_MAX_VALUE_LENGTH
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _require_key(key: Any, path: str) -> None:
    if not isinstance(key, str) or _FIELD_KEY.fullmatch(key) is None or key in _RESERVED_FIELD_KEYS:
        raise ConfigurationError(
            f"{path} has an invalid field name {key!r}: field names start with a letter "
            "and contain only letters and digits."
        )


def _require_nested(value: Mapping[str, Any], path: str) -> None:
    if len(value) > METHOD_FIELD_MAX_NESTED_KEYS:
        raise ConfigurationError(f"{path} can carry at most {METHOD_FIELD_MAX_NESTED_KEYS} fields.")
    for key, entry in value.items():
        _require_key(key, path)
        if not _is_scalar(entry):
            raise ConfigurationError(
                f"{path}.{key} must be a string (at most {METHOD_FIELD_MAX_VALUE_LENGTH} "
                "characters), a number or a boolean."
            )


def _require_value(value: Any, path: str, allow_list: bool) -> None:
    if _is_scalar(value):
        return
    if isinstance(value, Mapping):
        _require_nested(value, path)
        return
    if allow_list and isinstance(value, (list, tuple)):
        if len(value) > METHOD_FIELD_MAX_GROUP_ITEMS:
            raise ConfigurationError(
                f"{path} can carry at most {METHOD_FIELD_MAX_GROUP_ITEMS} items."
            )
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if not isinstance(item, Mapping):
                raise ConfigurationError(f"{item_path} must be an object.")
            if len(item) > METHOD_FIELDS_MAX_KEYS:
                raise ConfigurationError(
                    f"{item_path} can carry at most {METHOD_FIELDS_MAX_KEYS} fields."
                )
            for key, entry in item.items():
                _require_key(key, item_path)
                _require_value(entry, f"{item_path}.{key}", False)
        return
    raise ConfigurationError(
        f"{path} must be a string (at most {METHOD_FIELD_MAX_VALUE_LENGTH} characters), "
        "a number, a boolean, an object or a list of objects."
    )


def require_method_fields(value: Any, path: str) -> Dict[str, Any]:
    """Checks the shape of a method block or of confirm ``fields`` and returns a copy.

    The values themselves are the provider's declaration (``inputFields``) and
    are checked by the gateway; this stops a body refused for its shape alone:
    an object of at most 32 fields named ``[A-Za-z][A-Za-z0-9]{0,63}``, each a
    string (at most 1024 characters), a finite number or a boolean; an object
    of such values (``ADDRESS``, at most 16 fields); or a list of at most 10
    objects (``GROUP``). ``providerCode`` is refused: it is its own argument.
    """
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path} must be an object of field values.")
    if len(value) > METHOD_FIELDS_MAX_KEYS:
        raise ConfigurationError(f"{path} can carry at most {METHOD_FIELDS_MAX_KEYS} fields.")
    for key, entry in value.items():
        if key == "providerCode":
            raise ConfigurationError(
                f"{path} must not carry providerCode; pass it as its own argument."
            )
        _require_key(key, path)
        _require_value(entry, f"{path}.{key}", True)
    return {key: _copy(entry) for key, entry in value.items()}


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy(entry) for entry in value]
    return value


def assert_shopping_loan_basket(payment_method: str, basket_items: Optional[Any]) -> None:
    """A shopping-loan payment needs 1 to 100 basket items: the bank sets the term from them."""
    if payment_method != PaymentMethod.SHOPPING_LOAN:
        return
    if not isinstance(basket_items, (list, tuple)) or len(basket_items) == 0:
        raise ConfigurationError(
            "paymentMethod SHOPPING_LOAN requires basketItems: the bank sets the loan term "
            "from the basket."
        )
    if len(basket_items) > SHOPPING_LOAN_MAX_BASKET_ITEMS:
        raise ConfigurationError(
            f"paymentMethod SHOPPING_LOAN takes at most {SHOPPING_LOAN_MAX_BASKET_ITEMS} "
            f"basket items; got {len(basket_items)}."
        )
