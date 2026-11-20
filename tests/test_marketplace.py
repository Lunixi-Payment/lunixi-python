"""Marketplace: signed split charges with seller legs, bearer-only dealer routes, payouts.

Names and card data in the fixtures are fictional test values.
"""

from __future__ import annotations

import logging

import pytest

from lunixi.errors import ApiError, ConfigurationError
from lunixi.marketplace import (
    MARKETPLACE_ROUTES,
    MarketplaceClient,
    MarketplaceDealerStatus,
    MarketplaceMultiSellerPolicy,
    marketplace_onboarding_url,
)
from lunixi.payments import CreateIntent

from .support.order_details import BILLING_ADDRESS, BUYER, intent_details, order_details
from .support.recording_transport import envelope, json_response
from .support.wire import assert_signed, assert_unsigned, body_of, path_of

CARD_NUMBER = "5400000000000004"
CVC = "123"


def ok(data, **extra):
    return json_response(envelope(data, **extra))


def legs():
    return [
        {"subDealerId": "d_alice", "amountMinor": "60000"},
        {
            "subDealerId": "d_bob",
            "amountMinor": "40000",
            "scenario": {"type": "DYNAMIC_RATE", "ratePercent": "5"},
        },
    ]


def charge_request(amount="100000"):
    return {
        "amount": amount,
        "currency": "TRY",
        "orderId": "ORD-MP-1",
        "card": {
            "cardHolderName": "Ada Yilmaz",
            "cardNumber": CARD_NUMBER,
            "expireMonth": "12",
            "expireYear": "28",
            "cvcNumber": CVC,
        },
        "buyer": dict(BUYER),
        "billingAddress": dict(BILLING_ADDRESS),
        "shippingAddress": dict(BILLING_ADDRESS),
        "basketItems": [
            {
                "id": "SKU-1",
                "price": amount,
                "name": "Demo",
                "category1": "Demo",
                "itemType": "PHYSICAL",
            }
        ],
    }


def test_charges_are_signed_and_dealer_routes_bearer_only(client_factory):
    _, client = client_factory()
    assert isinstance(client.marketplace(), MarketplaceClient)
    for name, route in MARKETPLACE_ROUTES.items():
        charge = route["path"].startswith("/api/v1/payments/marketplace/")
        assert route["stepUp"] is charge, name
        if not charge:
            assert route["path"].startswith("/api/v1/marketplace/"), name


def test_create_checkout_intent_sends_the_split_signed_with_the_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    answer = ok({"paymentId": "pi_1", "token": "tok_1", "checkoutFormContent": "<script>"})
    transport, client = client_factory(answer)
    intent = client.marketplace().create_checkout_intent(
        CreateIntent("100000", "TRY", "WC-7", **intent_details("100000")),
        legs(),
        MarketplaceMultiSellerPolicy.ALL_OR_NOTHING,
        idempotency_key="idem-mp-1",
    )
    assert intent["data"]["token"] == "tok_1"
    request = transport.last
    assert path_of(request) == "/api/v1/payments/marketplace/intents"
    assert_signed(request, public_key)
    assert request.header("Idempotency-Key") == "idem-mp-1"
    body = body_of(request)
    assert body["amount"] == "100000"
    assert body["multiSellerPolicy"] == "ALL_OR_NOTHING"
    assert body["sellers"][0] == {"subDealerId": "d_alice", "amountMinor": "60000"}
    assert body["sellers"][1]["scenario"]["type"] == "DYNAMIC_RATE"


def test_create_checkout_intent_raises_when_the_answer_has_no_token(client_factory):
    _, client = client_factory(ok({}, code="marketplace.payment.seller_not_eligible"))
    with pytest.raises(ApiError) as raised:
        client.marketplace().create_checkout_intent(
            {"amount": "1000", "currency": "TRY", "orderId": "o1", **order_details("1000")},
            [{"subDealerId": "d_1", "amountMinor": "1000"}],
        )
    assert raised.value.code == "marketplace.payment.seller_not_eligible"


