"""Subscriptions: bearer-only calls, the route table, idempotency keys, money checks and paging.

Names in the fixtures are fictional.
"""

from __future__ import annotations

import pytest

from lunixi._routes import send_route
from lunixi.errors import ConfigurationError
from lunixi.subscriptions import (
    SUBSCRIPTION_ROUTES,
    SubscriptionCollectionMethod,
    SubscriptionEvents,
    SubscriptionPage,
    SubscriptionPortalSdkMode,
    SubscriptionsClient,
    SubscriptionStatus,
    is_subscription_active,
    is_subscription_terminal,
    subscription_portal_url,
)

from .support.recording_transport import envelope, json_response
from .support.wire import assert_unsigned, body_of, path_of, query_of


def ok(data, **extra):
    return json_response(envelope(data, **extra))


def test_the_client_has_every_sub_client(client_factory):
    _, client = client_factory()
    subscriptions = client.subscriptions()
    assert isinstance(subscriptions, SubscriptionsClient)
    for name in (
        "plans",
        "customers",
        "cards",
        "invoices",
        "portal",
        "products",
        "features",
        "addons",
        "usage",
    ):
        assert getattr(subscriptions, name) is not None, name


def test_the_route_table_is_bearer_only_and_keeps_the_api_paths():
    for name, route in SUBSCRIPTION_ROUTES.items():
        assert route["stepUp"] is False, name
        assert route["path"].startswith(
            ("/api/v1/subscriptions/", "/api/panel/v1/subscriptions/")
        ), name
    assert SUBSCRIPTION_ROUTES["create"]["idempotencyKey"] == "required"
    assert (
        SUBSCRIPTION_ROUTES["portal.createPortalLink"]["path"]
        == "/api/panel/v1/subscriptions/portal/links"
    )


def test_values_and_helpers():
    assert SubscriptionStatus.PAST_DUE == "PAST_DUE"
    assert SubscriptionEvents.TRIAL_WILL_END == "subscription.trial_will_end"
    assert SubscriptionEvents.INVOICE_PAYMENT_FAILED == "invoice.payment_failed"
    assert SubscriptionEvents.CARD_EXPIRING_SOON == "card.expiring_soon"
    assert len(SubscriptionEvents.ALL) == 23
    assert is_subscription_active({"status": "PAST_DUE"}) is True
    assert is_subscription_active("PAUSED") is False
    assert is_subscription_terminal("CANCELED") is True
    assert subscription_portal_url("cp xyz") == "https://portal.lunixi.com/?token=cp%20xyz"


def test_create_sends_the_key_in_the_header_and_the_body(client_factory):
    created = {"id": "sub_1", "status": "ACTIVE", "priceSnapshotAmount": "9900"}
    transport, client = client_factory(ok(created))
    subscription = client.subscriptions().create(
        customer_id="cus_1",
        plan_id="plan_1",
        payment_card_id="card_1",
        collection_method=SubscriptionCollectionMethod.AUTO_CHARGE,
        idempotency_key="idem-sub-1",
    )
    assert subscription == created
    request = transport.last
    assert (request.method, path_of(request)) == ("POST", "/api/v1/subscriptions/subscriptions")
    assert request.header("Idempotency-Key") == "idem-sub-1"
    assert_unsigned(request)
    assert body_of(request) == {
        "customerId": "cus_1",
        "planId": "plan_1",
        "paymentCardId": "card_1",
        "collectionMethod": "AUTO_CHARGE",
        "idempotencyKey": "idem-sub-1",
    }


