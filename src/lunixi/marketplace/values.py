"""Marketplace (sub-dealer split) — ``/api/v1/marketplace/*`` for dealers, commissions,
payouts and the audit log (bearer-only), and the split charges under
``/api/v1/payments/marketplace/*`` (signed per request).

:data:`MARKETPLACE_ROUTES` describes every route the client calls; it is the
same table as the Node SDK's ``MARKETPLACE_ROUTES`` and the shared catalog
(``contracts/products/marketplace.json``).
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

from .._routes import freeze_routes
from ..payments.marketplace_intent import MARKETPLACE_SELLER_FIELDS, MultiSellerPolicy

__all__ = [
    "MarketplaceDealerStatus",
    "MarketplaceDealerType",
    "MarketplaceMultiSellerPolicy",
    "MARKETPLACE_DEALER_ONBOARDING_HOSTED_BASE",
    "MARKETPLACE_SELLER_FIELDS",
    "MARKETPLACE_CHARGE_REQUIRED_FIELDS",
    "MARKETPLACE_ROUTES",
    "marketplace_onboarding_url",
]


class MarketplaceDealerStatus:
    """Sub-dealer lifecycle. Only ``ACTIVE`` dealers can receive a split."""

    DRAFT = "DRAFT"
    PENDING_KYC = "PENDING_KYC"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    HOLD = "HOLD"
    CLOSED = "CLOSED"
    ALL = (DRAFT, PENDING_KYC, ACTIVE, SUSPENDED, HOLD, CLOSED)


class MarketplaceDealerType:
    """``dealerType`` of a sub-dealer."""

    LEGAL_ENTITY = "LEGAL_ENTITY"
    INDIVIDUAL = "INDIVIDUAL"
    ALL = (LEGAL_ENTITY, INDIVIDUAL)


class MarketplaceMultiSellerPolicy(MultiSellerPolicy):
    """``multiSellerPolicy`` of a split charge: every seller leg must be eligible
    (``ALL_OR_NOTHING``), or the eligible legs may go through without the others
    (``PARTIAL_ALLOWED``). The same codes as :class:`~lunixi.payments.MultiSellerPolicy`."""

    ALL = (MultiSellerPolicy.ALL_OR_NOTHING, MultiSellerPolicy.PARTIAL_ALLOWED)


#: Hosted dealer onboarding wizard (:func:`marketplace_onboarding_url` when the answer
#: carries no ``url``).
MARKETPLACE_DEALER_ONBOARDING_HOSTED_BASE = "https://altbayi.lunixi.com"

#: Fields a split card charge (``charge_marketplace_card2d`` / ``3d``) needs besides the
#: seller legs: the commercial context of a traceable card payment.
MARKETPLACE_CHARGE_REQUIRED_FIELDS = (
    "amount",
    "currency",
    "orderId",
    "card",
    "buyer",
    "billingAddress",
    "basketItems",
)

_MP = "/api/v1/marketplace"
_PAY = "/api/v1/payments/marketplace"


def _route(method: str, path: str, **extra: Any) -> Mapping[str, Any]:
    return {"method": method, "path": path, "stepUp": False, "idempotencyKey": "none", **extra}


def _charge(path: str) -> Mapping[str, Any]:
    return _route("POST", path, stepUp=True, idempotencyKey="optional", free=True)


#: Every route the marketplace client calls (Node ``MARKETPLACE_ROUTES``).
MARKETPLACE_ROUTES = freeze_routes(
    {
        "createCheckoutIntent": _charge(f"{_PAY}/intents"),
        "chargeMarketplaceCard2d": _charge(f"{_PAY}/2d"),
        "chargeMarketplaceCard3d": _charge(f"{_PAY}/3d"),
        "createDealer": _route(
            "POST",
            f"{_MP}/dealers",
            required=["legalName"],
            optional=["taxId", "dealerType", "categoryCode", "email", "externalRef"],
        ),
        "bulkCreateDealers": _route("POST", f"{_MP}/dealers/bulk", required=["dealers"]),
        "listDealers": _route(
            "GET", f"{_MP}/dealers", query=["status", "search", "limit", "offset"]
        ),
        "getDealer": _route("GET", f"{_MP}/dealers/:dealerId"),
        "updateDealerStatus": _route(
            "PUT", f"{_MP}/dealers/:dealerId/status", required=["status"]
        ),
        "onboardingToken": _route("POST", f"{_MP}/dealers/:dealerId/onboarding-token"),
        "dealerApplication": _route("GET", f"{_MP}/dealers/:dealerId/application"),
        "submitDealerApplication": _route("POST", f"{_MP}/dealers/:dealerId/submit", free=True),
        "setDealerTerms": _route("POST", f"{_MP}/dealers/:dealerId/terms", free=True),
        "signDealerContract": _route("POST", f"{_MP}/dealers/:dealerId/sign", free=True),
        "activateDealer": _route("POST", f"{_MP}/dealers/:dealerId/activate"),
        "recordDealerKycResult": _route(
            "POST", f"{_MP}/dealers/:dealerId/kyc-result", free=True
        ),
        "payoutLedger": _route(
            "GET", f"{_MP}/payout-ledger", query=["status", "subDealerId", "days", "limit"]
        ),
        "transactions": _route(
            "GET", f"{_MP}/transactions", query=["status", "subDealerId", "limit"]
        ),
        "commissionRules": _route("GET", f"{_MP}/commission-rules", query=["limit"]),
        "upsertCommissionRule": _route("POST", f"{_MP}/commission-rules", free=True),
        "previewCommissionRule": _route("POST", f"{_MP}/commission-rules/preview", free=True),
        "resolveCommission": _route(
            "GET",
            f"{_MP}/commission/resolve",
            query=["subDealerId", "categoryCode", "mtdVolumeMinor"],
        ),
        "createPayout": _route("POST", f"{_MP}/payouts", free=True),
        "markPayoutPaid": _route("POST", f"{_MP}/payouts/:payoutId/mark-paid", free=True),
        "bulkMarkPayoutsPaid": _route("POST", f"{_MP}/payouts/bulk-mark-paid", free=True),
        "auditLog": _route("GET", f"{_MP}/audit-log", query=["limit", "type"]),
        "verifyAuditLog": _route("GET", f"{_MP}/audit-log/verify"),
    }
)


def marketplace_onboarding_url(
    link: Any, base: str = MARKETPLACE_DEALER_ONBOARDING_HOSTED_BASE
) -> str:
    """Onboarding URL of an ``onboarding_token()`` answer: its ``url``, else the hosted
    wizard with its ``token``."""
    url = link.get("url") if isinstance(link, Mapping) else None
    if isinstance(url, str) and url != "":
        return url
    token = link.get("token") if isinstance(link, Mapping) else None
    token = token if isinstance(token, str) else ""
    return str(base).rstrip("/") + "/m/" + quote(token, safe="!*'()")