@pytest.mark.parametrize(
    "sellers, policy, message",
    [
        ([], MarketplaceMultiSellerPolicy.ALL_OR_NOTHING, "at least one seller"),
        ([{"subDealerId": "d_1", "amountMinor": "0"}], "ALL_OR_NOTHING", "amountMinor"),
        ([{"subDealerId": "d_1", "amountMinor": 1000}], "ALL_OR_NOTHING", "amountMinor"),
        ([{"subDealerId": "d_1", "amountMinor": "999"}], "ALL_OR_NOTHING", "add up to 999"),
        ([{"subDealerId": "d_1", "amountMinor": "1000"}], "SOME", "multiSellerPolicy"),
        ([{"subDealerId": "d_1", "amountMinor": "1000", "iban": "TR"}], "ALL_OR_NOTHING", "iban"),
        ([{"amountMinor": "1000"}], "ALL_OR_NOTHING", "subDealerId"),
    ],
)
def test_seller_legs_are_checked_before_sending(client_factory, sellers, policy, message):
    transport, client = client_factory()
    intent = CreateIntent("1000", "TRY", "o1", **intent_details("1000"))
    with pytest.raises(ConfigurationError, match=message):
        client.marketplace().create_checkout_intent(intent, sellers, policy)
    assert transport.requests == []


def test_legs_in_the_body_are_refused(client_factory):
    transport, client = client_factory()
    body = {**charge_request(), "sellers": legs()}
    with pytest.raises(ConfigurationError, match="as arguments"):
        client.marketplace().charge_marketplace_card2d(body, legs())
    assert transport.requests == []


def test_card_charges_go_to_the_2d_and_3d_routes(client_factory, test_key_pair):
    _, public_key = test_key_pair
    answer = ok({"paymentId": "pay_1", "status": "SUCCEEDED"})
    transport, client = client_factory(answer, answer)
    marketplace = client.marketplace()
    marketplace.charge_marketplace_card2d(
        charge_request(),
        legs(),
        MarketplaceMultiSellerPolicy.PARTIAL_ALLOWED,
        idempotency_key="idem-2d",
    )
    marketplace.charge_marketplace_card3d(
        {**charge_request(), "callbackUrl": "https://shop.example/3ds"}, legs()
    )
    two_d, three_d = transport.requests[1:]
    assert path_of(two_d) == "/api/v1/payments/marketplace/2d"
    assert path_of(three_d) == "/api/v1/payments/marketplace/3d"
    assert_signed(two_d, public_key)
    assert_signed(three_d, public_key)
    assert two_d.header("Idempotency-Key") == "idem-2d"
    assert three_d.header("Idempotency-Key") is None
    body = body_of(two_d)
    assert body["multiSellerPolicy"] == "PARTIAL_ALLOWED"
    assert len(body["sellers"]) == 2
    assert body["card"]["cardNumber"] == CARD_NUMBER
    assert body_of(three_d)["multiSellerPolicy"] == "ALL_OR_NOTHING"


def test_a_broken_charge_is_refused_without_echoing_or_logging_the_card(client_factory, caplog):
    transport, client = client_factory()
    marketplace = client.marketplace()
    no_buyer = {key: value for key, value in charge_request().items() if key != "buyer"}
    attempts = [
        lambda: marketplace.charge_marketplace_card2d(no_buyer, legs()),
        lambda: marketplace.charge_marketplace_card2d(
            {**charge_request(), "price": "100000"}, legs()
        ),
        lambda: marketplace.charge_marketplace_card2d(
            {**charge_request(), "preauth": "false"}, legs()
        ),
        lambda: marketplace.charge_marketplace_card2d(
            {**charge_request(), "basketItems": []}, legs()
        ),
        lambda: marketplace.charge_marketplace_card({**charge_request(), "amount": 100000}),
    ]
    messages = []
    with caplog.at_level(logging.DEBUG):
        for attempt in attempts:
            with pytest.raises(ConfigurationError) as raised:
                attempt()
            messages.append(str(raised.value))
    for message in messages:
        assert CARD_NUMBER not in message
        assert CVC not in message
    assert "buyer" in messages[0]
    assert CARD_NUMBER not in caplog.text
    assert transport.requests == []


