"""Wallet: routes, signed bodies, Idempotency-Key rules and local refusals against WALLET_ROUTES."""

from __future__ import annotations

import pytest

from lunixi import BinaryResponse
from lunixi.errors import ConfigurationError
from lunixi.http.transport import HttpResponse
from lunixi.wallet import (
    WALLET_IDEMPOTENCY_KEY_MAX,
    WALLET_ROUTES,
    WalletAccountType,
    WalletBulkTargetType,
)

from .support.recording_transport import envelope, json_response
from .support.wire import assert_signed, body_of, path_of, query_of

PROGRAM = "8a5c2f3e-1b4d-4c6e-9f70-112233445566"
END_USER = "0b1c2d3e-4f50-4617-8899-aabbccddeeff"
ACCOUNT = "5e6f7081-92a3-44b5-8c6d-7e8f90a1b2c3"
OPERATION = "c0ffee00-1234-4567-89ab-cdef01234567"
KEY = "wallet-op-0001"


def ok(data=None, status=200):
    return json_response(envelope(data if data is not None else {}), status)


def test_create_end_user_is_signed_and_keyed(client_factory, test_key_pair):
    transport, client = client_factory(ok({"endUserId": END_USER}, 201))
    result = client.wallet().end_users.create(
        program_id=PROGRAM,
        account_type=WalletAccountType.PERSONAL,
        phone="+905550000000",
        display_name="Test User",
        idempotency_key=KEY,
    )
    request = transport.last
    assert result == {"endUserId": END_USER}
    assert (request.method, path_of(request)) == ("POST", "/api/v1/wallet/end-users")
    assert body_of(request) == {
        "programId": PROGRAM,
        "accountType": "PERSONAL",
        "phone": "+905550000000",
        "displayName": "Test User",
    }
    assert request.header("Idempotency-Key") == KEY
    assert_signed(request, test_key_pair[1])


def test_reads_are_signed_too(client_factory, test_key_pair):
    transport, client = client_factory(ok({"ok": True}))
    client.wallet().ping()
    assert (transport.last.method, path_of(transport.last)) == ("GET", "/api/v1/wallet/ping")
    assert_signed(transport.last, test_key_pair[1])


def test_a_keyed_route_without_a_key_is_refused_before_sending(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match="Idempotency-Key is required"):
        client.wallet().end_users.create(
            {"programId": PROGRAM, "accountType": "PERSONAL", "phone": "+905550000000"}
        )
    with pytest.raises(ConfigurationError, match="Idempotency-Key"):
        client.wallet().wallets.create_account(
            "w-1", "TRY", idempotency_key="x" * (WALLET_IDEMPOTENCY_KEY_MAX + 1)
        )
    assert transport.requests == []


