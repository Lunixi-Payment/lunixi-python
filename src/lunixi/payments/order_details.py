"""Order details every payment endpoint requires.

The buyer, the billing address and at least one basket item; a basket with a
``PHYSICAL`` item also requires the shipping address. Payment providers do not
start a payment without them.

The gateway refuses a missing field with ``payment.order.field_required`` and an
invalid one with ``payment.order.field_invalid``; ``details.field`` is the dotted
path of the first failing field, ``details.reason`` the reason and
``details.fields`` every field failing for the same reason. The SDK checks the
same rule before sending and names the same paths. Same values as the Node
SDK's ``order-details-values.js`` and the PHP SDK's ``Payment\\OrderDetails``.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Tuple

from ..errors import ConfigurationError

__all__ = [
    "ORDER_DETAILS_REQUIRED_FIELDS",
    "BUYER_REQUIRED_FIELDS",
    "CHECKOUT_INTENT_BUYER_OPTIONAL_FIELDS",
    "ADDRESS_REQUIRED_FIELDS",
    "BASKET_ITEM_REQUIRED_FIELDS",
    "OrderFieldErrorCode",
    "OrderFieldReason",
    "missing_order_details",
    "assert_order_details",
]

#: Order objects required on every payment endpoint.
ORDER_DETAILS_REQUIRED_FIELDS: Tuple[str, ...] = ("buyer", "billingAddress", "basketItems")

#: ``buyer`` fields that must be non-empty strings. ``identityNumber``: Turkish
#: ID or passport number; ``ip``: the buyer's browser IP.
BUYER_REQUIRED_FIELDS: Tuple[str, ...] = (
    "name",
    "surname",
    "identityNumber",
    "email",
    "gsmNumber",
    "city",
    "country",
    "zipCode",
    "ip",
)

#: ``buyer`` fields a checkout intent may leave out (``create_intent()``,
#: ``create_marketplace_intent()``): the Lunixi form takes the IP from the
#: buyer's browser. A given ``ip`` is still sent and wins.
CHECKOUT_INTENT_BUYER_OPTIONAL_FIELDS: Tuple[str, ...] = ("ip",)

#: Fields of ``billingAddress`` and ``shippingAddress`` that must be non-empty strings.
ADDRESS_REQUIRED_FIELDS: Tuple[str, ...] = ("contactName", "address", "city", "country", "zipCode")

#: Fields of each ``basketItems[]`` entry the gateway requires.
BASKET_ITEM_REQUIRED_FIELDS: Tuple[str, ...] = ("id", "name", "category1", "itemType", "price")


class OrderFieldErrorCode:
    """Error codes of a missing or invalid order field."""

    FIELD_REQUIRED = "payment.order.field_required"
    FIELD_INVALID = "payment.order.field_invalid"


class OrderFieldReason:
    """``details.reason`` of an order field error."""

    REQUIRED = "required"
    REQUIRED_WHEN_PHYSICAL = "required_when_physical"
    INVALID_TYPE = "invalid_type"
    INVALID_FORMAT = "invalid_format"
    TOO_LONG = "too_long"
    TOO_FEW_ITEMS = "too_few_items"


def _filled(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _missing_fields_of(value: Any, fields: Tuple[str, ...], path: str) -> List[str]:
    if not isinstance(value, Mapping):
        return [path]
    return [f"{path}.{field}" for field in fields if not _filled(value.get(field))]


def missing_order_details(
    body: Mapping[str, Any], *, basket: bool = True, checkout_intent: bool = False
) -> List[str]:
    """Paths of the missing order fields of a payment body, in the gateway's format.

    ``buyer``, ``buyer.email``, ``billingAddress.city``, ``shippingAddress`` …
    An empty list means the order details are complete. ``basket=False`` checks
    the buyer and billing address only (card storage, wallet card top-up);
    ``checkout_intent=True`` does not require ``CHECKOUT_INTENT_BUYER_OPTIONAL_FIELDS``.
    """
    buyer_fields = (
        tuple(f for f in BUYER_REQUIRED_FIELDS if f not in CHECKOUT_INTENT_BUYER_OPTIONAL_FIELDS)
        if checkout_intent
        else BUYER_REQUIRED_FIELDS
    )
    buyer = body.get("buyer")
    billing = body.get("billingAddress")
    missing = ["buyer"] if buyer is None else _missing_fields_of(buyer, buyer_fields, "buyer")
    missing += (
        ["billingAddress"]
        if billing is None
        else _missing_fields_of(billing, ADDRESS_REQUIRED_FIELDS, "billingAddress")
    )
    if not basket:
        return missing
    items = body.get("basketItems")
    if not isinstance(items, (list, tuple)) or len(items) == 0:
        missing.append("basketItems")
        return missing
    physical = False
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            missing.append(f"basketItems.{index}")
            continue
        for field in BASKET_ITEM_REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                missing.append(f"basketItems.{index}.{field}")
        physical = physical or item.get("itemType") == "PHYSICAL"
    shipping = body.get("shippingAddress")
    if physical and shipping is None:
        missing.append("shippingAddress")
    elif shipping is not None:
        missing += _missing_fields_of(shipping, ADDRESS_REQUIRED_FIELDS, "shippingAddress")
    return missing


def assert_order_details(
    body: Mapping[str, Any], label: str, *, basket: bool = True, checkout_intent: bool = False
) -> None:
    """Raises :class:`~lunixi.errors.ConfigurationError` naming the missing order fields."""
    missing = missing_order_details(body, basket=basket, checkout_intent=checkout_intent)
    if missing:
        raise ConfigurationError(f"{label} requires the order details: {', '.join(missing)}.")
