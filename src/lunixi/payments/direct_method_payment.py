"""Body of ``POST /api/v1/payments/direct/payment``: a payment with any method.

Build it with :class:`DirectMethodPaymentRequest`; a raw mapping passed to
``payments().direct_method_payment()`` is checked with the same rules by
:func:`assert_direct_method_payment_payload` before anything is sent.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from ..errors import ConfigurationError
from ..validation import amount_minor, currency_code, validate_money_fields
from .payment_method_values import (
    CARD_ONLY_FIELDS,
    DIRECT_METHOD_PAYMENT_FIELDS,
    METHOD_BLOCK_FIELDS,
    PaymentMethod,
    assert_shopping_loan_basket,
    block_name_of,
    normalize_payment_method,
    require_method_fields,
    require_provider_code,
)
from .promissory_note_values import (
    assert_promissory_note_plan,
    require_note_count,
    require_promissory_note_schedule,
)

__all__ = ["DirectMethodPaymentRequest", "assert_direct_method_payment_payload"]


def _text(value: Any, field: str, max_length: int = 2048) -> str:
    if (
        not isinstance(value, str)
        or value.strip() == ""
        or len(value) > max_length
        or any(ord(c) < 32 for c in value)
    ):
        raise ConfigurationError(
            f"{field} must be a non-empty string of at most {max_length} characters."
        )
    return value


def _callback_url(value: Any) -> str:
    _text(value, "callback_url")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or "#" in value
        or any(ord(c) <= 32 for c in value)
    ):
        raise ConfigurationError("callback_url must be a trusted HTTPS URL.")
    return value


def _object(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{field} must be an object.")
    return dict(value)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{field} must be a boolean; got {value!r}.")
    return value


def _installment(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(f"installment must be a positive integer; got {value!r}.")
    return value


class DirectMethodPaymentRequest:
    """Builder for ``payments().direct_method_payment()``.

    .. code-block:: python

        request = (
            DirectMethodPaymentRequest("15000", "TRY", "order-1001")
            .with_method_fields(PaymentMethod.MOBILE_BILLING, provider_code,
                                {"gsmNumber": "+905321234567"})
            .with_callback_url("https://shop.example/return/order-1001")
        )

    Choose the method with :meth:`with_method_fields` (any method other than
    card) or :meth:`with_card`. The provider code comes from
    ``payments().list_payment_methods()``. :meth:`to_dict` checks the request
    and returns the body that is signed and sent.
    """

    def __init__(self, amount: str, currency: str, order_id: str) -> None:
        self._payload: Dict[str, Any] = {
            "amount": amount_minor(amount),
            "currency": currency_code(currency),
            "orderId": _text(order_id, "order_id", 128),
        }
        self._payment_method: Optional[str] = None
        self._block: Optional[Dict[str, Any]] = None
        self._promissory_note_plan: Optional[Dict[str, Any]] = None

    def with_method_fields(
        self,
        payment_method: str,
        provider_code: Optional[str],
        fields: Optional[Mapping[str, Any]] = None,
    ) -> DirectMethodPaymentRequest:
        """Pays with a method other than card.

        ``fields`` are the provider's ``inputFields`` values; ``{}`` (or
        ``None``) when the provider asks for nothing. ``provider_code`` is
        required when the method lists more than one provider
        (``providerSelection: REQUIRED``); ``None`` otherwise. A
        ``BANK_TRANSFER`` payment takes no provider code: pass ``None`` and the
        buyer's bank as ``{"bankCode": ...}``.
        """
        code = normalize_payment_method(payment_method)
        if code == PaymentMethod.CARD:
            raise ConfigurationError("Use with_card(card) to pay by card.")
        block_name = block_name_of(code)
        if block_name not in METHOD_BLOCK_FIELDS:
            raise ConfigurationError(
                f"paymentMethod {code} cannot be paid through direct/payment yet; "
                "payments().list_payment_methods() lists the methods that can."
            )
        block = require_method_fields({} if fields is None else fields, block_name)
        if code == PaymentMethod.PROMISSORY_NOTE and "schedule" in block:
            raise ConfigurationError(
                "Pass the promissory-note schedule with with_promissory_note_schedule(rows), "
                "not in the fields."
            )
        if code == PaymentMethod.PROMISSORY_NOTE and "noteCount" in block:
            block["noteCount"] = require_note_count(block["noteCount"])
        if code == PaymentMethod.BANK_TRANSFER and provider_code is not None:
            raise ConfigurationError(
                "paymentMethod BANK_TRANSFER takes no provider_code: pass None and the buyer's "
                "bank as {'bankCode': ...}."
            )
        self._payment_method = code
        self._block = (
            block
            if provider_code is None
            else {"providerCode": require_provider_code(provider_code), **block}
        )
        return self

    def with_promissory_note_schedule(
        self, schedule: Sequence[Mapping[str, Any]]
    ) -> DirectMethodPaymentRequest:
        """Senetle Ödeme plan, one note per row ``{"amount", "dueDate"}``; replaces a note count.

        Amounts are canonical minor-unit strings adding up to ``amount``; due
        dates are ``YYYY-MM-DD`` in ascending order; at most 24 rows.
        """
        self._promissory_note_plan = {"schedule": require_promissory_note_schedule(schedule)}
        return self

    def with_promissory_note_count(self, count: Any) -> DirectMethodPaymentRequest:
        """Senetle Ödeme plan: the number of notes (1–24); replaces a schedule."""
        self._promissory_note_plan = {"noteCount": require_note_count(count)}
        return self

    def with_card(self, card: Mapping[str, Any]) -> DirectMethodPaymentRequest:
        """Pays by card: new card fields, or ``cardUserKey`` + ``cardToken`` of a stored card."""
        if not isinstance(card, Mapping) or len(card) == 0:
            raise ConfigurationError("with_card requires a non-empty card object.")
        self._payment_method = PaymentMethod.CARD
        self._block = dict(card)
        return self

    def with_installment(
        self, count: int, quote_token: Optional[str] = None
    ) -> DirectMethodPaymentRequest:
        """Card only. ``quote_token`` binds the charge to a quote from the installment options."""
        self._payload["installment"] = _installment(count)
        if quote_token is not None:
            self._payload["installmentQuoteToken"] = _text(
                quote_token, "installment_quote_token", 4096
            )
        return self

    def with_force3d(self, value: bool) -> DirectMethodPaymentRequest:
        """Card only. ``True`` charges with 3D Secure (the response carries a REDIRECT action)."""
        self._payload["force3D"] = _boolean(value, "force3D")
        return self

    def with_preauth(self, value: bool) -> DirectMethodPaymentRequest:
        """``True`` holds the amount (``AUTHORIZED``); capture or void it later."""
        self._payload["preauth"] = _boolean(value, "preauth")
        return self

    def with_callback_url(self, value: str) -> DirectMethodPaymentRequest:
        """Where the buyer's browser returns after a ``REDIRECT`` action."""
        self._payload["callbackUrl"] = _callback_url(value)
        return self

    def with_locale(self, value: str) -> DirectMethodPaymentRequest:
        self._payload["locale"] = _text(value, "locale", 16)
        return self

    def with_description(self, value: str) -> DirectMethodPaymentRequest:
        self._payload["description"] = _text(value, "description")
        return self

    def with_customer_id(self, value: str) -> DirectMethodPaymentRequest:
        self._payload["customerId"] = _text(value, "customer_id", 200)
        return self

    def with_payment_channel(self, value: str) -> DirectMethodPaymentRequest:
        self._payload["paymentChannel"] = _text(value, "payment_channel", 64)
        return self

    def with_payment_group(self, value: str) -> DirectMethodPaymentRequest:
        self._payload["paymentGroup"] = _text(value, "payment_group", 64)
        return self

    def with_buyer(self, value: Mapping[str, Any]) -> DirectMethodPaymentRequest:
        self._payload["buyer"] = _object(value, "buyer")
        return self

    def with_billing_address(self, value: Mapping[str, Any]) -> DirectMethodPaymentRequest:
        self._payload["billingAddress"] = _object(value, "billing_address")
        return self

    def with_shipping_address(self, value: Mapping[str, Any]) -> DirectMethodPaymentRequest:
        self._payload["shippingAddress"] = _object(value, "shipping_address")
        return self

    def with_basket_items(self, items: Sequence[Mapping[str, Any]]) -> DirectMethodPaymentRequest:
        """Basket items; ``SHOPPING_LOAN`` requires 1 to 100 of them."""
        if not isinstance(items, (list, tuple)):
            raise ConfigurationError("basket_items must be a list.")
        self._payload["basketItems"] = [_object(item, "basket_items[]") for item in items]
        return self

    def with_metadata(self, value: Mapping[str, Any]) -> DirectMethodPaymentRequest:
        self._payload["metadata"] = _object(value, "metadata")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Checks the request and returns the body."""
        if self._payment_method is None or self._block is None:
            raise ConfigurationError(
                "Choose the payment method with with_method_fields(method, provider_code, "
                "fields) or with_card(card)."
            )
        if self._payment_method != PaymentMethod.CARD:
            card_field = next((f for f in CARD_ONLY_FIELDS if f in self._payload), None)
            if card_field:
                raise ConfigurationError(
                    f"{card_field} can only be sent with a card payment (with_card)."
                )
        block = dict(self._block)
        if self._payment_method == PaymentMethod.PROMISSORY_NOTE:
            if self._promissory_note_plan is not None:
                if "noteCount" in block:
                    raise ConfigurationError(
                        "The promissory-note plan is given twice: noteCount in the fields and "
                        "with_promissory_note_schedule()/with_promissory_note_count(). Use one."
                    )
                block.update(self._promissory_note_plan)
        elif self._promissory_note_plan is not None:
            raise ConfigurationError(
                "A promissory-note plan can only be sent with paymentMethod PROMISSORY_NOTE."
            )
        if self._payment_method == PaymentMethod.CARD:
            block_name = "card"
        else:
            block_name = block_name_of(self._payment_method)
        body = {"paymentMethod": self._payment_method, **self._payload, block_name: block}
        assert_direct_method_payment_payload(body)
        return body


def _given(payload: Mapping[str, Any], field: str) -> bool:
    return payload.get(field) is not None


def _assert_method_block(method: str, block_name: str, block: Any) -> None:
    if not isinstance(block, Mapping):
        raise ConfigurationError(f"{block_name} must be an object.")
    provider_code = block.get("providerCode")
    if "providerCode" in block:
        if method == PaymentMethod.BANK_TRANSFER:
            raise ConfigurationError(
                "paymentMethod BANK_TRANSFER takes no providerCode in the bankTransfer block."
            )
        require_provider_code(provider_code)
    fields = {
        key: value
        for key, value in block.items()
        if key != "providerCode"
        and not (method == PaymentMethod.PROMISSORY_NOTE and key == "schedule")
    }
    require_method_fields(fields, block_name)


def assert_direct_method_payment_payload(payload: Any) -> None:
    """Checks a ``POST /payments/direct/payment`` body with the gateway's rules.

    No removed amount fields (``price``, ``paidPrice``); known fields only;
    ``paymentMethod``, ``amount``, ``currency`` and ``orderId`` present; card
    fields only with ``CARD``; exactly the chosen method's block (``card`` for
    a card) and no other; the block's shape; the promissory-note plan; the
    shopping-loan basket (1–100 items); no ``providerCode`` in a
    ``bankTransfer`` block; ``preauth`` and ``force3D`` booleans.
    """
    if not isinstance(payload, Mapping):
        raise ConfigurationError(
            "A direct method payment needs a body. Use DirectMethodPaymentRequest to build it."
        )
    if "price" in payload or "paidPrice" in payload:
        raise ConfigurationError(
            "price, paidPrice: removed from the payment body; send the amount only in 'amount' "
            "(minor units)."
        )
    validate_money_fields(dict(payload))
    unknown = [key for key in payload if key not in DIRECT_METHOD_PAYMENT_FIELDS]
    if unknown:
        raise ConfigurationError(
            f"Unknown direct method payment field(s): {', '.join(map(str, unknown))}."
        )
    for field in ("paymentMethod", "amount", "currency", "orderId"):
        if payload.get(field) is None or payload.get(field) == "":
            raise ConfigurationError(
                f"Direct method payments require '{field}'. Use DirectMethodPaymentRequest to "
                "build the request."
            )
    amount_minor(payload["amount"])
    currency_code(payload["currency"])
    method = normalize_payment_method(payload["paymentMethod"])
    own_block = "card" if method == PaymentMethod.CARD else block_name_of(method)
    if own_block != "card" and own_block not in METHOD_BLOCK_FIELDS:
        raise ConfigurationError(
            f"paymentMethod {method} cannot be paid through direct/payment yet; "
            "payments().list_payment_methods() lists the methods that can."
        )
    if method != PaymentMethod.CARD:
        card_field = next((f for f in CARD_ONLY_FIELDS if _given(payload, f)), None)
        if card_field:
            raise ConfigurationError(f"{card_field} can only be sent with paymentMethod CARD.")
    other_block = next(
        (f for f in METHOD_BLOCK_FIELDS if f != own_block and _given(payload, f)), None
    )
    if other_block:
        raise ConfigurationError(
            f"paymentMethod {method} takes only the '{own_block}' block; "
            f"'{other_block}' must not be sent."
        )
    if not _given(payload, own_block):
        raise ConfigurationError(f"paymentMethod {method} requires the '{own_block}' block.")
    if own_block == "card":
        if not isinstance(payload["card"], Mapping) or len(payload["card"]) == 0:
            raise ConfigurationError("card must be a non-empty object.")
    else:
        _assert_method_block(method, own_block, payload[own_block])
    if method == PaymentMethod.PROMISSORY_NOTE:
        assert_promissory_note_plan(payload["promissoryNote"], payload["amount"])
    assert_shopping_loan_basket(method, payload.get("basketItems"))
    if "preauth" in payload:
        _boolean(payload["preauth"], "preauth")
    if "force3D" in payload and payload["force3D"] is not None:
        _boolean(payload["force3D"], "force3D")
    installment = payload.get("installment")
    if installment is not None:
        _installment(installment)

