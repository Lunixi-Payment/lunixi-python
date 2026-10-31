"""Immutable native order identity and authenticated settlement evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from ..errors import ConfigurationError, LunixiError
from ..validation import amount_minor, currency_code


class CommerceError(LunixiError):
    """A durable checkout cannot safely advance; reconcile before retrying."""


def integer(value: Any) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value):
        value = int(value)
    return amount_minor(value, positive=False)


def minor_units(decimal: str, currency: str = "TRY") -> int:
    """Exact decimal string conversion; floats and fractional minor units fail."""
    exponent = 0 if currency_code(currency) == "JPY" else 3 if currency == "KWD" else 2
    if not isinstance(decimal, str) or not re.fullmatch(r"[0-9]{1,16}(?:[.][0-9]{1,8})?", decimal):
        raise ConfigurationError("A plain positive decimal string is required.")
    try:
        value = Decimal(decimal) * (10**exponent)
        if value != value.to_integral_value():
            raise ConfigurationError("Fractional minor units are not permitted.")
        return amount_minor(int(value))
    except InvalidOperation:
        raise ConfigurationError("Invalid decimal amount.") from None


@dataclass(frozen=True)
class OrderSnapshot:
    merchant_id: str
    order_id: str
    amount: int
    currency: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.merchant_id, str)
            or not self.merchant_id.strip()
            or len(self.merchant_id) > 200
            or not isinstance(self.order_id, str)
            or not 1 <= len(self.order_id) <= 128
        ):
            raise ConfigurationError("Persisted merchant/order identity is required.")
        amount_minor(self.amount)
        currency_code(self.currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchantId": self.merchant_id,
            "orderId": self.order_id,
            "amount": self.amount,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OrderSnapshot:
        return cls(
            value["merchantId"], value["orderId"], integer(value["amount"]), value["currency"]
        )

    @property
    def fingerprint(self) -> str:
        # Matches the PHP Commerce order fingerprint exactly, including Unicode escapes.
        return hashlib.sha256(
            json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"))
            .replace("/", "\\/")
            .encode()
        ).hexdigest()


@dataclass(frozen=True)
class PaymentDecision:
    state: str
    payment_id: str
    charged_amount: int
    captured_amount: int
    refunded_amount: int
    gateway_status: str
    split_id: Optional[str] = None

    @property
    def paid(self) -> bool:
        return self.state in ("paid", "partially_refunded")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate(
    order: OrderSnapshot,
    payment_id: str,
    response: Mapping[str, Any],
    split: Optional[Mapping[str, Any]] = None,
) -> PaymentDecision:
    """Accept authenticated GET evidence only; never browser/webhook status fields."""
    p = response.get("data", response)
    if not isinstance(p, dict):
        raise CommerceError("Invalid authenticated payment response.")
    expected = {
        "id": payment_id,
        "merchantId": order.merchant_id,
        "orderId": order.order_id,
        "currency": order.currency,
    }
    if any(p.get(k) != v for k, v in expected.items()):
        raise CommerceError("Authenticated payment identity does not match the order.")
    amount = integer(p.get("amount"))
    metadata = p.get("metadata")
    if not isinstance(metadata, dict) and isinstance(p.get("metadataJson"), str):
        try:
            metadata = json.loads(p["metadataJson"])
        except ValueError:
            metadata = None
    correlated = (
        isinstance(metadata, dict)
        and isinstance(metadata.get("lunixiCommerce"), dict)
        and metadata["lunixiCommerce"].get("fingerprint") == order.fingerprint
    )
    if amount < order.amount or (amount != order.amount and not correlated):
        raise CommerceError("Authenticated charged amount does not match the order.")
    status = p.get("status")
    if not isinstance(status, str):
        raise CommerceError("Authenticated payment status is invalid.")
    ref = p.get("split")
    if isinstance(ref, dict) or status == "SETTLED_BY_SPLIT":
        if (
            not isinstance(ref, dict)
            or ref.get("role") != "PARENT"
            or not isinstance(ref.get("splitPaymentId"), str)
            or split is None
        ):
            raise CommerceError("Complete split-parent evidence is required.")
        s = split.get("data", split)
        if not isinstance(s, dict):
            raise CommerceError("Invalid authenticated split response.")
        a = s.get("aggregate", {})
        if (
            s.get("id") != ref["splitPaymentId"]
            or s.get("currency") != order.currency
            or s.get("orderId") != order.order_id
            or s.get("parentPaymentId", payment_id) not in (None, payment_id)
            or s.get("needsReconciliation") is not False
            or a.get("amountsBalanced") is not True
            or integer(a.get("totalAmount")) != amount
            or integer(a.get("legsAmount")) != amount
        ):
            raise CommerceError("Split payment requires reconciliation.")
        captured = integer(a.get("capturedAmount"))
        refunded = integer(s.get("refund", {}).get("refundedAmount", 0))
        compensated = integer(a.get("compensatedAmount"))
        if captured > amount or refunded > captured:
            raise CommerceError("Invalid split settlement balances.")
        state = "review" if s.get("status") == "FAILED" else "pending"
        if (
            status == "SETTLED_BY_SPLIT"
            and s.get("status") == "COMPLETED"
            and captured == amount
            and compensated == 0
        ):
            state = (
                "paid"
                if refunded == 0
                else "refunded"
                if refunded == amount
                else "partially_refunded"
            )
        if (
            s.get("status") == "VOIDED"
            and captured == compensated
            and integer(a.get("authorizedAmount")) == 0
        ):
            state = "failed"
        return PaymentDecision(
            state, payment_id, amount, captured, refunded, status, ref["splitPaymentId"]
        )
    details = response.get("details", p.get("details", {}))
    if not isinstance(details, dict):
        raise CommerceError("Authenticated settlement balances are required.")
    captured = integer(details.get("capturedAmount"))
    refunded = integer(details.get("refundedAmount"))
    if captured > amount or refunded > captured:
        raise CommerceError("Invalid authenticated settlement balance.")
    state = "review"
    if status == "CAPTURED" and captured == amount and refunded == 0:
        state = "paid"
    elif status == "PARTIALLY_CAPTURED" and 0 < captured < amount and refunded == 0:
        state = "partially_captured"
    elif status == "AUTHORIZED" and captured == 0 and refunded == 0:
        state = "authorized"
    elif status == "REFUNDED" and captured > 0 and captured == refunded:
        state = "refunded"
    elif status == "PARTIALLY_REFUNDED" and 0 < refunded < captured:
        state = "partially_refunded"
    elif status in ("EXPIRED", "VOIDED") and captured == 0:
        state = "failed"
    elif status in ("INITIATED", "PROCESSING", "AWAITING_3D") and captured == 0:
        state = "pending"
    return PaymentDecision(state, payment_id, amount, captured, refunded, status)
