"""Synthetic order details every payment body carries (lunixi.payments.order_details)."""

from __future__ import annotations

from typing import Any, Dict, List

BUYER: Dict[str, str] = {
    "name": "Ada",
    "surname": "Yilmaz",
    "identityNumber": "11111111111",
    "email": "ada@example.com",
    "gsmNumber": "+905350000000",
    "city": "Istanbul",
    "country": "Turkey",
    "zipCode": "34000",
    "ip": "203.0.113.10",
}

BILLING_ADDRESS: Dict[str, str] = {
    "contactName": "Ada Yilmaz",
    "address": "Example Street 1",
    "city": "Istanbul",
    "country": "Turkey",
    "zipCode": "34000",
}


def basket(amount: str) -> List[Dict[str, str]]:
    """One virtual item whose price is the whole amount."""
    return [
        {
            "id": "SKU-1",
            "name": "Service",
            "category1": "General",
            "itemType": "VIRTUAL",
            "price": amount,
        }
    ]


def order_details(amount: str) -> Dict[str, Any]:
    return {
        "buyer": dict(BUYER),
        "billingAddress": dict(BILLING_ADDRESS),
        "basketItems": basket(amount),
    }


def with_order_details(request: Any, amount: str) -> Any:
    """Adds the order details to a request builder with ``with_buyer`` etc."""
    return (
        request.with_buyer(dict(BUYER))
        .with_billing_address(dict(BILLING_ADDRESS))
        .with_basket_items(basket(amount))
    )


def intent_details(amount: str) -> Dict[str, Any]:
    """``CreateIntent`` keyword arguments with the order details."""
    return {
        "buyer": dict(BUYER),
        "billing_address": dict(BILLING_ADDRESS),
        "basket_items": basket(amount),
    }


def snapshot_details(amount: str) -> Dict[str, Any]:
    """``OrderSnapshot`` keyword arguments with the order details."""
    return intent_details(amount)
