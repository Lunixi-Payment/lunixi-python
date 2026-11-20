"""Body of ``POST /api/v1/payments/split``."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ..errors import ConfigurationError
from .payment_method_values import (
    PaymentMethod,
    block_name_of,
    normalize_payment_method,
    require_method_fields,
    require_provider_code,
)
from .promissory_note_values import require_note_count
from .split_payment_values import SPLIT_LEG_BLOCK_FIELDS, assert_split_payment_payload

__all__ = ["SplitPaymentRequest"]


class SplitPaymentRequest:
    """Builder for ``payments().create_split_payment()``.

    .. code-block:: python

        request = (
            SplitPaymentRequest("30000", "TRY", "customer-42")
            .with_order_id("order-1001")
            .with_buyer(buyer)
            .with_billing_address(billing_address)
            .with_basket_items(basket_items)
            .add_card_leg(stored_card_token, "20000")
            .add_method_leg(PaymentMethod.WALLET, provider_code, "10000", {})
        )

    ``owner_ref`` is your reference of the buyer whose stored cards are used.
    A non-card leg takes a provider with ``splitEligible: true`` from
    ``payments().list_payment_methods()`` and only the methods with a block in
    ``SPLIT_LEG_BLOCK_FIELDS`` (mobile billing, wallet, promissory note).
    """

    def __init__(self, total_amount: str, currency: str, owner_ref: str) -> None:
        self._payload: Dict[str, Any] = {
            "totalAmount": total_amount,
            "currency": currency,
            "ownerRef": owner_ref,
        }
        self._legs: List[Dict[str, Any]] = []

    def with_order_id(self, value: str) -> SplitPaymentRequest:
        self._payload["orderId"] = value
        return self

    def with_buyer(self, value: Mapping[str, Any]) -> SplitPaymentRequest:
        """The buyer (required). Every leg goes to the payment provider with it."""
        self._payload["buyer"] = dict(value)
        return self

    def with_billing_address(self, value: Mapping[str, Any]) -> SplitPaymentRequest:
        """The billing address (required)."""
        self._payload["billingAddress"] = dict(value)
        return self

    def with_shipping_address(self, value: Mapping[str, Any]) -> SplitPaymentRequest:
        """The shipping address; required when a basket item is ``PHYSICAL``."""
        self._payload["shippingAddress"] = dict(value)
        return self

    def with_basket_items(self, items: List[Mapping[str, Any]]) -> SplitPaymentRequest:
        """Basket items (at least one); their ``price`` values add up to ``total_amount``."""
        if not isinstance(items, (list, tuple)):
            raise ConfigurationError("basket_items must be a list.")
        self._payload["basketItems"] = [dict(item) for item in items]
        return self

    def with_callback_url(self, value: str) -> SplitPaymentRequest:
        """Where the buyer returns after a card leg's 3D Secure step; required with ``force3d``."""
        self._payload["callbackUrl"] = value
        return self

    def add_card_leg(
        self,
        card_token: str,
        amount: str,
        *,
        force3d: Optional[bool] = None,
        installment: Optional[int] = None,
        installment_quote_token: Optional[str] = None,
    ) -> SplitPaymentRequest:
        """A stored card leg (``cardToken`` of a card saved for ``owner_ref``)."""
        leg: Dict[str, Any] = {"cardToken": card_token, "amount": amount}
        if force3d is not None:
            leg["force3D"] = force3d
        if installment is not None:
            leg["installment"] = installment
        if installment_quote_token is not None:
            leg["installmentQuoteToken"] = installment_quote_token
        self._legs.append(leg)
        return self

    def add_method_leg(
        self,
        payment_method: str,
        provider_code: str,
        amount: str,
        fields: Optional[Mapping[str, Any]] = None,
    ) -> SplitPaymentRequest:
        """A non-card leg with its provider code and the provider's ``inputFields`` values."""
        code = normalize_payment_method(payment_method)
        if code == PaymentMethod.CARD:
            raise ConfigurationError("Use add_card_leg(card_token, amount) for a card leg.")
        if provider_code is None:
            raise ConfigurationError(
                "provider_code is required in a split payment leg (a provider with "
                "splitEligible: true from payments().list_payment_methods())."
            )
        block_name = block_name_of(code)
        if block_name not in SPLIT_LEG_BLOCK_FIELDS:
            raise ConfigurationError(
                f"paymentMethod {code} cannot be a split payment leg; a non-card leg carries "
                f"one of the blocks {', '.join(SPLIT_LEG_BLOCK_FIELDS)}."
            )
        block = {
            "providerCode": require_provider_code(provider_code),
            **require_method_fields({} if fields is None else fields, block_name),
        }
        if code == PaymentMethod.PROMISSORY_NOTE and "noteCount" in block:
            block["noteCount"] = require_note_count(block["noteCount"], f"{block_name}.noteCount")
        self._legs.append({"paymentMethod": code, "amount": amount, block_name: block})
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Checks the request and returns the body."""
        body = dict(self._payload)
        body["legs"] = [dict(leg) for leg in self._legs]
        assert_split_payment_payload(body)
        return body
