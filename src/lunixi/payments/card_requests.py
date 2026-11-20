"""Card lookups and stored cards: BIN info, installment options, store-card bodies.

A card number or a security code never appears in an error message or in the
``repr`` of these objects; only the field name does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from ..errors import ConfigurationError
from ..validation import amount_minor, currency_code
from .enabled_installments import validate_enabled_installments

__all__ = [
    "InstallmentOptionsRequest",
    "StoreCardRequest",
    "require_bin_or_pan",
    "installment_options_body",
]

_BIN_OR_PAN = re.compile(r"[0-9]{6,19}")


def require_bin_or_pan(value: Any) -> str:
    """A BIN (6 or 8 digits) or the leading digits of a card number, digits only."""
    if not isinstance(value, str) or _BIN_OR_PAN.fullmatch(value) is None:
        raise ConfigurationError(
            "bin_or_pan must be 6 to 19 digits: the card's BIN or its leading digits, "
            "without spaces."
        )
    return value


def _text(value: Any, name: str, max_length: int = 256) -> str:
    if (
        not isinstance(value, str)
        or value.strip() == ""
        or len(value) > max_length
        or any(ord(c) < 32 for c in value)
    ):
        raise ConfigurationError(
            f"{name} must be a non-empty string of at most {max_length} characters."
        )
    return value


def _https_url(value: Any, name: str) -> str:
    _text(value, name, 2048)
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or "#" in value
        or any(ord(c) <= 32 for c in value)
    ):
        raise ConfigurationError(f"{name} must be a trusted HTTPS URL.")
    return value


def _installment(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(f"installment must be a positive integer; got {value!r}.")
    return value


@dataclass(frozen=True)
class InstallmentOptionsRequest:
    """Body of ``POST /api/v1/bin/installments`` (``payments().installment_options()``).

    ``amount`` is the basket total in minor units. ``bin_or_pan`` narrows the
    table to the buyer's card; with ``installment`` > 1 and a BIN the answer
    carries a binding ``quoteToken`` to pass to
    :meth:`DirectMethodPaymentRequest.with_installment`.
    ``enabled_installments`` limits the table to these counts (e.g. ``[1, 2, 3]``
    for a product page that allows at most 3): integers 1–36, no duplicates,
    1 included; sent in ascending order.
    """

    amount: str
    currency: str
    bin_or_pan: Optional[str] = field(default=None, repr=False)
    installment: Optional[int] = None
    card_brand: Optional[str] = None
    enabled_installments: Optional[list[int]] = None

    def to_dict(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "amount": amount_minor(self.amount),
            "currency": currency_code(self.currency),
        }
        if self.bin_or_pan is not None:
            body["binOrPan"] = require_bin_or_pan(self.bin_or_pan)
        if self.installment is not None:
            body["installment"] = _installment(self.installment)
        if self.card_brand is not None:
            body["cardBrand"] = _text(self.card_brand, "card_brand", 64)
        if self.enabled_installments is not None:
            body["enabledInstallments"] = validate_enabled_installments(self.enabled_installments)
        return body


def installment_options_body(request: Any) -> Dict[str, Any]:
    """The body for an :class:`InstallmentOptionsRequest` or a raw mapping.

    A raw ``amount`` must be a canonical minor-unit string, and a raw
    ``enabledInstallments`` follows the same rule as the typed field (sent in
    ascending order).
    """
    if isinstance(request, InstallmentOptionsRequest):
        return request.to_dict()
    if not isinstance(request, Mapping):
        raise ConfigurationError(
            "installment_options takes an InstallmentOptionsRequest or a body mapping."
        )
    body = dict(request)
    if "price" in body or "paidPrice" in body:
        raise ConfigurationError(
            "price/paidPrice were removed; send the basket total in 'amount' (minor units)."
        )
    amount_minor(body.get("amount"))
    if body.get("binOrPan") is not None:
        require_bin_or_pan(body["binOrPan"])
    if "enabledInstallments" in body:
        body["enabledInstallments"] = validate_enabled_installments(
            body["enabledInstallments"], "enabledInstallments"
        )
    return body


class StoreCardRequest:
    """Body of ``POST /api/v1/payments/cards`` (``payments().store_card()``).

    ``card`` holds the card fields (``cardHolderName``, ``cardNumber``,
    ``expireMonth``, ``expireYear``, ``cvcNumber``) collected under your own
    PCI scope; ``card_user_key`` groups the buyer's stored cards and
    ``callback_url`` is where the buyer returns after the bank's verification.
    ``with_buyer()`` and ``with_billing_address()`` are required (no basket).
    The card is never shown by ``repr``.
    """

    __slots__ = ("_payload",)

    def __init__(self, card: Mapping[str, Any], card_user_key: str, callback_url: str) -> None:
        if not isinstance(card, Mapping) or len(card) == 0:
            raise ConfigurationError("StoreCardRequest needs a non-empty card object.")
        if not all(isinstance(key, str) for key in card):
            raise ConfigurationError("StoreCardRequest card field names must be strings.")
        self._payload: Dict[str, Any] = {
            "card": dict(card),
            "cardUserKey": _text(card_user_key, "card_user_key"),
            "callbackUrl": _https_url(callback_url, "callback_url"),
        }

    def with_currency(self, value: str) -> StoreCardRequest:
        self._payload["currency"] = currency_code(value)
        return self

    def with_buyer(self, value: Mapping[str, Any]) -> StoreCardRequest:
        """The card holder as the buyer (required; :mod:`lunixi.payments.order_details`)."""
        self._payload["buyer"] = dict(value)
        return self

    def with_billing_address(self, value: Mapping[str, Any]) -> StoreCardRequest:
        """The billing address (required)."""
        self._payload["billingAddress"] = dict(value)
        return self

    def to_dict(self) -> Dict[str, Any]:
        body = dict(self._payload)
        body["card"] = dict(self._payload["card"])
        return body

    def __repr__(self) -> str:
        return "StoreCardRequest(card=<withheld>)"
