"""Physical POS payments: routes, Idempotency-Key, 202/200, typed errors, lists.

Contract source: nest-payment-gateway apps/api-gateway/src/physical-pos/
payments/ (physical-pos-payments-api.controller.ts, dtos/physical-pos-payments.dto.ts,
physical-pos-payments.service.ts, physical-pos-payments.mapper.ts) and
transactions/ (physical-pos-transactions-api.controller.ts, dtos, mapper).
Ids and values below are synthetic.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi.errors import (
    ApiError,
    ConfigurationError,
    PhysicalPosCardDataRejectedError,
    PhysicalPosOutcomeUnknownError,
    PhysicalPosRateLimitError,
    PhysicalPosVoidAfterSettlementError,
    RateLimitError,
    ValidationError,
)
from lunixi.physical_pos import PhysicalPosPaymentWriteResult

from .support.recording_transport import envelope, json_response, transport_failure

PAYMENT_ID = "0192f3a1-0000-7000-8000-000000000001"
CHILD_ID = "0192f3a1-0000-7000-8000-000000000002"
DEVICE_ID = "5f0c2b1e-1111-4222-8333-444455556666"
KEY = "pos-test-key-0001"
UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

SALE = {
    "operation": "SALE",
    "target": {"vendorCode": "PAVO", "serialNumber": "PAV00012345"},
    "amountMinor": "4500",
    "currency": "TRY",
    "merchantReference": "ORD-2026-000123",
    "items": [
        {
            "lineNo": 1,
            "name": "Tea",
            "quantityMilli": 2000,
            "unitCode": "C62",
            "unitPriceMinor": "1500",
            "taxGroupCode": "KDV10",
            "lineTotalMinor": "3000",
            "barcode": "8691234567012",
        },
        {
            "lineNo": 2,
            "name": "Bagel",
            "quantityMilli": 1000,
            "unitCode": "C62",
            "unitPriceMinor": "1500",
            "taxGroupCode": "KDV1",
            "lineTotalMinor": "1500",
        },
    ],
}


def payment(**overrides):
    view = {
        "paymentId": PAYMENT_ID,
        "rootPaymentId": PAYMENT_ID,
        "originalPaymentId": None,
        "origin": "API",
        "operation": "SALE",
        "paymentStatus": "NOT_STARTED",
        "statusReason": None,
        "outcomeConflict": False,
        "resolvable": False,
        "deviceId": DEVICE_ID,
        "logicalTerminalId": None,
        "terminalAcquirerId": None,
        "channel": "APP2APP",
        "vendorReference": PAYMENT_ID.replace("-", ""),
        "amountMinor": "4500",
        "approvedAmountMinor": None,
        "currency": "TRY",
        "installmentCount": None,
        "instrument": "CARD",
        "merchantReference": "ORD-2026-000123",
        "reversedMinor": "0",
        "capturedMinor": "0",
        "reversalReservedMinor": "0",
        "pendingReversalId": None,
        "reversalStatus": "NONE",
        "expiresAt": "2026-10-30T09:00:30.000Z",
        "resultDeadlineAt": "2026-10-30T09:03:30.000Z",
        "completedAt": None,
        "createdAt": "2026-10-30T09:00:00.000Z",
        "updatedAt": "2026-10-30T09:00:00.000Z",
        "rowVersion": 1,
        "historySeq": 1,
        "tender": None,
        "items": [],
        "refundItems": [],
    }
    view.update(overrides)
    return view


def write_answer(replayed=False, status=202, **overrides):
    return json_response(
        envelope({"payment": payment(**overrides), "replayed": replayed}, statusCode=status),
        status_code=status,
    )


def query_of(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


def error_answer(status, code, details=None, headers=None):
    body = {
        "status": "failure",
        "code": code,
        "message": "refused",
        "statusCode": status,
        "requestId": "req_pos",
    }
    if details is not None:
        body["details"] = details
    return json_response(body, status_code=status, headers=headers)


class TestCreatePayment:
    def test_posts_the_sale_signed_with_the_given_key(self, client_factory):
        transport, client = client_factory(write_answer())
        result = client.physical_pos().create_payment(SALE, idempotency_key=KEY)

        request = transport.last
        assert request.method == "POST"
        assert request.path == "/api/v1/physical-pos/payments"
        assert request.header("Idempotency-Key") == KEY
        for header in ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature", "Digest"):
            assert request.header(header), header
        assert json.loads(request.body) == SALE
        assert isinstance(result, PhysicalPosPaymentWriteResult)
        assert result.status_code == 202 and result.accepted is True
        assert result.replayed is False
        assert result.idempotency_key == KEY
        assert result.payment["paymentStatus"] == "NOT_STARTED"

    def test_a_key_is_required_and_never_generated(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(TypeError):
            client.physical_pos().create_payment(SALE)  # type: ignore[call-arg]
        with pytest.raises(ConfigurationError, match="new_idempotency_key"):
            client.physical_pos().create_payment(SALE, idempotency_key=None)  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError):
            client.physical_pos().create_reversal(
                PAYMENT_ID, {"operation": "VOID", "currency": "TRY"}, idempotency_key=None  # type: ignore[arg-type]
            )
        assert transport.requests == []

    def test_new_idempotency_key_is_a_fresh_uuid(self, client_factory):
        _, client = client_factory()
        first = client.physical_pos().new_idempotency_key()
        assert UUID_V4.fullmatch(first)
        assert first != type(client.physical_pos()).new_idempotency_key()

    def test_snake_case_keywords_map_to_wire_names(self, client_factory):
        transport, client = client_factory(write_answer())
        client.physical_pos().create_payment(
            operation="SALE",
            target={"device_id": DEVICE_ID},
            amount_minor="1000",
            currency="TRY",
            allow_duplicate_reference=True,
            installment_count=None,
            idempotency_key=KEY,
        )
        assert json.loads(transport.last.body) == {
            "operation": "SALE",
            "target": {"deviceId": DEVICE_ID},
            "amountMinor": "1000",
            "currency": "TRY",
            "allowDuplicateReference": True,
        }

    def test_a_replay_is_200_with_the_current_view(self, client_factory):
        _, client = client_factory(write_answer(replayed=True, status=200, paymentStatus="APPROVED"))
        result = client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        assert result.status_code == 200
        assert result.accepted is False
        assert result.replayed is True
        assert result.payment["paymentStatus"] == "APPROVED"

    def test_the_status_falls_back_to_replayed_when_the_envelope_has_none(self, client_factory):
        answer = envelope({"payment": payment(), "replayed": False})
        del answer["statusCode"]
        _, client = client_factory(json_response(answer, status_code=202))
        assert client.physical_pos().create_payment(SALE, idempotency_key=KEY).status_code == 202

    def test_transport_retries_reuse_the_same_key(self, client_factory):
        transport, client = client_factory(transport_failure(), write_answer())
        result = client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        sent = [r.header("Idempotency-Key") for r in transport.requests_to("/physical-pos/payments")]
        assert len(sent) == 2
        assert sent[0] == sent[1] == result.idempotency_key

    @pytest.mark.parametrize("key", ["", "        ", " pos-key-1", "short", "has space key", "x" * 201, "tab\tkey-0001"])
    def test_an_invalid_key_is_refused_before_sending(self, client_factory, key):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos().create_payment(SALE, idempotency_key=key)
        assert transport.requests == []

    @pytest.mark.parametrize(
        "change",
        [
            {"amountMinor": 4500},
            {"amountMinor": 45.0},
            {"amountMinor": True},
            {"currency": None},
            {"operation": None},
            {"target": None},
            {"currency": ""},
            {"items": []},
            {"environment": "LIVE"},
            {"organizationId": "org"},
        ],
    )
    def test_shape_errors_are_refused_before_sending(self, client_factory, change):
        transport, client = client_factory()
        request = dict(SALE, **change)
        with pytest.raises(ConfigurationError):
            client.physical_pos().create_payment(request, idempotency_key=KEY)
        assert transport.requests == []

    def test_an_unknown_item_field_is_refused(self, client_factory):
        transport, client = client_factory()
        request = dict(SALE, items=[dict(SALE["items"][0], vatRateBp=1000)])
        with pytest.raises(ConfigurationError, match="vatRateBp"):
            client.physical_pos().create_payment(request, idempotency_key=KEY)
        assert transport.requests == []


class TestCardData:
    @pytest.mark.parametrize(
        ("request_body", "field"),
        [
            (dict(SALE, cardNumber="x"), "cardNumber"),
            (dict(SALE, pan="x"), "pan"),
            (dict(SALE, card_cvv="x"), "card_cvv"),
            (dict(SALE, target={"deviceId": DEVICE_ID, "track2Data": "x"}), "target.track2Data"),
            (dict(SALE, items=[SALE["items"][0], dict(SALE["items"][1], CVVCode="x")]), "items[1].CVVCode"),
            (dict(SALE, expiry="12/30"), "expiry"),
            (dict(SALE, **{"4543600000001234": "x"}), "(body)"),
        ],
    )
    def test_card_data_keys_never_leave_the_process(self, client_factory, request_body, field):
        transport, client = client_factory()
        with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
            client.physical_pos().create_payment(request_body, idempotency_key=KEY)
        assert caught.value.field == field
        assert caught.value.code == "physical_pos.payment.card_data_rejected"
        assert caught.value.status_code == 0
        assert isinstance(caught.value, ValidationError)
        assert transport.requests == []

    def test_card_data_in_a_filter_name_is_refused(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
            client.physical_pos().list_payments(pan="x")
        assert caught.value.field == "pan"
        assert transport.requests == []

    def test_the_gateway_card_data_code_is_typed(self, client_factory):
        _, client = client_factory(
            error_answer(400, "physical_pos.payment.card_data_rejected", {"field": "merchantReference"})
        )
        with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
            client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        assert caught.value.status_code == 400
        assert caught.value.field == "merchantReference"
        assert caught.value.idempotency_key == KEY


class TestErrors:
    def test_rate_limit_reads_retry_after(self, client_factory):
        _, client = client_factory(
            error_answer(429, "RATE_LIMITED", {"retryAfterSeconds": 30}, {"retry-after": "12"})
        )
        with pytest.raises(PhysicalPosRateLimitError) as caught:
            client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        assert isinstance(caught.value, RateLimitError)
        assert caught.value.retry_after == 12
        assert caught.value.idempotency_key == KEY

    def test_rate_limit_falls_back_to_details(self, client_factory):
        _, client = client_factory(error_answer(429, "RATE_LIMITED", {"retryAfterSeconds": 30}))
        with pytest.raises(PhysicalPosRateLimitError) as caught:
            client.physical_pos().cancel_payment(PAYMENT_ID)
        assert caught.value.retry_after == 30

    def test_no_answer_is_an_unknown_outcome_carrying_the_key(self, client_factory):
        _, client = client_factory(transport_failure(), max_retries=0)
        with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
            client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        assert caught.value.idempotency_key == KEY
        assert caught.value.status_code == 0

    def test_a_generic_5xx_after_retries_is_an_unknown_outcome(self, client_factory):
        timeout = error_answer(504, "GATEWAY_TIMEOUT")
        transport, client = client_factory(timeout, timeout, timeout)
        with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
            client.physical_pos().create_reversal(
                PAYMENT_ID, {"operation": "VOID", "currency": "TRY"}, idempotency_key=KEY
            )
        keys = {r.header("Idempotency-Key") for r in transport.requests_to("/reversals")}
        assert keys == {KEY} == {caught.value.idempotency_key}
        assert len(transport.requests_to("/reversals")) == 3
        assert caught.value.code == "GATEWAY_TIMEOUT"
        assert caught.value.status_code == 504

    def test_a_not_started_503_after_retries_is_a_definite_refusal(self, client_factory):
        busy = error_answer(503, "physical_pos.service.busy", {"retryable": True})
        transport, client = client_factory(busy, busy, busy)
        with pytest.raises(ApiError) as caught:
            client.physical_pos().create_reversal(
                PAYMENT_ID, {"operation": "VOID", "currency": "TRY"}, idempotency_key=KEY
            )
        assert not isinstance(caught.value, PhysicalPosOutcomeUnknownError)
        assert caught.value.code == "physical_pos.service.busy"
        assert caught.value.idempotency_key == KEY
        assert len(transport.requests_to("/reversals")) == 3

    def test_a_definite_refusal_keeps_its_class_and_gets_the_key(self, client_factory):
        _, client = client_factory(
            error_answer(409, "physical_pos.payment.device_busy", {"reason": "payment_in_progress", "retryAfterSeconds": 20})
        )
        with pytest.raises(ApiError) as caught:
            client.physical_pos().create_payment(SALE, idempotency_key=KEY)
        assert type(caught.value) is ApiError
        assert caught.value.code == "physical_pos.payment.device_busy"
        assert caught.value.details == {"reason": "payment_in_progress", "retryAfterSeconds": 20}
        assert caught.value.idempotency_key == KEY

    def test_a_void_of_a_settled_payment_is_typed(self, client_factory):
        transport, client = client_factory(
            error_answer(409, "physical_pos.payment.void_after_settlement", {"allowedOperation": "REFUND"}),
            error_answer(409, "physical_pos.payment.void_after_settlement"),
        )
        pos = client.physical_pos()
        with pytest.raises(PhysicalPosVoidAfterSettlementError) as caught:
            pos.create_reversal(PAYMENT_ID, {"operation": "VOID", "currency": "TRY"}, idempotency_key=KEY)
        assert isinstance(caught.value, ApiError)
        assert not isinstance(caught.value, PhysicalPosOutcomeUnknownError)
        assert caught.value.status_code == 409
        assert caught.value.code == PhysicalPosVoidAfterSettlementError.CODE
        assert caught.value.allowed_operation == "REFUND"
        assert caught.value.idempotency_key == KEY
        assert len(transport.requests_to("/reversals")) == 1
        with pytest.raises(PhysicalPosVoidAfterSettlementError) as bare:
            pos.create_reversal(PAYMENT_ID, {"operation": "VOID", "currency": "TRY"}, idempotency_key=KEY)
        assert bare.value.allowed_operation is None

    def test_a_read_5xx_is_not_an_unknown_outcome(self, client_factory):
        failure = error_answer(500, "physical_pos.internal.integrity")
        _, client = client_factory(failure, failure, failure)
        with pytest.raises(ApiError) as caught:
            client.physical_pos().get_payment(PAYMENT_ID)
        assert not isinstance(caught.value, PhysicalPosOutcomeUnknownError)


class TestReversalAndCancel:
    def test_item_refund(self, client_factory):
        transport, client = client_factory(
            write_answer(paymentId=CHILD_ID, operation="REFUND", originalPaymentId=PAYMENT_ID, amountMinor="1500")
        )
        result = client.physical_pos().create_reversal(
            PAYMENT_ID,
            operation="REFUND",
            currency="TRY",
            items=[{"line_no": 1, "quantity_milli": 1000}],
            idempotency_key=KEY,
        )
        assert transport.last.path == f"/api/v1/physical-pos/payments/{PAYMENT_ID}/reversals"
        assert json.loads(transport.last.body) == {
            "operation": "REFUND",
            "currency": "TRY",
            "items": [{"lineNo": 1, "quantityMilli": 1000}],
        }
        assert result.status_code == 202
        assert result.payment["originalPaymentId"] == PAYMENT_ID

    def test_reversal_refuses_sale_only_fields(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos().create_reversal(
                PAYMENT_ID, {"operation": "VOID", "currency": "TRY", "installmentCount": 3}, idempotency_key=KEY
            )
        assert transport.requests == []

    def test_cancel_sends_an_empty_body_with_a_key(self, client_factory):
        transport, client = client_factory(
            write_answer(status=200, paymentStatus="EXPIRED", statusReason="MERCHANT_CANCELLED_BEFORE_DISPATCH")
        )
        result = client.physical_pos().cancel_payment(PAYMENT_ID)
        assert transport.last.path == f"/api/v1/physical-pos/payments/{PAYMENT_ID}/cancel"
        assert transport.last.body == "{}"
        assert UUID_V4.fullmatch(transport.last.header("Idempotency-Key"))
        assert result.status_code == 200
        assert result.payment["statusReason"] == "MERCHANT_CANCELLED_BEFORE_DISPATCH"

    @pytest.mark.parametrize("bad", ["", " id", None, 5, "..", "."])
    def test_a_bad_path_id_is_refused(self, client_factory, bad):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos().get_payment(bad)
        assert transport.requests == []

    def test_a_slash_in_an_id_is_encoded(self, client_factory):
        transport, client = client_factory(json_response(envelope({"payment": payment()})))
        client.physical_pos().get_payment("a/b")
        assert transport.last.path == "/api/v1/physical-pos/payments/a%2Fb"


class TestReads:
    def test_get_payment_unwraps_the_record(self, client_factory):
        transport, client = client_factory(json_response(envelope({"payment": payment()})))
        view = client.physical_pos().get_payment(PAYMENT_ID)
        assert view["paymentId"] == PAYMENT_ID
        assert transport.last.method == "GET"
        assert transport.last.header("X-Signature")

    def test_list_payments_maps_filters_and_reads_page_info(self, client_factory):
        page_info = {"hasMore": True, "nextCursor": "c1", "totalCount": None}
        transport, client = client_factory(
            json_response(envelope({"items": [payment()], "pageInfo": page_info}, pageInfo=page_info))
        )
        page = client.physical_pos().list_payments(
            limit=10, device_id=DEVICE_ID, merchant_reference="ORD-1", payment_status=None
        )
        assert transport.last.path.startswith("/api/v1/physical-pos/payments?")
        assert query_of(transport.last) == {
            "limit": "10",
            "deviceId": DEVICE_ID,
            "merchantReference": "ORD-1",
        }
        assert page.has_more is True and page.next_cursor == "c1"
        assert page.items[0]["paymentId"] == PAYMENT_ID

    @pytest.mark.parametrize("filters", [{"limit": 0}, {"limit": 101}, {"limit": "10"}, {"environment": "LIVE"}, {"organization_id": "x"}])
    def test_bad_filters_are_refused(self, client_factory, filters):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos().list_payments(**filters)
        assert transport.requests == []

    def test_iterate_follows_the_cursor(self, client_factory):
        first = {"hasMore": True, "nextCursor": "c1", "totalCount": None}
        last = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            json_response(envelope({"items": [payment()], "pageInfo": first}, pageInfo=first)),
            json_response(envelope({"items": [payment(paymentId=CHILD_ID)], "pageInfo": last}, pageInfo=last)),
        )
        ids = [row["paymentId"] for row in client.physical_pos().iterate_payments(limit=1)]
        assert ids == [PAYMENT_ID, CHILD_ID]
        assert query_of(transport.requests[-1]) == {"limit": "1", "cursor": "c1"}

    def test_transactions_routes(self, client_factory):
        tree = {
            "root": payment(),
            "children": [],
            "childrenTruncated": False,
            "itemSummary": {"lineCount": 2, "refundStatus": "NONE", "refundedMinor": "0"},
            "storeId": None,
            "registerId": None,
        }
        detail = dict(tree, requestedPaymentId=PAYMENT_ID, timeline=[], timelineTruncated=False)
        info = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            json_response(envelope({"items": [tree], "pageInfo": info}, pageInfo=info)),
            json_response(envelope({"transaction": detail})),
            json_response(envelope({"items": [payment(paymentStatus="UNKNOWN")], "pageInfo": info}, pageInfo=info)),
        )
        pos = client.physical_pos()
        page = pos.list_transactions(amount_from_minor="100", origin="DEVICE_DIRECT", store_id="s1")
        assert query_of(transport.last) == {"amountFromMinor": "100", "origin": "DEVICE_DIRECT", "storeId": "s1"}
        assert page.items[0]["itemSummary"]["lineCount"] == 2
        assert pos.get_transaction(CHILD_ID)["requestedPaymentId"] == PAYMENT_ID
        assert transport.last.path == f"/api/v1/physical-pos/transactions/{CHILD_ID}"
        pos.list_ambiguous_payments(payment_status="UNKNOWN")
        assert transport.last.path == "/api/v1/physical-pos/transactions/ambiguous?paymentStatus=UNKNOWN"

    def test_reports_and_settlements(self, client_factory):
        sales = {"environment": "LIVE", "dateFrom": "2026-10-24", "dateTo": "2026-10-30", "groupBy": "DAY", "rows": []}
        tax = {"environment": "LIVE", "dateFrom": "2026-10-24", "dateTo": "2026-10-30", "rows": [], "amountTotals": []}
        info = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            json_response(envelope(sales)),
            json_response(envelope(tax)),
            json_response(envelope({"items": [], "pageInfo": info}, pageInfo=info)),
        )
        pos = client.physical_pos()
        assert pos.get_sales_summary(group_by="STORE", date_from="2026-10-24")["groupBy"] == "DAY"
        assert query_of(transport.last) == {"groupBy": "STORE", "dateFrom": "2026-10-24"}
        assert transport.last.path.startswith("/api/v1/physical-pos/reports/sales-summary")
        assert pos.get_tax_summary()["amountTotals"] == []
        assert transport.last.path == "/api/v1/physical-pos/reports/tax-summary"
        assert pos.list_settlements(line_status="MISMATCH").items == []
        assert transport.last.path == "/api/v1/physical-pos/settlements?lineStatus=MISMATCH"

    def test_report_refuses_list_filters(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos().get_tax_summary(group_by="DAY")
        assert transport.requests == []

    def test_there_is_no_resolve_method(self, client_factory):
        _, client = client_factory()
        assert not hasattr(client.physical_pos(), "resolve_payment")

@pytest.mark.parametrize("invalid", [4500, None, True, "", "01", "1e3", "1.0", " 1", "1\n", "0", "-1", "9223372036854775808"])
def test_physical_pos_money_rejects_before_http_including_nested_and_filters(client_factory, invalid):
    transport, client = client_factory()
    pos = client.physical_pos()
    requests = [
        lambda: pos.create_payment(dict(SALE, amountMinor=invalid), idempotency_key=KEY),
        lambda: pos.create_payment(dict(SALE, items=[dict(SALE['items'][0], unitPriceMinor=invalid)]), idempotency_key=KEY),
        lambda: pos.create_reversal(PAYMENT_ID, {"operation": "REFUND", "currency": "TRY", "amountMinor": invalid}, idempotency_key=KEY),
        lambda: pos.create_reversal(PAYMENT_ID, {"operation": "REFUND", "currency": "TRY", "items": [{"lineNo": 1, "quantityMilli": 1000, "amountMinor": invalid}]}, idempotency_key=KEY),
        lambda: pos.list_transactions(amount_from_minor=invalid),
    ]
    for call in requests:
        with pytest.raises(ConfigurationError):
            call()
    assert transport.requests == []


def test_physical_pos_large_money_keeps_exact_string_and_numeric_quantity(client_factory):
    exact = "9007199254740993"
    transport, client = client_factory(write_answer(amountMinor=exact))
    request = {"operation": "SALE", "target": {"deviceId": DEVICE_ID}, "amountMinor": exact, "currency": "KWD", "items": [
        {"lineNo": 1, "name": "Exact", "quantityMilli": 1000, "unitCode": "C62", "unitPriceMinor": exact, "taxGroupCode": "KDV0", "lineTotalMinor": exact}
    ]}
    result = client.physical_pos().create_payment(request, idempotency_key=KEY)
    assert result.payment["amountMinor"] == exact
    assert json.loads(transport.last.body)["items"][0]["unitPriceMinor"] == exact
    assert json.loads(transport.last.body)["items"][0]["quantityMilli"] == 1000
