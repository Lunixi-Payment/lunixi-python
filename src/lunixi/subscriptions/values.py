"""Subscriptions — ``/api/v1/subscriptions/*`` (and the portal-link routes under
``/api/panel/v1/subscriptions/portal``).

:data:`SUBSCRIPTION_ROUTES` is the single description of every route the
client calls: method, path, whether it is signed (``stepUp``, never here: the
subscription surface is bearer-only), the ``Idempotency-Key`` rule and the
body / query fields. Keys are the operation names (``plans.create``). It is the
same table as the Node SDK's ``SUBSCRIPTION_ROUTES`` and the shared catalog
(``contracts/products/subscriptions.json``); the values below are the same
codes as the other SDKs.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

from .._routes import freeze_routes

__all__ = [
    "SubscriptionStatus",
    "SUBSCRIPTION_ACTIVE_STATES",
    "SUBSCRIPTION_TERMINAL_STATES",
    "SubscriptionInvoiceStatus",
    "SubscriptionCollectionMethod",
    "SubscriptionBillingFrequency",
    "SubscriptionCardVerificationMode",
    "SubscriptionPlanChangeBehavior",
    "SubscriptionPortalSdkMode",
    "SUBSCRIPTION_PORTAL_HOSTED_BASE",
    "SubscriptionEvents",
    "SUBSCRIPTION_EVENT_TYPES",
    "SUBSCRIPTION_BILLING_RULE_FIELDS",
    "SUBSCRIPTION_ROUTES",
    "is_subscription_active",
    "is_subscription_terminal",
    "subscription_portal_url",
]


class SubscriptionStatus:
    """Subscription status."""

    #: ``startsAt`` is in the future.
    PENDING = "PENDING"
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    #: A charge failed; dunning runs.
    PAST_DUE = "PAST_DUE"
    #: Dunning exhausted; grace period.
    UNPAID = "UNPAID"
    #: Paused by the merchant; no charges.
    PAUSED = "PAUSED"
    UPGRADED = "UPGRADED"
    DOWNGRADED = "DOWNGRADED"
    CANCELED = "CANCELED"
    #: The recurrence ran out.
    EXPIRED = "EXPIRED"
    ALL = (
        PENDING,
        TRIALING,
        ACTIVE,
        PAST_DUE,
        UNPAID,
        PAUSED,
        UPGRADED,
        DOWNGRADED,
        CANCELED,
        EXPIRED,
    )


#: Live states: the subscription may be billed.
SUBSCRIPTION_ACTIVE_STATES = (
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
)

#: Terminal states: no further transition.
SUBSCRIPTION_TERMINAL_STATES = (
    SubscriptionStatus.UPGRADED,
    SubscriptionStatus.DOWNGRADED,
    SubscriptionStatus.CANCELED,
    SubscriptionStatus.EXPIRED,
)


class SubscriptionInvoiceStatus:
    """Invoice status: ``DRAFT`` → ``OPEN`` → ``PAID`` | ``UNCOLLECTIBLE`` | ``VOID``."""

    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"
    VOID = "VOID"
    ALL = (DRAFT, OPEN, PAID, UNCOLLECTIBLE, VOID)


class SubscriptionCollectionMethod:
    """How invoices are collected (``collectionMethod``).

    ``AUTO_CHARGE``: the saved card is charged each cycle (default).
    ``SEND_INVOICE``: the invoice is finalised but not charged.
    ``MANUAL``: collection is up to the merchant.
    """

    AUTO_CHARGE = "AUTO_CHARGE"
    SEND_INVOICE = "SEND_INVOICE"
    MANUAL = "MANUAL"
    ALL = (AUTO_CHARGE, SEND_INVOICE, MANUAL)


class SubscriptionBillingFrequency:
    """``billing.frequency`` of a plan."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    ALL = (DAILY, WEEKLY, MONTHLY, YEARLY)


class SubscriptionCardVerificationMode:
    """``verificationMode`` of a saved card."""

    NONE = "NONE"
    ON_ADD = "ON_ADD"
    FIRST_CHARGE = "FIRST_CHARGE"
    ALL = (NONE, ON_ADD, FIRST_CHARGE)


class SubscriptionPlanChangeBehavior:
    """``behavior`` of a plan change: now (prorated) or at the next period."""

    IMMEDIATE = "IMMEDIATE"
    NEXT_PERIOD = "NEXT_PERIOD"
    ALL = (IMMEDIATE, NEXT_PERIOD)


