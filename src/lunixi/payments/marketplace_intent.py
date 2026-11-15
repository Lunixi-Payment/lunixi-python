"""Body of ``POST /api/v1/payments/marketplace/intents``: a hosted checkout split by seller.

The body is the intent body plus ``sellers[]`` (``{subDealerId, amountMinor,
scenario?}``; ``scenario`` is an optional commission scenario override object)
and an optional ``multiSellerPolicy``. ``amountMinor`` is a
canonical minor-unit string and the sellers' amounts add up to ``amount``; the
gateway refuses any other total with 400 and nothing is charged, so the SDK
refuses it before sending.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..errors import ConfigurationError
from ..validation import amount_minor

__all__ = [
    "MultiSellerPolicy",
    "MARKETPLACE_SELLER_FIELDS",
    "marketplace_intent_body",
    "assert_marketplace_intent_payload",
]

#: Keys of one ``sellers[]`` entry.
MARKETPLACE_SELLER_FIELDS = ("subDealerId", "amountMinor", "scenario")


class MultiSellerPolicy:
    """What happens when one seller of a marketplace payment cannot be paid."""

    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    PARTIAL_ALLOWED = "PARTIAL_ALLOWED"


def _text(value: Any, name: str, max_length: int = 128) -> str:
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


def _sellers(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        raise ConfigurationError("A marketplace intent needs at least one seller in 'sellers'.")
    sellers: List[Dict[str, Any]] = []
    for index, seller in enumerate(value):
        if not isinstance(seller, Mapping):
            raise ConfigurationError(f"sellers[{index}] must be an object.")
        unknown = sorted(str(key) for key in seller if key not in MARKETPLACE_SELLER_FIELDS)
        if unknown:
            raise ConfigurationError(
                f"Unknown sellers[{index}] field(s): {', '.join(unknown)}. "
                f"Allowed: {', '.join(MARKETPLACE_SELLER_FIELDS)}."
            )
        _text(seller.get("subDealerId"), f"sellers[{index}].subDealerId")
        try:
            amount_minor(seller.get("amountMinor"))
        except ConfigurationError:
            raise ConfigurationError(
                f"sellers[{index}].amountMinor must be a positive canonical minor-unit string."
            ) from None
        if seller.get("scenario") is not None and not isinstance(seller["scenario"], Mapping):
            raise ConfigurationError(
                f"sellers[{index}].scenario must be an object (a commission scenario override)."
            )
        sellers.append(dict(seller))
    return sellers


def assert_marketplace_intent_payload(body: Mapping[str, Any]) -> None:
    """Checks a marketplace intent body before it is sent."""
    if "price" in body or "paidPrice" in body:
        raise ConfigurationError(
            "price/paidPrice were removed; send the basket total in 'amount' (minor units)."
        )
    total = int(amount_minor(body.get("amount")))
    sellers = _sellers(body.get("sellers"))
    seller_total = sum(int(seller["amountMinor"]) for seller in sellers)
    if seller_total != total:
        raise ConfigurationError(
            f"The sellers' amountMinor values add up to {seller_total}, not to amount {total}."
        )
    if body.get("multiSellerPolicy") is not None:
        _text(body["multiSellerPolicy"], "multiSellerPolicy", 64)
    if "preauth" in body and not isinstance(body["preauth"], bool):
        raise ConfigurationError(f"preauth must be a boolean; got {body['preauth']!r}.")


def marketplace_intent_body(
    intent_body: Mapping[str, Any],
    sellers: Optional[Sequence[Mapping[str, Any]]],
    multi_seller_policy: Optional[str],
) -> Dict[str, Any]:
    """Joins the intent body with ``sellers`` and ``multiSellerPolicy`` and checks the result."""
    body = dict(intent_body)
    if sellers is not None:
        if "sellers" in body:
            raise ConfigurationError("Pass the sellers once: in the body or as sellers=.")
        body["sellers"] = [
            dict(seller) if isinstance(seller, Mapping) else seller for seller in sellers
        ]
    if multi_seller_policy is not None:
        if "multiSellerPolicy" in body:
            raise ConfigurationError(
                "Pass the policy once: in the body or as multi_seller_policy=."
            )
        body["multiSellerPolicy"] = multi_seller_policy
    assert_marketplace_intent_payload(body)
    return body
