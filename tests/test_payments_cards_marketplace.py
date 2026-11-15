"""BIN info, installment options, card taxonomy, stored cards, marketplace intents, analytics."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi import CreateIntent, InstallmentOptionsRequest, MultiSellerPolicy, StoreCardRequest
from lunixi.auth.canonical_request import build_canonical_request
from lunixi.auth.ed25519_signer import verify_signature
from lunixi.errors import ConfigurationError

from .support.recording_transport import envelope, json_response

PAN = "5400000000000004"
CVC = "123"
SIGNATURE_HEADERS = ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature")


def assert_signed(request, public_key):
    for header in SIGNATURE_HEADERS:
        assert request.header(header), header
    canonical = build_canonical_request(
        request.method,
        request.path,
        request.header("X-Date"),
        request.header("X-Nonce"),
        request.header("Digest"),
    )
    assert verify_signature(public_key, request.header("X-Signature"), canonical) is True


def assert_bearer_only(request):
    assert request.header("Authorization").startswith("Bearer ")
    for header in SIGNATURE_HEADERS:
        assert request.header(header) is None, header


def query_of(request):
    return parse_qs(urlsplit(request.url).query)


def card():
    return {
        "cardHolderName": "Test Buyer",
        "cardNumber": PAN,
        "expireMonth": "12",
        "expireYear": "2030",
        "cvcNumber": CVC,
    }


def store_card_request():
    return StoreCardRequest(card(), "cuk_123", "https://shop.example/cards/return")


# ── BIN info ─────────────────────────────────────────────────────────────────


def test_bin_info_posts_the_bin_with_the_access_token(client_factory):
    transport, client = client_factory(json_response(envelope({"bin": "540000"})))
    client.payments().bin_info("54000000")
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/bin/info"
    assert request.body == '{"binOrPan":"54000000"}'
    assert request.header("Idempotency-Key") is None
    assert_bearer_only(request)


@pytest.mark.parametrize(
    "value", ["5400", "5400 0000", "54000000000000000000", "abcdef", 540000, None]
)
def test_an_invalid_bin_is_refused_without_echoing_it(client_factory, value):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError) as caught:
        client.payments().bin_info(value)
    assert transport.requests == []
    if isinstance(value, str) and value:
        assert value not in str(caught.value)


# ── installment options ──────────────────────────────────────────────────────


def test_installment_options_sends_the_sorted_list(client_factory):
    transport, client = client_factory(json_response(envelope({"installments": []})))
    client.payments().installment_options(
        InstallmentOptionsRequest(
            "10050", "TRY", bin_or_pan="540000", installment=3, enabled_installments=[3, 1, 2]
        )
    )
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/bin/installments"
    assert json.loads(request.body) == {
        "amount": "10050",
        "currency": "TRY",
        "binOrPan": "540000",
        "installment": 3,
        "enabledInstallments": [1, 2, 3],
    }
    assert_bearer_only(request)


def test_a_raw_installment_options_body_is_checked_and_sorted(client_factory):
    transport, client = client_factory(json_response(envelope({"installments": []})))
    client.payments().installment_options(
        {"amount": "10050", "currency": "TRY", "enabledInstallments": [6, 1]}
    )
    assert json.loads(transport.last.body)["enabledInstallments"] == [1, 6]


@pytest.mark.parametrize(
    "request_value",
    [
        InstallmentOptionsRequest("10050", "TRY", enabled_installments=[2, 3]),
        InstallmentOptionsRequest("10050", "TRY", enabled_installments=[]),
        InstallmentOptionsRequest("10050", "TRY", enabled_installments=[1, 1]),
        InstallmentOptionsRequest("10050", "TRY", enabled_installments=[1, 37]),
        InstallmentOptionsRequest("10050", "TRY", installment=0),
        InstallmentOptionsRequest(10050, "TRY"),
        InstallmentOptionsRequest("10050", "try"),
        InstallmentOptionsRequest("10050", "TRY", bin_or_pan="54"),
        {"amount": "10050", "currency": "TRY", "enabledInstallments": [2, 3]},
        {"amount": "10050", "currency": "TRY", "price": "10050"},
        {"amount": 10050, "currency": "TRY"},
    ],
)
def test_broken_installment_options_are_refused_locally(client_factory, request_value):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().installment_options(request_value)
    assert transport.requests == []


def test_the_bin_is_not_in_the_request_repr():
    assert "540000" not in repr(InstallmentOptionsRequest("10050", "TRY", bin_or_pan="540000"))


def test_card_taxonomy_is_a_plain_get(client_factory):
    transport, client = client_factory(json_response(envelope({"brands": []})))
    client.payments().card_taxonomy()
    request = transport.last
    assert (request.method, request.path, request.body) == (
        "GET",
        "/api/v1/bin/card-taxonomy",
        None,
    )
    assert_bearer_only(request)


# ── stored cards ─────────────────────────────────────────────────────────────


def test_store_card_is_signed_with_the_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"storedCardToken": "sct_1"})))
    request_body = store_card_request().with_currency("TRY")
    client.payments().store_card(request_body, idempotency_key="card-1")
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/payments/cards"
    assert json.loads(request.body) == {
        "card": card(),
        "cardUserKey": "cuk_123",
        "callbackUrl": "https://shop.example/cards/return",
        "currency": "TRY",
    }
    assert request.header("Idempotency-Key") == "card-1"
    assert_signed(request, public_key)


@pytest.mark.parametrize("key", [None, "", "   ", " card-1", "k" * 201])
def test_store_card_needs_a_key(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().store_card(store_card_request(), idempotency_key=key)
    assert transport.requests == []


def test_the_card_never_shows_in_repr_or_errors(client_factory):
    request = store_card_request()
    assert PAN not in repr(request)
    assert CVC not in repr(request)
    transport, client = client_factory()
    with pytest.raises(ConfigurationError) as caught:
        client.payments().store_card(request, idempotency_key=None)
    assert PAN not in str(caught.value)
    assert transport.requests == []


@pytest.mark.parametrize(
    "args",
    [
        ({}, "cuk_123", "https://shop.example/r"),
        (card(), "", "https://shop.example/r"),
        (card(), "cuk_123", "http://shop.example/r"),
        (card(), "cuk_123", "https://user:pw@shop.example/r"),
    ],
)
def test_a_broken_store_card_request_is_refused(args):
    with pytest.raises(ConfigurationError):
        StoreCardRequest(*args)


def test_store_card_takes_the_typed_request_only(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().store_card(
            {"card": card(), "cardUserKey": "cuk_123"}, idempotency_key="card-1"
        )
    assert transport.requests == []


def test_list_and_get_stored_cards(client_factory):
    transport, client = client_factory(
        json_response(envelope({"items": []})), json_response(envelope({"storedCardToken": "a/b"}))
    )
    client.payments().list_stored_cards("cuk_123")
    listed = transport.last
    assert urlsplit(listed.url).path == "/api/v1/payments/cards"
    assert query_of(listed) == {"cardUserKey": ["cuk_123"]}
    assert_bearer_only(listed)
    client.payments().get_stored_card("a/b")
    fetched = transport.last
    assert (fetched.method, fetched.path) == ("GET", "/api/v1/payments/cards/a%2Fb")
    assert_bearer_only(fetched)


def test_deactivate_stored_card_is_a_signed_delete_with_the_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"active": False})))
    client.payments().deactivate_stored_card("sct_1", idempotency_key="deactivate-1")
    request = transport.last
    assert (request.method, request.path, request.body) == (
        "DELETE",
        "/api/v1/payments/cards/sct_1",
        None,
    )
    assert request.header("Idempotency-Key") == "deactivate-1"
    assert_signed(request, public_key)


@pytest.mark.parametrize(
    "call",
    [
        lambda payments: payments.deactivate_stored_card("sct_1", idempotency_key=None),
        lambda payments: payments.deactivate_stored_card("sct_1", idempotency_key=""),
        lambda payments: payments.deactivate_stored_card("", idempotency_key="deactivate-1"),
        lambda payments: payments.get_stored_card(" "),
        lambda payments: payments.list_stored_cards(""),
    ],
)
def test_stored_card_calls_without_their_inputs_send_nothing(client_factory, call):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        call(client.payments())
    assert transport.requests == []


# ── marketplace intent ───────────────────────────────────────────────────────


def sellers(*amounts):
    return [
        {"subDealerId": f"d_{index}", "amountMinor": amount}
        for index, amount in enumerate(amounts, 1)
    ]


def test_marketplace_intent_is_signed_with_sellers_and_policy(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"token": "t", "paymentId": "p"})))
    client.payments().create_marketplace_intent(
        CreateIntent("10050", "TRY", "order-1"),
        sellers=sellers("6000", "4050"),
        multi_seller_policy=MultiSellerPolicy.ALL_OR_NOTHING,
        idempotency_key="mp-1",
    )
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/payments/marketplace/intents"
    body = json.loads(request.body)
    assert body["amount"] == "10050"
    assert body["sellers"] == sellers("6000", "4050")
    assert body["multiSellerPolicy"] == "ALL_OR_NOTHING"
    assert request.header("Idempotency-Key") == "mp-1"
    assert_signed(request, public_key)


def test_a_raw_marketplace_body_is_sent_as_given(client_factory):
    transport, client = client_factory(json_response(envelope({"token": "t"})))
    body = {
        "amount": "1000",
        "currency": "TRY",
        "orderId": "order-1",
        "sellers": [{"subDealerId": "d_1", "amountMinor": "1000", "scenario": {"code": "std"}}],
    }
    client.payments().create_marketplace_intent(body)
    assert json.loads(transport.last.body) == body
    assert transport.last.header("Idempotency-Key") is None


@pytest.mark.parametrize(
    "seller_rows",
    [
        sellers("6000", "4000"),
        sellers("6000", "4051"),
        sellers("10050", "1"),
        [],
        [{"subDealerId": "d_1", "amountMinor": 10050}],
        [{"subDealerId": "d_1", "amountMinor": "010050"}],
        sellers("0", "10050"),
        [{"subDealerId": "d_1", "amountMinor": "10050", "scenario": "standard"}],
        [{"subDealerId": "", "amountMinor": "10050"}],
        [{"subDealerId": "d_1", "amountMinor": "10050", "price": "10050"}],
        ["d_1"],
    ],
)
def test_marketplace_seller_totals_and_shape_are_checked(client_factory, seller_rows):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().create_marketplace_intent(
            CreateIntent("10050", "TRY", "order-1"), sellers=seller_rows
        )
    assert transport.requests == []


def test_a_marketplace_total_mismatch_names_both_totals(client_factory):
    _, client = client_factory()
    with pytest.raises(ConfigurationError, match="10000.*10050"):
        client.payments().create_marketplace_intent(
            CreateIntent("10050", "TRY", "order-1"), sellers=sellers("6000", "4000")
        )


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "1000", "currency": "TRY", "orderId": "o"},
        {"amount": "1000", "price": "1000", "sellers": sellers("1000")},
        {"amount": "1000", "sellers": sellers("1000"), "preauth": "false"},
        {"amount": 1000, "sellers": sellers("1000")},
    ],
)
def test_a_broken_raw_marketplace_body_is_refused(client_factory, body):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().create_marketplace_intent(body)
    assert transport.requests == []


def test_typed_marketplace_intent_needs_sellers_once(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().create_marketplace_intent(CreateIntent("1000", "TRY", "order-1"))
    with pytest.raises(ConfigurationError):
        client.payments().create_marketplace_intent(
            {"amount": "1000", "sellers": sellers("1000")}, sellers=sellers("1000")
        )
    assert transport.requests == []


# ── analytics ────────────────────────────────────────────────────────────────


def test_analytics_routes_carry_their_filters(client_factory):
    transport, client = client_factory(
        json_response(envelope({"recovered": "0"})), json_response(envelope({"rows": []}))
    )
    client.payments().failover_recovery_analytics(range="30d")
    first = transport.last
    assert urlsplit(first.url).path == "/api/v1/payments/analytics/failover-recovery"
    assert query_of(first) == {"range": ["30d"]}
    assert_bearer_only(first)
    client.payments().provider_credential_analytics("cred 1", range="7d", to=None)
    second = transport.last
    assert urlsplit(second.url).path == "/api/v1/payments/analytics/provider-credentials/cred%201"
    assert query_of(second) == {"range": ["7d"]}


def test_analytics_need_a_credential_id(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().provider_credential_analytics("")
    assert transport.requests == []
