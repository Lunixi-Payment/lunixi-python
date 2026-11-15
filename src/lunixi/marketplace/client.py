"""Marketplace — ``client.marketplace()``: split charges across sub-dealers, the
sub-dealer lifecycle, commissions, payouts and the audit log.

Split charges (``/api/v1/payments/marketplace/*``) are signed per request and
take an optional ``Idempotency-Key``. A split is aggregate per seller: group
the basket by vendor and pass one leg per sub-dealer,
``{"subDealerId", "amountMinor", "scenario"?}``; the legs must add up to
``amount``. Dealer, commission, payout and audit routes
(``/api/v1/marketplace/*``) are bearer-only.

Card data (card number, expiry, security code) is sent as given and never
logged or put in an error message; a direct card charge is PCI DSS SAQ-D
scope, so most marketplaces use :meth:`MarketplaceClient.create_checkout_intent`
(hosted form).

Amounts are canonical minor-unit strings. Entity calls return the envelope's
``data``; lists return a :class:`~lunixi.http.envelope.Page`. Every call is
checked against :data:`~lunixi.marketplace.values.MARKETPLACE_ROUTES` before
anything is sent.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from .._routes import (
    check_value,
    compact,
    data_of,
    merge_request,
    merge_root,
    optional_text,
    plain_mapping,
    route_page,
    send_route,
    text,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ApiError, ConfigurationError
from ..http.envelope import Page
from ..validation import amount_minor, validate_money_fields
from .values import (
    MARKETPLACE_CHARGE_REQUIRED_FIELDS,
    MARKETPLACE_ROUTES,
    MARKETPLACE_SELLER_FIELDS,
    MarketplaceDealerStatus,
    MarketplaceDealerType,
    MarketplaceMultiSellerPolicy,
)

__all__ = ["MarketplaceClient"]

Request = Optional[Mapping[str, Any]]
Sellers = Sequence[Mapping[str, Any]]

_ALL_OR_NOTHING = MarketplaceMultiSellerPolicy.ALL_OR_NOTHING


def _call(api: ApiClient, name: str, **options: Any) -> Any:
    return send_route(api, MARKETPLACE_ROUTES, name, **options)


class MarketplaceClient:
    """Split charges, sub-dealers, commissions, payouts and the audit log."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    # ── Split charges ────────────────────────────────────────────────────────

    def create_checkout_intent(
        self,
        request: Any,
        sellers: Sellers,
        multi_seller_policy: str = _ALL_OR_NOTHING,
        *,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Hosted-form split checkout (``POST /payments/marketplace/intents``, signed).

        ``request`` is a :class:`~lunixi.payments.CreateIntent` or its body;
        the seller legs and the policy are added. Returns the envelope as it
        came (``token``, ``checkoutFormContent``, ``paymentId`` …); an answer
        without a token or form (a seller not eligible under
        ``ALL_OR_NOTHING``) raises :class:`~lunixi.errors.ApiError` instead of
        leaving the buyer on an empty page. Same route as
        ``payments().create_marketplace_intent()``.
        """
        body = _split_body(
            _wire_body(request, "createCheckoutIntent request"), sellers, multi_seller_policy
        )
        response = _call(
            self._api, "createCheckoutIntent", body=body, idempotency_key=idempotency_key
        )
        intent = merge_root(response)
        if _text_or_none(intent.get("token")) is None and (
            _text_or_none(intent.get("checkoutFormContent")) is None
        ):
            status_code = intent.get("statusCode")
            raise ApiError(
                "The marketplace checkout intent did not return a token.",
                status_code=status_code if isinstance(status_code, int) else 0,
                code=_text_or_none(intent.get("code")),
                request_id=_text_or_none(intent.get("requestId")),
                idempotency_key=idempotency_key,
            )
        return response

    def charge_marketplace_card(
        self, payload: Any, three_ds: bool = False, *, idempotency_key: Optional[str] = None
    ) -> Any:
        """Direct split card charge from a raw body (``amount``, ``currency``, ``orderId``,
        ``card``, ``buyer``, ``billingAddress``, ``basketItems``, ``sellers``,
        ``multiSellerPolicy``, ``preauth``? …): ``/payments/marketplace/3d`` when
        ``three_ds`` is true, ``/2d`` otherwise. Returns the envelope.

        Prefer :meth:`charge_marketplace_card2d` / :meth:`charge_marketplace_card3d`,
        which check the body and the legs.
        """
        body = _wire_body(payload, "chargeMarketplaceCard payload")
        _assert_charge_amount(body)
        name = "chargeMarketplaceCard3d" if three_ds else "chargeMarketplaceCard2d"
        return _call(self._api, name, body=body, idempotency_key=idempotency_key)

    def charge_marketplace_card2d(
        self,
        request: Any,
        sellers: Sellers,
        multi_seller_policy: str = _ALL_OR_NOTHING,
        *,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Split card charge without 3-D Secure: the card payment body plus the seller legs."""
        body = _charge_body(request, sellers, multi_seller_policy)
        return self.charge_marketplace_card(body, False, idempotency_key=idempotency_key)

    def charge_marketplace_card3d(
        self,
        request: Any,
        sellers: Sellers,
        multi_seller_policy: str = _ALL_OR_NOTHING,
        *,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Split card charge with 3-D Secure: the card payment body plus the seller legs."""
        body = _charge_body(request, sellers, multi_seller_policy)
        return self.charge_marketplace_card(body, True, idempotency_key=idempotency_key)

    # ── Sub-dealers ──────────────────────────────────────────────────────────

    def create_dealer(self, request: Request = None, **fields: Any) -> Any:
        """``legalName``, optional ``taxId``, ``dealerType``, ``categoryCode``, ``email``,
        ``externalRef``. The dealer then onboards itself (KYC, IBAN, contract) before it
        is ``ACTIVE``."""
        body = _dealer_body(merge_request(_mapping_or_none(request, "createDealer"), fields))
        return data_of(_call(self._api, "createDealer", body=body))

    def bulk_create_dealers(self, dealers: Sequence[Any]) -> Any:
        """Several dealers at once (an import); each row as in :meth:`create_dealer`."""
        if not isinstance(dealers, (list, tuple)) or len(dealers) == 0:
            raise ConfigurationError("bulkCreateDealers needs a non-empty list of dealers.")
        rows = [
            wire_fields(plain_mapping(dealer, f"dealers[{index}]"), f"dealers[{index}]")
            for index, dealer in enumerate(dealers)
        ]
        return data_of(_call(self._api, "bulkCreateDealers", body={"dealers": rows}))

    def list_dealers(self, **filters: Any) -> Page:
        """Filters: ``status``, ``search``, ``limit``, ``offset``."""
        return route_page(_call(self._api, "listDealers", query=filters))

    def get_dealer(self, dealer_id: str) -> Any:
        return data_of(_call(self._api, "getDealer", params={"dealerId": dealer_id}))

    def update_dealer_status(self, dealer_id: str, status: str) -> Any:
        check_value("status", MarketplaceDealerStatus.ALL, status)
        params = {"dealerId": dealer_id}
        return data_of(
            _call(self._api, "updateDealerStatus", params=params, body={"status": status})
        )

    def onboarding_token(self, dealer_id: str) -> Dict[str, Any]:
        """Self-onboarding link: ``{token, url, …}`` (``token`` also starts the embedded
        onboarding SDK); :func:`~lunixi.marketplace.values.marketplace_onboarding_url`
        gives the URL."""
        return merge_root(_call(self._api, "onboardingToken", params={"dealerId": dealer_id}))

    def dealer_application(self, dealer_id: str) -> Any:
        """Onboarding / application status."""
        return data_of(_call(self._api, "dealerApplication", params={"dealerId": dealer_id}))

    def submit_dealer_application(
        self, dealer_id: str, payload: Request = None, **fields: Any
    ) -> Any:
        body = merge_request(_mapping_or_none(payload, "submitDealerApplication"), fields)
        params = {"dealerId": dealer_id}
        return data_of(_call(self._api, "submitDealerApplication", params=params, body=body))

    def set_dealer_terms(self, dealer_id: str, payload: Request = None, **fields: Any) -> Any:
        """Commission / terms definition."""
        body = _required_body("setDealerTerms", payload, fields)
        params = {"dealerId": dealer_id}
        return data_of(_call(self._api, "setDealerTerms", params=params, body=body))

    def sign_dealer_contract(self, dealer_id: str, payload: Request = None, **fields: Any) -> Any:
        """Signature / contract acceptance."""
        body = merge_request(_mapping_or_none(payload, "signDealerContract"), fields)
        params = {"dealerId": dealer_id}
        return data_of(_call(self._api, "signDealerContract", params=params, body=body))

    def activate_dealer(self, dealer_id: str) -> Any:
        return data_of(_call(self._api, "activateDealer", params={"dealerId": dealer_id}))

    def record_dealer_kyc_result(
        self, dealer_id: str, payload: Request = None, **fields: Any
    ) -> Any:
        """A KYC outcome, when you run the dealer's KYC yourself."""
        body = _required_body("recordDealerKycResult", payload, fields)
        params = {"dealerId": dealer_id}
        return data_of(_call(self._api, "recordDealerKycResult", params=params, body=body))

    # ── Reporting and commissions ────────────────────────────────────────────

    def payout_ledger(self, **filters: Any) -> Page:
        """Filters: ``status``, ``subDealerId``, ``days``, ``limit``."""
        return route_page(_call(self._api, "payoutLedger", query=filters))

    def transactions(self, **filters: Any) -> Page:
        """Filters: ``status``, ``subDealerId``, ``limit``."""
        return route_page(_call(self._api, "transactions", query=filters))

    def commission_rules(self, **filters: Any) -> Page:
        """Filter: ``limit``."""
        return route_page(_call(self._api, "commissionRules", query=filters))

    def upsert_commission_rule(self, rule: Request = None, **fields: Any) -> Any:
        body = _required_body("upsertCommissionRule", rule, fields)
        return data_of(_call(self._api, "upsertCommissionRule", body=body))

    def preview_commission_rule(self, rule: Request = None, **fields: Any) -> Any:
        """Dry run of a rule's effect."""
        body = _required_body("previewCommissionRule", rule, fields)
        return data_of(_call(self._api, "previewCommissionRule", body=body))

    def resolve_commission(
        self,
        sub_dealer_id: str,
        *,
        category_code: Optional[str] = None,
        mtd_volume_minor: Optional[str] = None,
    ) -> Any:
        """Effective commission of a dealer (and category) at a month-to-date volume
        (``mtd_volume_minor``, a minor-unit string)."""
        query = compact(
            {
                "subDealerId": text(sub_dealer_id, "subDealerId"),
                "categoryCode": optional_text(category_code, "categoryCode"),
                "mtdVolumeMinor": mtd_volume_minor,
            }
        )
        return data_of(_call(self._api, "resolveCommission", query=query))

    # ── Payouts ──────────────────────────────────────────────────────────────

    def create_payout(self, payload: Request = None, **fields: Any) -> Any:
        """A manual payout: ``subDealerId``, ``amountMinor``, ``currency``, optional
        ``reference`` …"""
        body = wire_fields(_required_body("createPayout", payload, fields), "createPayout")
        if body.get("amountMinor") is not None:
            _minor(body["amountMinor"], "amountMinor")
        return data_of(_call(self._api, "createPayout", body=body))

    def mark_payout_paid(self, payout_id: str, payload: Request = None, **fields: Any) -> Any:
        """Optional ``paidAt``, ``reference`` …"""
        body = merge_request(_mapping_or_none(payload, "markPayoutPaid"), fields)
        params = {"payoutId": payout_id}
        return data_of(_call(self._api, "markPayoutPaid", params=params, body=body))

    def bulk_mark_payouts_paid(
        self, payout_ids: Sequence[str], extra: Request = None, **fields: Any
    ) -> Any:
        if not isinstance(payout_ids, (list, tuple)) or len(payout_ids) == 0:
            raise ConfigurationError("bulkMarkPayoutsPaid needs a non-empty list of payout ids.")
        ids = [text(payout_id, f"payoutIds[{index}]") for index, payout_id in enumerate(payout_ids)]
        body = wire_fields(
            merge_request(_mapping_or_none(extra, "bulkMarkPayoutsPaid"), fields),
            "bulkMarkPayoutsPaid",
        )
        body["payoutIds"] = ids
        return data_of(_call(self._api, "bulkMarkPayoutsPaid", body=body))

    # ── Audit log (append-only, hash-chained) ────────────────────────────────

    def audit_log(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``type``."""
        return route_page(_call(self._api, "auditLog", query=filters))

    def verify_audit_log(self) -> Any:
        """Verifies the integrity of the hash chain."""
        return data_of(_call(self._api, "verifyAuditLog"))


# ── checks ───────────────────────────────────────────────────────────────────


def _text_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value != "" else None


def _mapping_or_none(value: Any, label: str) -> Optional[Dict[str, Any]]:
    return None if value is None else plain_mapping(value, f"{label} payload")


def _required_body(label: str, payload: Any, fields: Mapping[str, Any]) -> Dict[str, Any]:
    if payload is None and not fields:
        raise ConfigurationError(f"{label} needs a payload (a mapping or keyword fields).")
    return merge_request(_mapping_or_none(payload, label), fields)


def _wire_body(request: Any, label: str) -> Dict[str, Any]:
    """A mapping, or an object with ``to_dict()`` (``CreateIntent``), with wire field names."""
    return wire_fields(plain_mapping(request, label), label)


def _minor(value: Any, field: str) -> str:
    try:
        return amount_minor(value)
    except ConfigurationError:
        raise ConfigurationError(
            f"{field} must be a positive canonical string in minor units."
        ) from None


def _dealer_body(body: Mapping[str, Any]) -> Dict[str, Any]:
    plain = wire_fields(body, "createDealer request")
    if plain.get("dealerType") is not None:
        check_value("dealerType", MarketplaceDealerType.ALL, plain["dealerType"])
    return plain


def _charge_body(request: Any, sellers: Sellers, multi_seller_policy: str) -> Dict[str, Any]:
    """The body of a split card charge: the commercial context is required."""
    body = _wire_body(request, "marketplace charge request")
    missing = [
        field for field in MARKETPLACE_CHARGE_REQUIRED_FIELDS if body.get(field) in (None, "")
    ]
    if missing:
        raise ConfigurationError(f"A marketplace card charge requires {', '.join(missing)}.")
    basket = body.get("basketItems")
    if not isinstance(basket, (list, tuple)) or len(basket) == 0:
        raise ConfigurationError("A marketplace card charge requires at least one basket item.")
    return _split_body(body, sellers, multi_seller_policy)


def _split_body(body: Dict[str, Any], sellers: Sellers, multi_seller_policy: str) -> Dict[str, Any]:
    """Adds the seller legs and the policy; the legs must add up to ``amount``."""
    if "sellers" in body or "multiSellerPolicy" in body:
        raise ConfigurationError(
            "Pass the seller legs and multi_seller_policy as arguments, not in the request body."
        )
    _assert_charge_amount(body)
    check_value("multiSellerPolicy", MarketplaceMultiSellerPolicy.ALL, multi_seller_policy)
    if not isinstance(sellers, (list, tuple)) or len(sellers) == 0:
        raise ConfigurationError("A marketplace split requires at least one seller leg.")
    legs = [_seller_leg(seller, index) for index, seller in enumerate(sellers)]
    total = sum(int(leg["amountMinor"]) for leg in legs)
    if total != int(body["amount"]):
        raise ConfigurationError(
            f"The seller legs add up to {total}, not to amount {body['amount']}; "
            "the gateway refuses any other total."
        )
    return {**body, "sellers": legs, "multiSellerPolicy": multi_seller_policy}


def _seller_leg(seller: Any, index: int) -> Dict[str, Any]:
    label = f"sellers[{index}]"
    leg = compact(wire_fields(plain_mapping(seller, label), label))
    unknown = [key for key in leg if key not in MARKETPLACE_SELLER_FIELDS]
    if unknown:
        raise ConfigurationError(f"{label} does not accept {', '.join(unknown)}.")
    out: Dict[str, Any] = {
        "subDealerId": text(leg.get("subDealerId"), f"{label}.subDealerId"),
        "amountMinor": _minor(leg.get("amountMinor"), f"{label}.amountMinor"),
    }
    if "scenario" in leg:
        out["scenario"] = plain_mapping(leg["scenario"], f"{label}.scenario")
    return out


def _assert_charge_amount(body: Mapping[str, Any]) -> None:
    """``amount`` (the basket total) is a positive minor-unit string; ``price`` /
    ``paidPrice`` are gone; ``preauth`` is a boolean. No message carries a value."""
    if "price" in body or "paidPrice" in body:
        raise ConfigurationError(
            "price/paidPrice were removed; send the basket total in 'amount' (minor units)."
        )
    _minor(body.get("amount"), "amount")
    if "preauth" in body and not isinstance(body["preauth"], bool):
        raise ConfigurationError("preauth must be a boolean.")
    validate_money_fields(dict(body))
