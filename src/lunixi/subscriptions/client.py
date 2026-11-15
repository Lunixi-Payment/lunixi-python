"""Subscriptions — ``/api/v1/subscriptions/*``, ``client.subscriptions()``.

Calls carry the access token minted from your API key (no per-request
signature). Creating a subscription needs an ``Idempotency-Key`` (reuse it
when retrying the same subscription); plan, customer, card, plan-change and
charge-retry writes accept one.

Amounts are canonical minor-unit strings (``"9900"`` = 99.00 TRY), checked in
bodies, filters and answers (``"0"`` is a free plan). Entity calls return the
envelope's ``data``. Subscription, plan, customer, card and invoice lists
return a :class:`SubscriptionPage` (send ``next_page_token`` back as
``page_token``, or use ``iterate()``); catalog, feature, add-on and portal-link
lists return a :class:`~lunixi.http.envelope.Page`. The related resources hang
off ``plans``, ``customers``, ``cards``, ``invoices``, ``portal``,
``products``, ``features``, ``addons`` and ``usage``.

Every call is checked against :data:`~lunixi.subscriptions.values.SUBSCRIPTION_ROUTES`
before anything is sent: an unknown field or filter, a missing required field,
a value outside its set, an amount that is not a minor-unit string or a missing
``Idempotency-Key`` raises :class:`~lunixi.errors.ConfigurationError`, naming
the field, never its value. Body fields may be given as a mapping or as
keyword arguments, in camelCase or snake_case.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, Optional, cast

from .._routes import (
    check_value,
    compact,
    data_of,
    idempotency_key_of,
    iso_time,
    merge_request,
    merge_root,
    optional_text,
    paginate,
    plain_mapping,
    route_page,
    send_route,
    text,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from ..validation import currency_code
from .values import (
    SUBSCRIPTION_BILLING_RULE_FIELDS,
    SUBSCRIPTION_ROUTES,
    SubscriptionBillingFrequency,
    SubscriptionCardVerificationMode,
    SubscriptionCollectionMethod,
    SubscriptionPlanChangeBehavior,
    SubscriptionPortalSdkMode,
)

__all__ = [
    "SubscriptionsClient",
    "SubscriptionPage",
    "SubscriptionPlans",
    "SubscriptionCustomers",
    "SubscriptionCards",
    "SubscriptionInvoices",
    "SubscriptionPortal",
    "SubscriptionProducts",
    "SubscriptionFeatures",
    "SubscriptionAddons",
    "SubscriptionUsage",
]

Request = Optional[Mapping[str, Any]]


def _call(api: ApiClient, name: str, **options: Any) -> Any:
    return send_route(api, SUBSCRIPTION_ROUTES, name, **options)


class SubscriptionPage(Page):
    """A subscription, plan, customer, card or invoice list.

    ``next_cursor`` is the answer's ``nextPageToken`` (also readable as
    :attr:`next_page_token`); send it back as ``page_token``. ``page_size`` is
    the answer's ``pageSize``, else the number of rows.
    """

    __slots__ = ("page_size",)

    page_size: int

    @property
    def next_page_token(self) -> Optional[str]:
        return self.next_cursor


def _subscription_page(response: Any) -> SubscriptionPage:
    page = cast(SubscriptionPage, route_page(response, SubscriptionPage))
    size = response.get("pageSize") if isinstance(response, Mapping) else None
    counted = isinstance(size, int) and not isinstance(size, bool)
    page.page_size = size if counted else len(page.items)
    return page


def _token_pages(fetch: Any, filters: Mapping[str, Any], label: str) -> Iterator[Any]:
    return paginate(fetch, wire_fields(filters, f"{label} filters"), "pageToken")


class SubscriptionsClient:
    """Subscriptions; the related resources live on the sub-clients."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api
        self.plans = SubscriptionPlans(api)
        self.customers = SubscriptionCustomers(api)
        self.cards = SubscriptionCards(api)
        self.invoices = SubscriptionInvoices(api)
        self.portal = SubscriptionPortal(api)
        self.products = SubscriptionProducts(api)
        self.features = SubscriptionFeatures(api)
        self.addons = SubscriptionAddons(api)
        self.usage = SubscriptionUsage(api)

    def create(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """``customerId``, ``planId``, optional ``paymentCardId``, ``paymentMethodId``,
        ``collectionMethod``, ``priceUpdatePolicy``, ``entitlementPolicy``,
        ``billingTimezone``, ``startsAt``, ``chargeOnCreate``,
        ``billingCycleAnchorOverride``, ``skipTrial``, ``metadata``.

        The ``Idempotency-Key`` is required (``idempotency_key=`` or the
        request's ``idempotencyKey``; both given, they must agree); it is also
        sent in the body.
        """
        body = wire_fields(merge_request(request, fields), "create request")
        key = idempotency_key_of("create", body, idempotency_key)
        if key is not None:
            body["idempotencyKey"] = key
        if body.get("collectionMethod") is not None:
            check_value(
                "collectionMethod", SubscriptionCollectionMethod.ALL, body["collectionMethod"]
            )
        for field in ("chargeOnCreate", "skipTrial"):
            _boolean_field(body, field)
        if body.get("metadata") is not None:
            plain_mapping(body["metadata"], "metadata")
        return data_of(_call(self._api, "create", body=body, idempotency_key=key))

    def get(self, subscription_id: str) -> Any:
        return data_of(_call(self._api, "get", params={"subscriptionId": subscription_id}))

    def list(self, **filters: Any) -> SubscriptionPage:
        """Filters: ``customerId``, ``status``, ``pageSize``, ``pageToken``."""
        return _subscription_page(_call(self._api, "list", query=filters))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        """Every subscription, following ``nextPageToken``."""
        return _token_pages(lambda page: self.list(**page), filters, "list")

    def cancel(
        self, subscription_id: str, *, at_period_end: bool = False, reason: Optional[str] = None
    ) -> Any:
        """Cancels now, or at the period end with ``at_period_end=True``."""
        if not isinstance(at_period_end, bool):
            raise ConfigurationError("at_period_end must be a boolean.")
        reason_text = optional_text(reason, "reason")
        body = compact({"cancelAtPeriodEnd": at_period_end, "reason": reason_text})
        params = {"subscriptionId": subscription_id}
        return data_of(_call(self._api, "cancel", params=params, body=body))

    def pause(self, subscription_id: str, resume_at: Any = None) -> Any:
        """Pauses billing; ``resume_at`` (an aware datetime or ISO-8601 text) resumes it
        automatically."""
        resume = None if resume_at is None or resume_at == "" else iso_time(resume_at, "resume_at")
        params = {"subscriptionId": subscription_id}
        return data_of(_call(self._api, "pause", params=params, body=compact({"resumeAt": resume})))

    def resume(self, subscription_id: str) -> Any:
        return data_of(_call(self._api, "resume", params={"subscriptionId": subscription_id}))

    def change_plan(
        self,
        subscription_id: str,
        request: Request = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """``newPlanId``, optional ``behavior`` (``IMMEDIATE`` | ``NEXT_PERIOD``), ``reason``.

        An ``Idempotency-Key`` (``idempotency_key=`` or the request's
        ``idempotencyKey``) is sent in the header and the body.
        """
        body = wire_fields(merge_request(request, fields), "changePlan request")
        key = idempotency_key_of("changePlan", body, idempotency_key)
        if key is not None:
            body["idempotencyKey"] = key
        if body.get("behavior") is not None:
            body["behavior"] = check_value(
                "behavior", SubscriptionPlanChangeBehavior.ALL, str(body["behavior"]).upper()
            )
        params = {"subscriptionId": subscription_id}
        return data_of(
            _call(self._api, "changePlan", params=params, body=body, idempotency_key=key)
        )

    def audit_logs(self, subscription_id: str, **filters: Any) -> SubscriptionPage:
        """Audit trail of a subscription; filters ``limit``, ``pageToken``."""
        params = {"subscriptionId": subscription_id}
        return _subscription_page(_call(self._api, "auditLogs", params=params, query=filters))

    def iterate_audit_logs(self, subscription_id: str, **filters: Any) -> Iterator[Any]:
        return _token_pages(
            lambda page: self.audit_logs(subscription_id, **page), filters, "auditLogs"
        )


class _Section:
    def __init__(self, api: ApiClient) -> None:
        self._api = api


class SubscriptionPlans(_Section):
    """Plans: the templates a subscription is created against."""

    def create(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """``productId``, ``code``, ``name``, ``price``, ``currency``, ``billing``, optional
        ``description``, ``trialPeriodDays``, ``maxDunningAttempts``, ``dunningScheduleDays``,
        ``gracePeriodDays``, ``metadata``.

        ``price`` is a minor-unit string (``"0"`` for a free plan); ``billing``
        is ``{frequency, interval?, byMonthDay?, byWeekDay?, timezone?,
        lastDayOfMonthFix?, count?}`` (``interval`` defaults to 1).
        """
        body = wire_fields(merge_request(request, fields), "plans.create request")
        for field in ("productId", "code", "name"):
            if body.get(field) is not None:
                body[field] = text(body[field], field)
        if body.get("price") is None:
            raise ConfigurationError("plans.create requires price.")
        if body.get("currency") is not None:
            body["currency"] = _currency(body["currency"], "currency")
        if body.get("billing") is not None:
            body["billing"] = _billing_rule(body["billing"])
        for field in ("trialPeriodDays", "maxDunningAttempts", "gracePeriodDays"):
            _count_field(body, field, 0)
        if body.get("dunningScheduleDays") is not None:
            body["dunningScheduleDays"] = _integer_list(
                body["dunningScheduleDays"], "dunningScheduleDays", 0
            )
        return data_of(
            _call(self._api, "plans.create", body=body, idempotency_key=idempotency_key)
        )

    def get(self, plan_id: str) -> Any:
        return data_of(_call(self._api, "plans.get", params={"planId": plan_id}))

    def list(self, **filters: Any) -> SubscriptionPage:
        """Filters: ``productId``, ``includeArchived``, ``pageSize``, ``pageToken``."""
        return _subscription_page(_call(self._api, "plans.list", query=filters))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return _token_pages(lambda page: self.list(**page), filters, "plans.list")

    def update(self, plan_id: str, changes: Request = None, **fields: Any) -> Any:
        """Price, billing, metadata…; a ``price`` is a minor-unit string."""
        body = _changes("plans.update", changes, fields)
        return data_of(_call(self._api, "plans.update", params={"planId": plan_id}, body=body))

    def archive(self, plan_id: str) -> Any:
        return data_of(_call(self._api, "plans.archive", params={"planId": plan_id}))

    def translations(self, plan_id: str) -> Any:
        return data_of(_call(self._api, "plans.translations", params={"planId": plan_id}))

    def upsert_translation(
        self, plan_id: str, locale: str, translation: Request = None, **fields: Any
    ) -> Any:
        body = _changes("plans.upsertTranslation", translation, fields)
        params = {"planId": plan_id, "locale": locale}
        return data_of(_call(self._api, "plans.upsertTranslation", params=params, body=body))


class SubscriptionCustomers(_Section):
    """Customers, upserted by your own ``externalId`` (one stable customer per user)."""

    def upsert(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """``externalId``, optional ``email``, ``name``, ``phone``, ``locale``, ``metadata``."""
        body = merge_request(request, fields)
        return data_of(
            _call(self._api, "customers.upsert", body=body, idempotency_key=idempotency_key)
        )

    def get(self, customer_id: str) -> Any:
        return data_of(_call(self._api, "customers.get", params={"customerId": customer_id}))

    def get_by_external_id(self, external_id: str) -> Any:
        params = {"externalId": external_id}
        return data_of(_call(self._api, "customers.getByExternalId", params=params))

    def list(self, **filters: Any) -> SubscriptionPage:
        """Filters: ``search``, ``includeArchived``, ``pageSize``, ``pageToken``."""
        return _subscription_page(_call(self._api, "customers.list", query=filters))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return _token_pages(lambda page: self.list(**page), filters, "customers.list")

    def credit_balance(self, customer_id: str) -> Any:
        params = {"customerId": customer_id}
        return data_of(_call(self._api, "customers.creditBalance", params=params))

    def adjust_credit(self, customer_id: str, adjustment: Request = None, **fields: Any) -> Any:
        """Grants or deducts credit: ``amountMinor`` (a minor-unit string), ``currency``,
        ``reason``, ``type`` …"""
        body = _changes("customers.adjustCredit", adjustment, fields)
        params = {"customerId": customer_id}
        return data_of(_call(self._api, "customers.adjustCredit", params=params, body=body))

    def archive(self, customer_id: str) -> Any:
        return data_of(_call(self._api, "customers.archive", params={"customerId": customer_id}))


class SubscriptionCards(_Section):
    """Saved cards for automatic charges.

    A card is added from the checkout SDK's ``paymentMethodToken``; a card
    number or security code is never sent (the fields are refused, and the
    refusal names only the field).
    """

    def add(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """``customerId``, ``paymentMethodToken``, optional ``brand``, ``last4``, ``bin``,
        ``expireMonth``, ``expireYear``, ``cardholderName``, ``isDefault``, ``nickname``,
        ``verificationMode``, ``supportedCurrencies``."""
        body = wire_fields(merge_request(request, fields), "cards.add request")
        if body.get("verificationMode") is not None:
            check_value(
                "verificationMode", SubscriptionCardVerificationMode.ALL, body["verificationMode"]
            )
        for field in ("expireMonth", "expireYear"):
            _count_field(body, field, 1)
        _boolean_field(body, "isDefault")
        currencies = body.get("supportedCurrencies")
        if currencies is not None:
            if not isinstance(currencies, (list, tuple)):
                raise ConfigurationError("supportedCurrencies must be a list.")
            body["supportedCurrencies"] = [
                _currency(currency, "supportedCurrencies") for currency in currencies
            ]
        return data_of(_call(self._api, "cards.add", body=body, idempotency_key=idempotency_key))

    def get(self, card_id: str) -> Any:
        return data_of(_call(self._api, "cards.get", params={"cardId": card_id}))

    def list(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        page_token: Optional[str] = None,
        page_size: Optional[int] = None,
    ) -> SubscriptionPage:
        """A customer's cards."""
        query = {
            "customerId": text(customer_id, "customerId"),
            "includeInactive": include_inactive,
            "pageToken": page_token,
            "pageSize": page_size,
        }
        return _subscription_page(_call(self._api, "cards.list", query=query))

    def iterate(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        page_size: Optional[int] = None,
    ) -> Iterator[Any]:
        def fetch(page: Dict[str, Any]) -> Page:
            return self.list(
                customer_id,
                include_inactive=include_inactive,
                page_token=page.get("pageToken"),
                page_size=page_size,
            )

        return paginate(fetch, {}, "pageToken")

    def set_default(self, card_id: str) -> Any:
        return data_of(_call(self._api, "cards.setDefault", params={"cardId": card_id}))

    def deactivate(self, card_id: str, reason: Optional[str] = None) -> Any:
        body = compact({"reason": optional_text(reason, "reason")})
        return data_of(_call(self._api, "cards.deactivate", params={"cardId": card_id}, body=body))

    def verify(self, card_id: str, options: Request = None, **fields: Any) -> Any:
        """Verifies a saved card (a small authorisation or a 3-D check); options as the
        gateway documents them."""
        body = merge_request(options, fields)
        return data_of(_call(self._api, "cards.verify", params={"cardId": card_id}, body=body))

    def update(self, card_id: str, changes: Request = None, **fields: Any) -> Any:
        """Card metadata (label, expiry, billing…); never a card number."""
        body = _changes("cards.update", changes, fields)
        return data_of(_call(self._api, "cards.update", params={"cardId": card_id}, body=body))


class SubscriptionInvoices(_Section):
    """Invoices: billing history, void and charge retry."""

    def list(self, **filters: Any) -> SubscriptionPage:
        """Filters: ``subscriptionId``, ``status``, ``pageSize``, ``pageToken``."""
        return _subscription_page(_call(self._api, "invoices.list", query=filters))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return _token_pages(lambda page: self.list(**page), filters, "invoices.list")

    def get(self, invoice_id: str) -> Any:
        return data_of(_call(self._api, "invoices.get", params={"invoiceId": invoice_id}))

    def void(self, invoice_id: str, reason: Optional[str] = None) -> Any:
        body = compact({"reason": optional_text(reason, "reason")})
        params = {"invoiceId": invoice_id}
        return data_of(_call(self._api, "invoices.void", params=params, body=body))

    def retry_charge(self, invoice_id: str, *, idempotency_key: Optional[str] = None) -> Any:
        params = {"invoiceId": invoice_id}
        return data_of(
            _call(self._api, "invoices.retryCharge", params=params, idempotency_key=idempotency_key)
        )


class SubscriptionPortal(_Section):
    """Customer portal.

    Embedded: :meth:`create_sdk_session` mints an origin-bound session for the
    browser portal SDK (``origin`` must be allow-listed). Hosted:
    :meth:`create_portal_link` returns a link whose ``token`` opens the hosted
    portal (:func:`~lunixi.subscriptions.values.subscription_portal_url`); the
    customer verifies with a one-time code. The link routes live under
    ``/api/panel/v1/subscriptions/portal``.
    """

    def create_sdk_session(
        self,
        customer_id: str,
        origin: str,
        *,
        sdk_mode: Optional[str] = None,
        portal_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns ``portalToken``, ``sessionProof``, ``proofNonce``, ``proofExpiresAt`` …

        The gateway answers at the envelope root; hand those four to the browser.
        """
        if sdk_mode is not None and sdk_mode != "":
            check_value("sdkMode", SubscriptionPortalSdkMode.ALL, sdk_mode)
        body = compact(
            {
                "customerId": text(customer_id, "customerId"),
                "origin": text(origin, "origin"),
                "sdkMode": optional_text(sdk_mode, "sdkMode"),
                "portalLinkId": optional_text(portal_link_id, "portalLinkId"),
            }
        )
        session = merge_root(_call(self._api, "portal.createSdkSession", body=body))
        if "proofNonce" not in session and "nonce" in session:
            session["proofNonce"] = session["nonce"]
        if "proofExpiresAt" not in session and "expiresAt" in session:
            session["proofExpiresAt"] = session["expiresAt"]
        return session

    def create_portal_link(self, customer_id: str, options: Request = None, **fields: Any) -> Any:
        """Options: ``allowedPlanIds``, ``defaultPlanId``, ``permissions``,
        ``sessionDurationMinutes``, ``expiresAt``, ``requireEmailVerification`` …"""
        body = wire_fields(merge_request(options, fields), "createPortalLink options")
        body["customerId"] = text(customer_id, "customerId")
        return data_of(_call(self._api, "portal.createPortalLink", body=body))

    def list_links(self, **filters: Any) -> Page:
        """Filters: ``customerId``, ``status``, ``limit``."""
        return route_page(_call(self._api, "portal.listLinks", query=filters))

    def get_link(self, link_id: str) -> Any:
        return data_of(_call(self._api, "portal.getLink", params={"linkId": link_id}))

    def update_link(self, link_id: str, changes: Request = None, **fields: Any) -> Any:
        body = _changes("portal.updateLink", changes, fields)
        return data_of(_call(self._api, "portal.updateLink", params={"linkId": link_id}, body=body))

    def revoke_link(self, link_id: str, reason: Optional[str] = None) -> Any:
        body = compact({"reason": optional_text(reason, "reason")})
        return data_of(_call(self._api, "portal.revokeLink", params={"linkId": link_id}, body=body))

    def link_activity(self, link_id: str) -> Any:
        return data_of(_call(self._api, "portal.linkActivity", params={"linkId": link_id}))

    def send_invite(self, invite: Request = None, **fields: Any) -> Any:
        """Emails a portal invite: ``customerId``, optional ``email``, ``allowedPlanIds`` …"""
        body = _changes("portal.sendInvite", invite, fields)
        return data_of(_call(self._api, "portal.sendInvite", body=body))

    def get_settings(self) -> Any:
        """Portal settings (branding, allowed origins)."""
        return data_of(_call(self._api, "portal.getSettings"))

    def update_settings(self, settings: Request = None, **fields: Any) -> Any:
        body = _changes("portal.updateSettings", settings, fields)
        return data_of(_call(self._api, "portal.updateSettings", body=body))


class SubscriptionProducts(_Section):
    """Catalog products (groups of plans)."""

    def create(self, product: Request = None, **fields: Any) -> Any:
        body = _changes("products.create", product, fields)
        return data_of(_call(self._api, "products.create", body=body))

    def list(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor``, ``active``."""
        return route_page(_call(self._api, "products.list", query=filters))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def get(self, product_id: str) -> Any:
        return data_of(_call(self._api, "products.get", params={"productId": product_id}))

    def update(self, product_id: str, changes: Request = None, **fields: Any) -> Any:
        body = _changes("products.update", changes, fields)
        params = {"productId": product_id}
        return data_of(_call(self._api, "products.update", params=params, body=body))

    def archive(self, product_id: str) -> Any:
        return data_of(_call(self._api, "products.archive", params={"productId": product_id}))

    def translations(self, product_id: str) -> Any:
        params = {"productId": product_id}
        return data_of(_call(self._api, "products.translations", params=params))

    def upsert_translation(
        self, product_id: str, locale: str, translation: Request = None, **fields: Any
    ) -> Any:
        body = _changes("products.upsertTranslation", translation, fields)
        params = {"productId": product_id, "locale": locale}
        return data_of(_call(self._api, "products.upsertTranslation", params=params, body=body))


class SubscriptionFeatures(_Section):
    """Entitlement features."""

    def create(self, feature: Request = None, **fields: Any) -> Any:
        body = _changes("features.create", feature, fields)
        return data_of(_call(self._api, "features.create", body=body))

    def list(self, **filters: Any) -> Page:
        """Any scalar filter is passed through (the gateway validates them)."""
        return route_page(_call(self._api, "features.list", query=filters))

    def get(self, feature_id: str) -> Any:
        return data_of(_call(self._api, "features.get", params={"featureId": feature_id}))

    def update(self, feature_id: str, changes: Request = None, **fields: Any) -> Any:
        body = _changes("features.update", changes, fields)
        params = {"featureId": feature_id}
        return data_of(_call(self._api, "features.update", params=params, body=body))

    def delete(self, feature_id: str) -> Any:
        return data_of(_call(self._api, "features.delete", params={"featureId": feature_id}))

    def translations(self, feature_id: str) -> Any:
        params = {"featureId": feature_id}
        return data_of(_call(self._api, "features.translations", params=params))

    def upsert_translation(
        self, feature_id: str, locale: str, translation: Request = None, **fields: Any
    ) -> Any:
        body = _changes("features.upsertTranslation", translation, fields)
        params = {"featureId": feature_id, "locale": locale}
        return data_of(_call(self._api, "features.upsertTranslation", params=params, body=body))


class SubscriptionAddons(_Section):
    """Add-ons."""

    def create(self, addon: Request = None, **fields: Any) -> Any:
        body = _changes("addons.create", addon, fields)
        return data_of(_call(self._api, "addons.create", body=body))

    def list(self, **filters: Any) -> Page:
        """Any scalar filter is passed through (the gateway validates them)."""
        return route_page(_call(self._api, "addons.list", query=filters))

    def update(self, addon_id: str, changes: Request = None, **fields: Any) -> Any:
        body = _changes("addons.update", changes, fields)
        return data_of(_call(self._api, "addons.update", params={"addonId": addon_id}, body=body))

    def deactivate(self, addon_id: str) -> Any:
        return data_of(_call(self._api, "addons.deactivate", params={"addonId": addon_id}))


class SubscriptionUsage(_Section):
    """Metered usage and entitlement checks."""

    def record(self, usage: Request = None, **fields: Any) -> Any:
        """A metered-usage event: ``customerId`` | ``subscriptionId``, ``featureKey``,
        ``quantity``, optional ``timestamp``, ``idempotencyKey`` …"""
        body = _changes("usage.record", usage, fields)
        return data_of(_call(self._api, "usage.record", body=body))

    def check_entitlement(self, check: Request = None, **fields: Any) -> Any:
        """Whether the customer is entitled / has quota left: ``customerId`` |
        ``subscriptionId``, ``featureKey``, optional ``requested`` …"""
        body = _changes("usage.checkEntitlement", check, fields)
        return data_of(_call(self._api, "usage.checkEntitlement", body=body))


# ── checks ───────────────────────────────────────────────────────────────────


def _changes(label: str, request: Request, fields: Mapping[str, Any]) -> Dict[str, Any]:
    """The body of a write the gateway validates; nothing given at all is refused."""
    if request is None and not fields:
        raise ConfigurationError(f"{label} needs a body (a mapping or keyword fields).")
    plain = plain_mapping(request, f"{label} body") if request is not None else None
    return merge_request(plain, fields)


def _currency(value: Any, field: str) -> str:
    code = value.strip().upper() if isinstance(value, str) else ""
    try:
        return currency_code(code)
    except ConfigurationError:
        raise ConfigurationError(f"{field} must be a supported ISO 4217 currency.") from None


def _billing_rule(value: Any) -> Dict[str, Any]:
    rule = compact(wire_fields(plain_mapping(value, "billing"), "billing"))
    unknown = [key for key in rule if key not in SUBSCRIPTION_BILLING_RULE_FIELDS]
    if unknown:
        raise ConfigurationError(f"billing does not accept {', '.join(unknown)}.")
    frequency = rule.get("frequency")
    out = dict(rule)
    out["frequency"] = check_value(
        "billing.frequency",
        SubscriptionBillingFrequency.ALL,
        (frequency if isinstance(frequency, str) else "").upper(),
    )
    out["interval"] = rule.get("interval", 1)
    _count_field(out, "interval", 1, "billing.interval")
    _count_field(out, "count", 0, "billing.count")
    if "byMonthDay" in out:
        out["byMonthDay"] = _integer_list(out["byMonthDay"], "billing.byMonthDay", 1, 31)
    if "byWeekDay" in out:
        days = out["byWeekDay"]
        if not isinstance(days, (list, tuple)) or any(not isinstance(day, str) for day in days):
            raise ConfigurationError(
                "billing.byWeekDay must be a list of week days (MO, TU, WE, TH, FR, SA, SU)."
            )
        out["byWeekDay"] = list(days)
    _boolean_field(out, "lastDayOfMonthFix", "billing.lastDayOfMonthFix")
    return out


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _boolean_field(body: Mapping[str, Any], field: str, label: Optional[str] = None) -> None:
    value = body.get(field)
    if value is not None and not isinstance(value, bool):
        raise ConfigurationError(f"{label or field} must be a boolean.")


def _count_field(
    body: Mapping[str, Any], field: str, minimum: int, label: Optional[str] = None
) -> None:
    value = body.get(field)
    if value is None:
        return
    if not _is_integer(value) or value < minimum:
        raise ConfigurationError(f"{label or field} must be an integer of at least {minimum}.")


def _integer_list(
    values: Any, field: str, minimum: int, maximum: Optional[int] = None
) -> List[int]:
    valid = isinstance(values, (list, tuple)) and all(
        _is_integer(value) and value >= minimum and (maximum is None or value <= maximum)
        for value in values
    )
    if not valid:
        upper = "" if maximum is None else f" to {maximum}"
        raise ConfigurationError(f"{field} must be a list of integers from {minimum}{upper}.")
    return list(values)