@pytest.mark.parametrize(
    "body, message",
    [
        ({"programId": PROGRAM, "accountType": "PERSONAL"}, "requires phone"),
        (
            {"programId": PROGRAM, "accountType": "PERSONAL", "phone": "1", "merchantId": "m"},
            "does not accept merchantId",
        ),
    ],
)
def test_unknown_and_missing_fields_are_refused(client_factory, body, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.wallet().end_users.create(body, idempotency_key=KEY)
    assert transport.requests == []


@pytest.mark.parametrize("amount", [12550, "125.50", "-1", "", "1" * 19, 1.5])
def test_an_amount_must_be_a_digit_string(client_factory, amount):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.wallet().fees.quote(
            program_id=PROGRAM, operation_type="W2W", currency="TRY", amount=amount
        )
    assert transport.requests == []


def test_complete_puts_the_operation_id_in_the_body(client_factory):
    transport, client = client_factory(ok({"status": "COMPLETED"}))
    client.wallet().transfers.complete_w2w(
        OPERATION,
        {"endUserId": END_USER, "integrityHash": "h", "nonce": "n", "otpCode": "123456"},
        idempotency_key=KEY,
    )
    request = transport.last
    assert path_of(request) == f"/api/v1/wallet/transfers/w2w/{OPERATION}/complete"
    assert body_of(request) == {
        "endUserId": END_USER,
        "integrityHash": "h",
        "nonce": "n",
        "otpCode": "123456",
        "operationId": OPERATION,
    }
    with pytest.raises(ConfigurationError, match="must match"):
        client.wallet().withdrawals.complete(
            OPERATION,
            end_user_id=END_USER,
            operationId="other",
            integrity_hash="h",
            nonce="n",
            idempotency_key=KEY,
        )


def test_initiate_iban_transfer_body(client_factory):
    transport, client = client_factory(ok({"operationId": OPERATION}, 201))
    client.wallet().transfers.initiate_w2_iban(
        end_user_id=END_USER,
        source_wallet_account_id=ACCOUNT,
        beneficiary_name="Test Receiver",
        iban="TR000000000000000000000000",
        amount="150000",
        currency="TRY",
        idempotency_key=KEY,
    )
    assert path_of(transport.last) == "/api/v1/wallet/transfers/w2iban"
    assert body_of(transport.last)["amount"] == "150000"
    assert transport.last.header("Idempotency-Key") == KEY


def test_a_route_without_a_key_sends_none(client_factory):
    transport, client = client_factory(ok({"feeTotal": "100"}))
    client.wallet().fees.quote(program_id=PROGRAM, operation_type="W2W", currency="TRY", amount="1")
    assert transport.last.header("Idempotency-Key") is None


def test_operations_list_reads_the_wallet_page_shape(client_factory):
    transport, client = client_factory(
        ok({"operations": [{"operationId": OPERATION}], "nextCursor": "c2"})
    )
    page = client.wallet().operations.list(end_user_id=END_USER, limit=20)
    assert page.items == [{"operationId": OPERATION}]
    assert page.next_cursor == "c2"
    assert page.has_more is True
    assert query_of(transport.last) == {"endUserId": [END_USER], "limit": ["20"]}
    assert path_of(transport.last) == "/api/v1/wallet/operations"


def test_an_unknown_filter_is_refused(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match="filter"):
        client.wallet().end_users.list(environment="LIVE")
    assert transport.requests == []


def test_iterate_follows_the_cursor(client_factory):
    transport, client = client_factory(
        ok({"items": [{"id": 1}], "nextCursor": "c2"}),
        ok({"items": [{"id": 2}], "nextCursor": None}),
    )
    assert [row["id"] for row in client.wallet().qr.iterate(program_id=PROGRAM)] == [1, 2]
    assert query_of(transport.requests[-1])["cursor"] == ["c2"]


def test_bulk_payout_items_are_checked_row_by_row(client_factory):
    transport, client = client_factory(ok({"batchId": "b-1"}, 201))
    item = {"targetType": WalletBulkTargetType.WALLET, "targetRef": "W-1", "amount": "500"}
    client.wallet().bulk_payouts.create(
        program_id=PROGRAM,
        source_wallet_account_id=ACCOUNT,
        currency="TRY",
        items=[item],
        idempotency_key=KEY,
    )
    assert body_of(transport.last)["items"] == [item]
    with pytest.raises(ConfigurationError, match=r"items\[0\] does not accept iban"):
        client.wallet().bulk_payouts.create(
            program_id=PROGRAM,
            source_wallet_account_id=ACCOUNT,
            currency="TRY",
            items=[{**item, "iban": "TR00"}],
            idempotency_key=KEY,
        )
    with pytest.raises(ConfigurationError, match="digit string"):
        client.wallet().bulk_payouts.create(
            program_id=PROGRAM,
            source_wallet_account_id=ACCOUNT,
            currency="TRY",
            items=[{**item, "amount": 500}],
            idempotency_key=KEY,
        )


def test_bulk_payout_approve_defaults_to_true(client_factory):
    transport, client = client_factory(ok({"status": "APPROVED"}))
    client.wallet().bulk_payouts.approve("b-1")
    assert body_of(transport.last) == {"approve": True}
    assert transport.last.header("Idempotency-Key") is None


def test_qr_image_is_bytes(client_factory, test_key_pair):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    transport, client = client_factory(HttpResponse(200, {"content-type": "image/svg+xml"}, svg))
    image = client.wallet().qr.image("qr-1", format="svg", scale=4)
    assert isinstance(image, BinaryResponse)
    assert image.content == svg and image.content_type == "image/svg+xml"
    assert path_of(transport.last) == "/api/v1/wallet/qr/qr-1/image"
    assert query_of(transport.last) == {"format": ["svg"], "scale": ["4"]}
    assert "image/svg+xml" in transport.last.header("Accept")
    assert_signed(transport.last, test_key_pair[1])
    with pytest.raises(ConfigurationError, match="format"):
        client.wallet().qr.image("qr-1", format="gif")
    with pytest.raises(ConfigurationError, match="scale"):
        client.wallet().qr.image("qr-1", scale=21)


def test_path_ids_are_required_and_encoded(client_factory):
    transport, client = client_factory(ok({"endUserId": "a/b"}))
    client.wallet().end_users.get("a/b")
    assert transport.last.url.endswith("/api/v1/wallet/end-users/a%2Fb")
    with pytest.raises(ConfigurationError, match="endUserId is required"):
        client.wallet().end_users.get(" ")


def test_every_route_is_reached_by_a_method():
    import inspect

    from lunixi.wallet import client as wallet_client

    source = inspect.getsource(wallet_client)
    for name in WALLET_ROUTES:
        assert f'"{name}"' in source, name