def test_dealer_lifecycle_routes_are_bearer_only(client_factory):
    answer = ok({"id": "d_1", "legalName": "Acme", "status": "DRAFT"})
    transport, client = client_factory(answer, answer, answer, answer)
    marketplace = client.marketplace()
    dealer = marketplace.create_dealer(legal_name="Acme", tax_id="1234567890", external_ref="42")
    assert dealer["id"] == "d_1"
    marketplace.update_dealer_status("d_1", MarketplaceDealerStatus.SUSPENDED)
    marketplace.activate_dealer("d_1")
    marketplace.set_dealer_terms("d_1", commission_bps=250)
    create, status, activate, terms = transport.requests[1:]
    assert path_of(create) == "/api/v1/marketplace/dealers"
    assert body_of(create) == {
        "legalName": "Acme",
        "taxId": "1234567890",
        "externalRef": "42",
    }
    assert (status.method, body_of(status)) == ("PUT", {"status": "SUSPENDED"})
    assert path_of(activate) == "/api/v1/marketplace/dealers/d_1/activate"
    assert activate.body is None
    assert path_of(terms) == "/api/v1/marketplace/dealers/d_1/terms"
    assert body_of(terms) == {"commissionBps": 250}
    for request in transport.requests[1:]:
        assert_unsigned(request)

    with pytest.raises(ConfigurationError, match="status must be one of"):
        marketplace.update_dealer_status("d_1", "PAUSED")
    with pytest.raises(ConfigurationError, match="dealerType"):
        marketplace.create_dealer(legal_name="Acme", dealer_type="COMPANY")
    with pytest.raises(ConfigurationError, match="requires legalName"):
        marketplace.create_dealer(tax_id="1234567890")
    with pytest.raises(ConfigurationError, match="needs a payload"):
        marketplace.set_dealer_terms("d_1")
    assert len(transport.requests) == 5


def test_list_dealers_reads_the_items_envelope(client_factory):
    rows = {
        "items": [{"id": "d_1", "status": "ACTIVE"}, {"id": "d_2", "status": "DRAFT"}],
        "total": 2,
        "pageInfo": {"hasMore": False, "nextCursor": None, "totalCount": 2},
    }
    transport, client = client_factory(ok(rows))
    page = client.marketplace().list_dealers(status="ACTIVE", limit=20, offset=40)
    assert len(page.items) == 2
    assert page.total_count == 2
    assert page.has_more is False
    assert transport.last.url.endswith(
        "/api/v1/marketplace/dealers?status=ACTIVE&limit=20&offset=40"
    )


def test_the_onboarding_link_is_the_answer_url_else_the_hosted_wizard(client_factory):
    transport, client = client_factory(json_response(envelope(None, token="mp_xyz")))
    link = client.marketplace().onboarding_token("d_1")
    assert path_of(transport.last) == "/api/v1/marketplace/dealers/d_1/onboarding-token"
    assert link["token"] == "mp_xyz"
    assert marketplace_onboarding_url(link) == "https://altbayi.lunixi.com/m/mp_xyz"
    explicit = {"token": "mp_xyz", "url": "https://onboard.example/m/mp_xyz"}
    assert marketplace_onboarding_url(explicit) == "https://onboard.example/m/mp_xyz"


def test_payouts_commissions_and_the_audit_log(client_factory):
    transport, client = client_factory(*(ok({"items": []}) for _ in range(5)))
    marketplace = client.marketplace()
    marketplace.create_payout(sub_dealer_id="d_1", amount_minor="5000", currency="TRY")
    marketplace.resolve_commission("d_1", category_code="ELECTRONICS", mtd_volume_minor="100000")
    marketplace.bulk_mark_payouts_paid(["po_1", "po_2"], reference="R-1")
    marketplace.audit_log(limit=20)
    marketplace.verify_audit_log()
    payout, resolve, bulk, audit, verify = transport.requests[1:]
    assert path_of(payout) == "/api/v1/marketplace/payouts"
    assert body_of(payout) == {"subDealerId": "d_1", "amountMinor": "5000", "currency": "TRY"}
    assert resolve.url.endswith(
        "/api/v1/marketplace/commission/resolve"
        "?subDealerId=d_1&categoryCode=ELECTRONICS&mtdVolumeMinor=100000"
    )
    assert body_of(bulk) == {"reference": "R-1", "payoutIds": ["po_1", "po_2"]}
    assert audit.url.endswith("/api/v1/marketplace/audit-log?limit=20")
    assert path_of(verify) == "/api/v1/marketplace/audit-log/verify"

    with pytest.raises(ConfigurationError, match="amountMinor"):
        marketplace.create_payout(sub_dealer_id="d_1", amount_minor=5000)
    with pytest.raises(ConfigurationError, match="mtdVolumeMinor"):
        marketplace.resolve_commission("d_1", mtd_volume_minor=100000)
    with pytest.raises(ConfigurationError, match="does not accept the filter"):
        marketplace.commission_rules(include_archived=True)
    with pytest.raises(ConfigurationError, match="non-empty list of payout ids"):
        marketplace.bulk_mark_payouts_paid([])
    assert len(transport.requests) == 6
