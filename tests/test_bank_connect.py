"""Bank accounts: signed reads, filter rules, transfers and FX (keys, retries) and webhook readers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from lunixi.bank_connect import (
    BankAccountTransactionReceived,
    BankConnectEvents,
    BankTransactionDirection,
    BankTransferEvents,
    BankTransferStatus,
    BankTransferWebhookData,
)
from lunixi.errors import ConfigurationError, ServiceUnavailableError
from lunixi.webhook.verifier import WebhookEvent

from .support.recording_transport import (
    envelope,
    error_envelope,
    json_response,
    transport_failure,
)
from .support.wire import assert_signed, body_of, path_of, query_of

ACCOUNT = "4d3c2b1a-0f9e-4d8c-b7a6-112233445566"
OTHER_ACCOUNT = "9a8b7c6d-5e4f-4a3b-8c2d-665544332211"
CONNECTION = "1f2e3d4c-5b6a-4978-8a9b-0c1d2e3f4a5b"
UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
KEY = "payout-2026-0001"
TRANSFER = {
    "accountId": ACCOUNT,
    "receiverIban": "TR330006100519786457841326",
    "receiverName": "Test Receiver",
    "amountMinor": "150075",
}


def page(items, **page_info):
    return json_response(envelope({"items": items}, pageInfo=page_info))


def created(data):
    return json_response(envelope(data), 201)


# ── reads ────────────────────────────────────────────────────────────────────


def test_list_transactions_sends_checked_filters_signed(client_factory, test_key_pair):
    answer = page([{"transactionId": "t-1"}], hasMore=True, nextCursor="c2")
    transport, client = client_factory(answer)
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    result = client.bank_connect().list_transactions(
        account_id=[ACCOUNT, OTHER_ACCOUNT],
        booked_from=start,
        booked_to="2026-11-15T00:00:00+03:00",
        direction=BankTransactionDirection.CREDIT,
        min_amount_minor="100",
        max_amount_minor="500000",
        canonical_type=["TRANSFER_IN", "FEE"],
        limit=50,
    )
    request = transport.last
    assert (request.method, path_of(request)) == ("GET", "/api/v1/bank-connect/transactions")
    assert query_of(request) == {
        "limit": ["50"],
        "accountId": [f"{ACCOUNT},{OTHER_ACCOUNT}"],
        "bookedFrom": ["2026-11-01T00:00:00.000Z"],
        "bookedTo": ["2026-11-15T00:00:00+03:00"],
        "direction": ["CREDIT"],
        "minAmountMinor": ["100"],
        "maxAmountMinor": ["500000"],
        "canonicalType": ["TRANSFER_IN,FEE"],
    }
    assert request.body is None and request.header("Idempotency-Key") is None
    assert_signed(request, test_key_pair[1])
    assert result.items == [{"transactionId": "t-1"}]
    assert (result.has_more, result.next_cursor) == (True, "c2")


def test_account_currency_filter_must_be_an_iso_code(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match="ISO 4217"):
        client.bank_connect().list_accounts(currency="lira")
    assert transport.requests == []


@pytest.mark.parametrize(
    "filters, message",
    [
        ({"environment": "LIVE"}, "Unknown bank-connect filter"),
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": True}, "limit"),
        ({"account_id": [f"a-{index}" for index in range(101)]}, "at most 100"),
        ({"account_id": ["a,b"]}, "without commas"),
        ({"direction": "IN"}, "direction"),
        ({"canonical_type": ["TRANSFER_IN", "SALARY"]}, "canonicalType"),
        ({"min_amount_minor": 100}, "canonical"),
        ({"min_amount_minor": "500", "max_amount_minor": "100"}, "greater than"),
        ({"booked_to": "2026-11-15T00:00:00Z"}, "needs 'bookedFrom'"),
        (
            {"booked_from": "2026-11-15T00:00:00Z", "booked_to": "2026-11-01T00:00:00Z"},
            "after",
        ),
        (
            {"booked_from": "2026-01-01T00:00:00Z", "booked_to": "2026-06-01T00:00:00Z"},
            "92 days",
        ),
        ({"booked_from": datetime(2026, 11, 1)}, "timezone-aware"),
    ],
)
def test_transaction_filters_are_refused_before_sending(client_factory, filters, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.bank_connect().list_transactions(**filters)
    assert transport.requests == []


def test_booked_window_of_exactly_92_days_is_accepted(client_factory):
    transport, client = client_factory(page([]))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    client.bank_connect().list_transactions(booked_from=start, booked_to=start + timedelta(days=92))
    assert path_of(transport.last) == "/api/v1/bank-connect/transactions"


def test_connection_status_takes_a_list_account_status_one_value(client_factory):
    transport, client = client_factory(page([]), page([]))
    client.bank_connect().list_connections(status=["ACTIVE", "DEGRADED"])
    assert query_of(transport.last) == {"status": ["ACTIVE,DEGRADED"]}
    client.bank_connect().list_accounts(status="INACTIVE", currency="try")
    assert query_of(transport.last) == {"currency": ["TRY"], "status": ["INACTIVE"]}
    with pytest.raises(ConfigurationError, match="status"):
        client.bank_connect().list_accounts(status=["ACTIVE"])


def test_request_sync_posts_without_body_or_key(client_factory, test_key_pair):
    transport, client = client_factory(
        json_response(envelope({"accountId": ACCOUNT, "syncStatus": "QUEUED"}), 202)
    )
    result = client.bank_connect().request_sync(ACCOUNT)
    request = transport.last
    assert (request.method, path_of(request)) == (
        "POST",
        f"/api/v1/bank-connect/accounts/{ACCOUNT}/sync",
    )
    assert request.body is None and request.header("Idempotency-Key") is None
    assert result["syncStatus"] == "QUEUED"
    assert_signed(request, test_key_pair[1])


def test_iterate_accounts_stops_without_a_cursor(client_factory):
    transport, client = client_factory(
        page([{"accountId": "a-1"}], hasMore=True, nextCursor="c2"),
        page([{"accountId": "a-2"}], hasMore=False, nextCursor=None),
    )
    assert [row["accountId"] for row in client.bank_connect().iterate_accounts(limit=1)] == [
        "a-1",
        "a-2",
    ]
    assert query_of(transport.last) == {"limit": ["1"], "cursor": ["c2"]}


# ── transfers ────────────────────────────────────────────────────────────────


def test_transfer_create_generates_a_uuid_key(client_factory, test_key_pair):
    transport, client = client_factory(created({"transfer": {"id": "tr-1"}, "replayed": False}))
    result = client.bank_connect().transfers.create(
        TRANSFER, currency="try", payment_purpose="OTHER", description="Invoice 42"
    )
    request = transport.last
    assert (request.method, path_of(request)) == ("POST", "/api/v1/bank-connect/transfers")
    assert body_of(request) == {
        **TRANSFER,
        "currency": "TRY",
        "paymentPurpose": "OTHER",
        "description": "Invoice 42",
    }
    assert UUID_V4.fullmatch(request.header("Idempotency-Key"))
    assert result["transfer"]["id"] == "tr-1"
    assert_signed(request, test_key_pair[1])


def test_transfer_create_keeps_the_callers_key(client_factory):
    transport, client = client_factory(created({"transfer": {"id": "tr-1"}, "replayed": True}))
    client.bank_connect().transfers.create(TRANSFER, idempotency_key=KEY)
    assert transport.last.header("Idempotency-Key") == KEY


@pytest.mark.parametrize("key", ["short", "has space key", "k" * 201, "ключ-ключ-ключ"])
def test_a_malformed_transfer_key_is_refused(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match="idempotency_key"):
        client.bank_connect().transfers.create(TRANSFER, idempotency_key=key)
    assert transport.requests == []


def test_a_5xx_or_network_error_is_retried_with_the_same_key_and_body(client_factory):
    transport, client = client_factory(
        json_response(error_envelope("bank_connect.provider.unavailable", "x", 503), 503),
        transport_failure(),
        created({"transfer": {"id": "tr-1"}, "replayed": False}),
    )
    client.bank_connect().transfers.create(TRANSFER)
    attempts = transport.requests_to("/bank-connect/transfers")
    assert len(attempts) == 3
    assert len({attempt.header("Idempotency-Key") for attempt in attempts}) == 1
    assert len({attempt.body for attempt in attempts}) == 1


def test_a_transfer_that_keeps_failing_raises_after_the_retries(client_factory):
    failure = json_response(error_envelope("bank_connect.provider.unavailable", "x", 503), 503)
    transport, client = client_factory(failure, failure, failure)
    with pytest.raises(ServiceUnavailableError):
        client.bank_connect().transfers.create(TRANSFER, idempotency_key=KEY)
    assert len(transport.requests_to("/bank-connect/transfers")) == 3


@pytest.mark.parametrize(
    "change, message",
    [
        ({"amountMinor": 150075}, "canonical"),
        ({"amountMinor": "0"}, "canonical"),
        ({"amountMinor": "1500.75"}, "canonical"),
        ({"receiverName": "X"}, "receiverName"),
        ({"receiverIban": "TR" + "0" * 41}, "receiverIban"),
        ({"paymentPurpose": "not-a-code"}, "paymentPurpose"),
        ({"description": "d" * 141}, "description"),
        ({"merchantId": "m-1"}, "does not accept merchantId"),
        ({"accountId": None}, "requires accountId"),
    ],
)
def test_transfer_body_is_refused_before_sending(client_factory, change, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.bank_connect().transfers.create({**TRANSFER, **change})
    assert transport.requests == []


def test_transfer_list_and_purposes(client_factory):
    transport, client = client_factory(
        page([{"id": "tr-1"}]), json_response(envelope({"items": [{"code": "OTHER"}]}))
    )
    client.bank_connect().transfers.list(
        status=[BankTransferStatus.SUBMITTED, BankTransferStatus.COMPLETED],
        created_from=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert query_of(transport.last) == {
        "status": ["SUBMITTED,COMPLETED"],
        "createdFrom": ["2026-11-01T00:00:00.000Z"],
    }
    assert client.bank_connect().transfers.list_purposes(CONNECTION) == {
        "items": [{"code": "OTHER"}]
    }
    assert path_of(transport.last) == "/api/v1/bank-connect/transfer-purposes"
    assert query_of(transport.last) == {"connectionId": [CONNECTION]}
    with pytest.raises(ConfigurationError, match="status"):
        client.bank_connect().transfers.list(status="DONE")


# ── currency exchange ────────────────────────────────────────────────────────


def test_fx_quote_takes_exactly_one_amount_and_two_accounts(client_factory):
    transport, client = client_factory(created({"id": "q-1"}))
    fx = client.bank_connect().fx
    fx.create_quote(
        source_account_id=ACCOUNT, target_account_id=OTHER_ACCOUNT, source_amount_minor="10000"
    )
    assert path_of(transport.last) == "/api/v1/bank-connect/fx/quotes"
    assert body_of(transport.last) == {
        "sourceAccountId": ACCOUNT,
        "targetAccountId": OTHER_ACCOUNT,
        "sourceAmountMinor": "10000",
    }
    assert transport.last.header("Idempotency-Key") is None
    with pytest.raises(ConfigurationError, match="exactly one"):
        fx.create_quote(
            source_account_id=ACCOUNT,
            target_account_id=OTHER_ACCOUNT,
            source_amount_minor="1",
            target_amount_minor="1",
        )
    with pytest.raises(ConfigurationError, match="exactly one"):
        fx.create_quote(source_account_id=ACCOUNT, target_account_id=OTHER_ACCOUNT)
    with pytest.raises(ConfigurationError, match="two different accounts"):
        fx.create_quote(
            source_account_id=ACCOUNT, target_account_id=ACCOUNT, target_amount_minor="1"
        )


def test_fx_order_generates_or_checks_the_key(client_factory):
    transport, client = client_factory(
        created({"order": {"id": "o-1"}}), created({"order": {"id": "o-1"}})
    )
    client.bank_connect().fx.create_order(quote_id="q-1")
    assert path_of(transport.last) == "/api/v1/bank-connect/fx/orders"
    assert UUID_V4.fullmatch(transport.last.header("Idempotency-Key"))
    client.bank_connect().fx.create_order({"quoteId": "q-1"}, idempotency_key=KEY)
    assert transport.last.header("Idempotency-Key") == KEY
    with pytest.raises(ConfigurationError, match="description"):
        client.bank_connect().fx.create_order(quote_id="q-1", description="d" * 141)


def test_fx_orders_status_set(client_factory):
    transport, client = client_factory(page([]))
    client.bank_connect().fx.list_orders(status="FAILED")
    assert query_of(transport.last) == {"status": ["FAILED"]}
    with pytest.raises(ConfigurationError, match="status"):
        client.bank_connect().fx.list_orders(status="PROCESSING")


# ── webhooks ─────────────────────────────────────────────────────────────────


def event(event_type, data):
    return WebhookEvent(id="evt_1", type=event_type, timestamp=None, data=data, raw={"data": data})


def test_transaction_received_reader():
    data = {
        "transactionId": "t-1",
        "accountId": ACCOUNT,
        "connectionId": CONNECTION,
        "bankEftCode": "0062",
        "bankName": "Test Bank",
        "direction": "CREDIT",
        "amountMinor": "150075",
        "currency": "TRY",
        "bookedAt": "2026-11-15T09:00:00Z",
        "valueAt": None,
        "receivedAt": "2026-11-15T09:01:00Z",
        "canonicalType": "TRANSFER_IN",
        "description": "Invoice 42",
        "counterpartyNameMasked": "T*** R***",
        "counterpartyIbanMasked": None,
        "receiptNo": None,
    }
    received = BankAccountTransactionReceived.from_event(
        event(BankConnectEvents.TRANSACTION_RECEIVED, data)
    )
    assert received.transaction_id == "t-1"
    assert received.amount_minor == "150075"
    assert received.value_at is None and received.receipt_no is None
    assert received.counterparty_name_masked == "T*** R***"


def test_transfer_event_reader_checks_the_type():
    data = {"transferId": "tr-1", "status": "FAILED", "failureCode": "bank_connect.transfer.x"}
    transfer = BankTransferWebhookData.from_event(event(BankTransferEvents.FAILED, data))
    assert (transfer.transfer_id, transfer.status) == ("tr-1", "FAILED")
    assert transfer.failure_code == "bank_connect.transfer.x"
    assert transfer.completed_at is None
    with pytest.raises(ConfigurationError, match="does not read"):
        BankTransferWebhookData.from_event(event("payment.bank_transfer.underpaid", data))
    with pytest.raises(ConfigurationError, match="WebhookEvent"):
        BankTransferWebhookData.from_event(data)