class SubscriptionPortalSdkMode:
    """``sdkMode`` of a portal SDK session."""

    FULL = "FULL"
    HEADLESS = "HEADLESS"
    HYBRID = "HYBRID"
    ALL = (FULL, HEADLESS, HYBRID)


#: Hosted customer portal; a portal link's ``token`` opens it (:func:`subscription_portal_url`).
SUBSCRIPTION_PORTAL_HOSTED_BASE = "https://portal.lunixi.com"


class SubscriptionEvents:
    """Webhook event types, verified with :class:`~lunixi.webhook.verifier.WebhookVerifier`.

    Same signed envelope as payment events; ``data`` amounts are minor-unit strings.
    """

    CREATED = "subscription.created"
    ACTIVATED = "subscription.activated"
    TRIAL_WILL_END = "subscription.trial_will_end"
    PAUSED = "subscription.paused"
    RESUMED = "subscription.resumed"
    CANCEL_SCHEDULED = "subscription.cancel_scheduled"
    CANCELED = "subscription.canceled"
    UPGRADED = "subscription.upgraded"
    DOWNGRADED = "subscription.downgraded"
    PLAN_CHANGE_SCHEDULED = "subscription.plan_change_scheduled"
    PENDING_CHANGE_APPLIED = "subscription.pending_change_applied"
    PAYMENT_CARD_SWAPPED = "subscription.payment_card_swapped"
    PAYMENT_METHOD_LOST = "subscription.payment_method_lost"
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    INVOICE_VOIDED = "invoice.voided"
    CARD_ADDED = "card.added"
    CARD_SET_DEFAULT = "card.set_default"
    CARD_UPDATED = "card.updated"
    CARD_DEACTIVATED = "card.deactivated"
    CARD_EXPIRING_SOON = "card.expiring_soon"
    CARD_EXPIRED = "card.expired"
    ALL = (
        CREATED,
        ACTIVATED,
        TRIAL_WILL_END,
        PAUSED,
        RESUMED,
        CANCEL_SCHEDULED,
        CANCELED,
        UPGRADED,
        DOWNGRADED,
        PLAN_CHANGE_SCHEDULED,
        PENDING_CHANGE_APPLIED,
        PAYMENT_CARD_SWAPPED,
        PAYMENT_METHOD_LOST,
        INVOICE_CREATED,
        INVOICE_PAID,
        INVOICE_PAYMENT_FAILED,
        INVOICE_VOIDED,
        CARD_ADDED,
        CARD_SET_DEFAULT,
        CARD_UPDATED,
        CARD_DEACTIVATED,
        CARD_EXPIRING_SOON,
        CARD_EXPIRED,
    )


SUBSCRIPTION_EVENT_TYPES = SubscriptionEvents.ALL

#: Fields of a plan's ``billing`` rule.
SUBSCRIPTION_BILLING_RULE_FIELDS = (
    "frequency",
    "interval",
    "byMonthDay",
    "byWeekDay",
    "timezone",
    "lastDayOfMonthFix",
    "count",
)

_SUBS = "/api/v1/subscriptions"
_PORTAL_PANEL = "/api/panel/v1/subscriptions/portal"
_CURSOR_QUERY = ["pageSize", "pageToken"]


def _route(method: str, path: str, **extra: Any) -> Mapping[str, Any]:
    return {"method": method, "path": path, "stepUp": False, "idempotencyKey": "none", **extra}