@pytest.mark.parametrize(
    "fields, key, message",
    [
        ({"customerId": "cus_1", "planId": "plan_1"}, None, "Idempotency-Key is required"),
        ({"customerId": "cus_1", "planId": "plan_1", "amount": "1"}, "k1", "not accept amount"),
        ({"customerId": "cus_1", "planId": "plan_1", "collectionMethod": "CASH"}, "k1", "one of"),
        ({"customerId": "cus_1", "planId": "plan_1", "idempotencyKey": "a"}, "b", "differ"),
        ({"customerId": "cus_1", "planId": "plan_1", "skipTrial": "yes"}, "k1", "boolean"),
        ({"planId": "plan_1"}, "k1", "requires customerId"),
    ],
)
def test_create_is_refused_before_sending(client_factory, fields, key, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.subscriptions().create(fields, idempotency_key=key)
    assert transport.requests == []


def test_cancel_pause_resume_and_change_plan(client_factory):
    answer = ok({"id": "sub_1", "status": "ACTIVE"})
    transport, client = client_factory(answer, answer, answer, answer, answer)
    subscriptions = client.subscriptions()
    subscriptions.cancel("sub_1", at_period_end=True, reason="too expensive")
    subscriptions.pause("sub_1")
    subscriptions.pause("sub_1", "2026-12-01T00:00:00Z")
    subscriptions.resume("sub_1")
    subscriptions.change_plan(
        "sub_1", new_plan_id="plan_2", behavior="next_period", idempotency_key="idem-cp-1"
    )
    cancel, pause, pause_until, resume, change = transport.requests[1:]
    assert path_of(cancel) == "/api/v1/subscriptions/subscriptions/sub_1/cancel"
    assert body_of(cancel) == {"cancelAtPeriodEnd": True, "reason": "too expensive"}
    assert pause.body is None
    assert body_of(pause_until) == {"resumeAt": "2026-12-01T00:00:00Z"}
    assert path_of(resume) == "/api/v1/subscriptions/subscriptions/sub_1/resume"
    assert resume.body is None
    assert path_of(change) == "/api/v1/subscriptions/subscriptions/sub_1/change-plan"
    assert change.header("Idempotency-Key") == "idem-cp-1"
    assert body_of(change) == {
        "newPlanId": "plan_2",
        "behavior": "NEXT_PERIOD",
        "idempotencyKey": "idem-cp-1",
    }


def test_plan_lists_read_the_token_envelope_and_send_booleans(client_factory):
    plans = [{"id": "plan_1", "name": "Pro", "price": "9900", "currency": "TRY"}]
    transport, client = client_factory(ok(plans, nextPageToken="tok_next", pageSize=20))
    page = client.subscriptions().plans.list(include_archived=False, product_id="prod_1")
    assert isinstance(page, SubscriptionPage)
    assert page.items == plans
    assert page.next_page_token == "tok_next"
    assert page.next_cursor == "tok_next"
    assert page.has_more is True
    assert page.page_size == 20
    assert query_of(transport.last) == {"includeArchived": ["false"], "productId": ["prod_1"]}
    with pytest.raises(ConfigurationError, match="does not accept the filter"):
        client.subscriptions().plans.list(archived=True)


def test_iterate_follows_the_page_token(client_factory):
    transport, client = client_factory(
        ok([{"id": "sub_1"}], nextPageToken="tok_2"),
        ok([{"id": "sub_2"}]),
    )
    rows = list(client.subscriptions().iterate(customer_id="cus_1", page_size=1))
    assert [row["id"] for row in rows] == ["sub_1", "sub_2"]
    first, second = transport.requests[1:]
    assert "pageToken" not in query_of(first)
    assert query_of(second) == {"customerId": ["cus_1"], "pageSize": ["1"], "pageToken": ["tok_2"]}


def test_plans_create_checks_price_currency_and_the_billing_rule(client_factory):
    transport, client = client_factory(ok({"id": "plan_1", "price": "0"}))
    plan = {
        "productId": "prod_1",
        "code": "free",
        "name": "Free",
        "price": "0",
        "currency": "try",
        "billing": {"frequency": "monthly"},
    }
    client.subscriptions().plans.create(plan, idempotency_key="idem-plan-1")
    request = transport.last
    assert path_of(request) == "/api/v1/subscriptions/plans"
    assert request.header("Idempotency-Key") == "idem-plan-1"
    assert body_of(request)["billing"] == {"frequency": "MONTHLY", "interval": 1}
    assert body_of(request)["currency"] == "TRY"

    plans = client.subscriptions().plans
    for broken, message in (
        ({**plan, "price": 9900}, "price must be a canonical string"),
        ({**plan, "currency": "XXX"}, "currency"),
        ({**plan, "billing": {"frequency": "HOURLY"}}, "billing.frequency"),
        ({**plan, "billing": {"frequency": "DAILY", "interval": 0}}, "billing.interval"),
        ({**plan, "billing": {"frequency": "DAILY", "every": 2}}, "billing does not accept"),
        ({**plan, "trialPeriodDays": -1}, "trialPeriodDays"),
    ):
        with pytest.raises(ConfigurationError, match=message):
            plans.create(broken)
    assert len(transport.requests) == 2


def test_an_answer_with_a_numeric_amount_is_refused(client_factory):
    _, client = client_factory(ok({"id": "inv_1", "totalAmount": 9900}))
    with pytest.raises(ConfigurationError, match="totalAmount must be a canonical string"):
        client.subscriptions().invoices.get("inv_1")


def test_cards_add_sends_the_token_and_refuses_card_numbers_without_echoing_them(
    client_factory,
):
    transport, client = client_factory(ok({"id": "card_1", "last4": "4242", "isDefault": True}))
    cards = client.subscriptions().cards
    card = cards.add(
        customer_id="cus_1",
        payment_method_token="tok_abc",
        brand="VISA",
        last4="4242",
        expire_month=12,
        expire_year=2030,
        is_default=True,
    )
    assert card["last4"] == "4242"
    assert body_of(transport.last)["paymentMethodToken"] == "tok_abc"

    with pytest.raises(ConfigurationError) as raised:
        cards.add(
            customer_id="cus_1", payment_method_token="tok_abc", card_number="4111111111111111"
        )
    assert "cardNumber" in str(raised.value)
    assert "4111" not in str(raised.value)
    assert len(transport.requests) == 2


def test_card_list_default_deactivate_and_invoice_operations(client_factory):
    answers = [ok([]) for _ in range(6)]
    transport, client = client_factory(*answers)
    subscriptions = client.subscriptions()
    subscriptions.cards.list("cus_1", page_size=10)
    subscriptions.cards.set_default("card_1")
    subscriptions.cards.deactivate("card_1")
    subscriptions.invoices.list(subscription_id="sub_1", status="OPEN")
    subscriptions.invoices.void("inv_1", "duplicate")
    subscriptions.invoices.retry_charge("inv_1", idempotency_key="idem-retry-1")
    cards, default, deactivate, invoices, void, retry = transport.requests[1:]
    assert cards.url.endswith(
        "/api/v1/subscriptions/cards?customerId=cus_1&includeInactive=false&pageSize=10"
    )
    assert path_of(default) == "/api/v1/subscriptions/cards/card_1/set-default"
    assert (deactivate.method, deactivate.body) == ("DELETE", None)
    assert query_of(invoices) == {"subscriptionId": ["sub_1"], "status": ["OPEN"]}
    assert body_of(void) == {"reason": "duplicate"}
    assert path_of(retry) == "/api/v1/subscriptions/invoices/inv_1/retry-charge"
    assert retry.header("Idempotency-Key") == "idem-retry-1"
    for request in transport.requests[1:]:
        assert_unsigned(request)


def test_customers_upsert_lookup_and_credit(client_factory):
    answer = ok({"id": "cus_1", "externalId": "u-42"})
    transport, client = client_factory(answer, answer, answer)
    customers = client.subscriptions().customers
    customers.upsert(external_id="u-42", email="ada@example.com", idempotency_key="idem-cus-1")
    customers.get_by_external_id("u-42")
    customers.adjust_credit("cus_1", amount_minor="500", currency="TRY", type="GRANT")
    upsert, lookup, credit = transport.requests[1:]
    assert (upsert.method, path_of(upsert)) == ("PUT", "/api/v1/subscriptions/customers")
    assert upsert.header("Idempotency-Key") == "idem-cus-1"
    assert path_of(lookup) == "/api/v1/subscriptions/customers/by-external/u-42"
    assert path_of(credit) == "/api/v1/subscriptions/customers/cus_1/credit-balance/adjust"
    assert body_of(credit) == {"amountMinor": "500", "currency": "TRY", "type": "GRANT"}
    with pytest.raises(ConfigurationError, match="amountMinor"):
        customers.adjust_credit("cus_1", amount_minor=5)
    assert len(transport.requests) == 4


def test_the_portal_sdk_session_reads_the_proof_at_the_envelope_root(client_factory):
    answer = json_response(
        envelope(
            None,
            portalToken="cp_abc",
            sessionProof="hmac_xyz",
            nonce="nonce_1",
            expiresAt="2026-06-16T03:00:00Z",
        )
    )
    transport, client = client_factory(answer)
    portal = client.subscriptions().portal
    session = portal.create_sdk_session(
        "cus_1", "https://shop.example", sdk_mode=SubscriptionPortalSdkMode.HYBRID
    )
    assert session["portalToken"] == "cp_abc"
    assert session["sessionProof"] == "hmac_xyz"
    assert session["proofNonce"] == "nonce_1"
    assert session["proofExpiresAt"] == "2026-06-16T03:00:00Z"
    assert path_of(transport.last) == "/api/v1/subscriptions/portal/sdk-session"
    assert body_of(transport.last) == {
        "customerId": "cus_1",
        "origin": "https://shop.example",
        "sdkMode": "HYBRID",
    }
    with pytest.raises(ConfigurationError, match="sdkMode"):
        portal.create_sdk_session("cus_1", "https://shop.example", sdk_mode="EMBED")
    assert len(transport.requests) == 2


def test_a_portal_link_is_created_on_the_panel_route_and_gives_the_hosted_url(client_factory):
    link_data = {"id": "lnk_1", "customerId": "cus_1", "token": "cp_xyz", "status": "ACTIVE"}
    transport, client = client_factory(ok(link_data), ok(None))
    portal = client.subscriptions().portal
    link = portal.create_portal_link("cus_1", allowed_plan_ids=["plan_1"])
    assert subscription_portal_url(link) == "https://portal.lunixi.com/?token=cp_xyz"
    assert path_of(transport.last) == "/api/panel/v1/subscriptions/portal/links"
    assert body_of(transport.last) == {"allowedPlanIds": ["plan_1"], "customerId": "cus_1"}
    assert_unsigned(transport.last)

    portal.revoke_link("lnk_1")
    assert (transport.last.method, transport.last.body) == ("DELETE", None)


def test_other_panel_paths_stay_refused(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.api().request("GET", "/api/panel/v1/subscriptions/plans")
    with pytest.raises(ConfigurationError):
        client.api().request("GET", "/api/panel/v1/subscriptions/portal/../../x")
    assert transport.requests == []


def test_catalog_feature_addon_and_usage_routes(client_factory):
    listing = ok({"items": [{"id": "prod_1"}], "pageInfo": {"hasMore": False, "nextCursor": None}})
    transport, client = client_factory(listing, *(ok({}) for _ in range(5)))
    subscriptions = client.subscriptions()
    page = subscriptions.products.list(limit=5, active=True)
    subscriptions.products.upsert_translation("prod_1", "en", name="Pro")
    subscriptions.features.delete("feat_1")
    subscriptions.addons.deactivate("addon_1")
    subscriptions.usage.record(subscription_id="sub_1", feature_key="api_calls", quantity=3)
    subscriptions.usage.check_entitlement(subscription_id="sub_1", feature_key="api_calls")
    products, translation, feature, addon, record, check = transport.requests[1:]
    assert page.items == [{"id": "prod_1"}]
    assert page.has_more is False and page.next_cursor is None
    assert products.url.endswith("/api/v1/subscriptions/products?limit=5&active=true")
    assert translation.method == "PATCH"
    assert path_of(translation) == "/api/v1/subscriptions/products/prod_1/translations/en"
    assert body_of(translation) == {"name": "Pro"}
    assert feature.method == "DELETE"
    assert path_of(addon) == "/api/v1/subscriptions/addons/addon_1"
    assert path_of(record) == "/api/v1/subscriptions/usage/record"
    assert body_of(record) == {"subscriptionId": "sub_1", "featureKey": "api_calls", "quantity": 3}
    assert path_of(check) == "/api/v1/subscriptions/usage/check-entitlement"


def test_the_table_caller_refuses_what_a_route_does_not_take(client_factory):
    transport, client = client_factory()
    resume = {"subscriptionId": "sub_1"}
    with pytest.raises(ConfigurationError, match="needs a body"):
        client.subscriptions().plans.update("plan_1")
    with pytest.raises(ConfigurationError, match="takes no body"):
        send_route(client.api(), SUBSCRIPTION_ROUTES, "resume", params=resume, body={"x": 1})
    with pytest.raises(ConfigurationError, match="does not take an Idempotency-Key"):
        send_route(client.api(), SUBSCRIPTION_ROUTES, "resume", params=resume, idempotency_key="k")
    with pytest.raises(ConfigurationError, match="subscriptionId is required"):
        client.subscriptions().get("  ")
    with pytest.raises(ConfigurationError, match="must be a string, number or boolean"):
        client.subscriptions().list(status=["ACTIVE"])
    assert transport.requests == []