#: Every route the subscriptions client calls (Node ``SUBSCRIPTION_ROUTES``).
SUBSCRIPTION_ROUTES = freeze_routes(
    {
        "create": _route(
            "POST",
            f"{_SUBS}/subscriptions",
            idempotencyKey="required",
            required=["customerId", "planId", "idempotencyKey"],
            optional=[
                "paymentCardId",
                "paymentMethodId",
                "collectionMethod",
                "priceUpdatePolicy",
                "entitlementPolicy",
                "billingTimezone",
                "startsAt",
                "chargeOnCreate",
                "billingCycleAnchorOverride",
                "skipTrial",
                "metadata",
            ],
        ),
        "get": _route("GET", f"{_SUBS}/subscriptions/:subscriptionId"),
        "list": _route(
            "GET", f"{_SUBS}/subscriptions", query=["customerId", "status", *_CURSOR_QUERY]
        ),
        "cancel": _route(
            "POST",
            f"{_SUBS}/subscriptions/:subscriptionId/cancel",
            required=["cancelAtPeriodEnd"],
            optional=["reason"],
        ),
        "pause": _route(
            "POST",
            f"{_SUBS}/subscriptions/:subscriptionId/pause",
            optional=["resumeAt"],
            optionalBody=True,
        ),
        "resume": _route("POST", f"{_SUBS}/subscriptions/:subscriptionId/resume"),
        "changePlan": _route(
            "POST",
            f"{_SUBS}/subscriptions/:subscriptionId/change-plan",
            idempotencyKey="optional",
            required=["newPlanId"],
            optional=["behavior", "reason", "idempotencyKey"],
        ),
        "auditLogs": _route(
            "GET",
            f"{_SUBS}/subscriptions/:subscriptionId/audit-logs",
            query=["limit", "pageToken"],
        ),
        "plans.create": _route(
            "POST",
            f"{_SUBS}/plans",
            idempotencyKey="optional",
            required=["productId", "code", "name", "price", "currency", "billing"],
            optional=[
                "description",
                "trialPeriodDays",
                "maxDunningAttempts",
                "dunningScheduleDays",
                "gracePeriodDays",
                "metadata",
            ],
        ),
        "plans.get": _route("GET", f"{_SUBS}/plans/:planId"),
        "plans.list": _route(
            "GET", f"{_SUBS}/plans", query=["productId", "includeArchived", *_CURSOR_QUERY]
        ),
        "plans.update": _route("PATCH", f"{_SUBS}/plans/:planId", free=True),
        "plans.archive": _route("DELETE", f"{_SUBS}/plans/:planId"),
        "plans.translations": _route("GET", f"{_SUBS}/plans/:planId/translations"),
        "plans.upsertTranslation": _route(
            "PATCH", f"{_SUBS}/plans/:planId/translations/:locale", free=True
        ),
        "customers.upsert": _route(
            "PUT",
            f"{_SUBS}/customers",
            idempotencyKey="optional",
            required=["externalId"],
            optional=["email", "name", "phone", "locale", "metadata"],
        ),
        "customers.get": _route("GET", f"{_SUBS}/customers/:customerId"),
        "customers.getByExternalId": _route("GET", f"{_SUBS}/customers/by-external/:externalId"),
        "customers.list": _route(
            "GET", f"{_SUBS}/customers", query=["search", "includeArchived", *_CURSOR_QUERY]
        ),
        "customers.creditBalance": _route("GET", f"{_SUBS}/customers/:customerId/credit-balance"),
        "customers.adjustCredit": _route(
            "POST", f"{_SUBS}/customers/:customerId/credit-balance/adjust", free=True
        ),
        "customers.archive": _route("DELETE", f"{_SUBS}/customers/:customerId"),
        "cards.add": _route(
            "POST",
            f"{_SUBS}/cards",
            idempotencyKey="optional",
            required=["customerId", "paymentMethodToken"],
            optional=[
                "brand",
                "last4",
                "bin",
                "expireMonth",
                "expireYear",
                "cardholderName",
                "isDefault",
                "nickname",
                "verificationMode",
                "supportedCurrencies",
            ],
        ),
        "cards.get": _route("GET", f"{_SUBS}/cards/:cardId"),
        "cards.list": _route(
            "GET", f"{_SUBS}/cards", query=["customerId", "includeInactive", *_CURSOR_QUERY]
        ),
        "cards.setDefault": _route("POST", f"{_SUBS}/cards/:cardId/set-default"),
        "cards.deactivate": _route(
            "DELETE", f"{_SUBS}/cards/:cardId", optional=["reason"], optionalBody=True
        ),
        "cards.verify": _route(
            "POST", f"{_SUBS}/cards/:cardId/verify", free=True, optionalBody=True
        ),
        "cards.update": _route("PATCH", f"{_SUBS}/cards/:cardId", free=True),
        "invoices.list": _route(
            "GET", f"{_SUBS}/invoices", query=["subscriptionId", "status", *_CURSOR_QUERY]
        ),
        "invoices.get": _route("GET", f"{_SUBS}/invoices/:invoiceId"),
        "invoices.void": _route(
            "POST", f"{_SUBS}/invoices/:invoiceId/void", optional=["reason"], optionalBody=True
        ),
        "invoices.retryCharge": _route(
            "POST", f"{_SUBS}/invoices/:invoiceId/retry-charge", idempotencyKey="optional"
        ),
        "portal.createSdkSession": _route(
            "POST",
            f"{_SUBS}/portal/sdk-session",
            required=["customerId", "origin"],
            optional=["sdkMode", "portalLinkId"],
        ),
        "portal.createPortalLink": _route("POST", f"{_PORTAL_PANEL}/links", free=True),
        "portal.listLinks": _route(
            "GET", f"{_PORTAL_PANEL}/links", query=["customerId", "status", "limit"]
        ),
        "portal.getLink": _route("GET", f"{_PORTAL_PANEL}/links/:linkId"),
        "portal.updateLink": _route("PATCH", f"{_PORTAL_PANEL}/links/:linkId", free=True),
        "portal.revokeLink": _route(
            "DELETE", f"{_PORTAL_PANEL}/links/:linkId", optional=["reason"], optionalBody=True
        ),
        "portal.linkActivity": _route("GET", f"{_PORTAL_PANEL}/links/:linkId/activity"),
        "portal.sendInvite": _route("POST", f"{_PORTAL_PANEL}/invite", free=True),
        "portal.getSettings": _route("GET", f"{_PORTAL_PANEL}/settings"),
        "portal.updateSettings": _route("PUT", f"{_PORTAL_PANEL}/settings", free=True),
        "products.create": _route("POST", f"{_SUBS}/products", free=True),
        "products.list": _route("GET", f"{_SUBS}/products", query=["limit", "cursor", "active"]),
        "products.get": _route("GET", f"{_SUBS}/products/:productId"),
        "products.update": _route("PATCH", f"{_SUBS}/products/:productId", free=True),
        "products.archive": _route("DELETE", f"{_SUBS}/products/:productId"),
        "products.translations": _route("GET", f"{_SUBS}/products/:productId/translations"),
        "products.upsertTranslation": _route(
            "PATCH", f"{_SUBS}/products/:productId/translations/:locale", free=True
        ),
        "features.create": _route("POST", f"{_SUBS}/features", free=True),
        "features.list": _route("GET", f"{_SUBS}/features", anyQuery=True),
        "features.get": _route("GET", f"{_SUBS}/features/:featureId"),
        "features.update": _route("PATCH", f"{_SUBS}/features/:featureId", free=True),
        "features.delete": _route("DELETE", f"{_SUBS}/features/:featureId"),
        "features.translations": _route("GET", f"{_SUBS}/features/:featureId/translations"),
        "features.upsertTranslation": _route(
            "PATCH", f"{_SUBS}/features/:featureId/translations/:locale", free=True
        ),
        "addons.create": _route("POST", f"{_SUBS}/addons", free=True),
        "addons.list": _route("GET", f"{_SUBS}/addons", anyQuery=True),
        "addons.update": _route("PATCH", f"{_SUBS}/addons/:addonId", free=True),
        "addons.deactivate": _route("DELETE", f"{_SUBS}/addons/:addonId"),
        "usage.record": _route("POST", f"{_SUBS}/usage/record", free=True),
        "usage.checkEntitlement": _route("POST", f"{_SUBS}/usage/check-entitlement", free=True),
    }
)


def _status_of(subscription: Any) -> str:
    if isinstance(subscription, str):
        return subscription
    status = subscription.get("status") if isinstance(subscription, Mapping) else None
    return status if isinstance(status, str) else ""


def is_subscription_active(subscription: Any) -> bool:
    """True while the subscription may be billed (``TRIALING``, ``ACTIVE``, ``PAST_DUE``).

    Takes a subscription mapping or its status.
    """
    return _status_of(subscription) in SUBSCRIPTION_ACTIVE_STATES


def is_subscription_terminal(subscription: Any) -> bool:
    """True for ``UPGRADED``, ``DOWNGRADED``, ``CANCELED``, ``EXPIRED``."""
    return _status_of(subscription) in SUBSCRIPTION_TERMINAL_STATES


def subscription_portal_url(link: Any, base: str = SUBSCRIPTION_PORTAL_HOSTED_BASE) -> str:
    """Hosted portal URL of a portal link (the ``portal.create_portal_link()`` answer, or
    its token)."""
    if isinstance(link, str):
        token = link
    else:
        value = link.get("token") if isinstance(link, Mapping) else None
        token = value if isinstance(value, str) else ""
    return str(base).rstrip("/") + "/?token=" + quote(token, safe="!*'()")
