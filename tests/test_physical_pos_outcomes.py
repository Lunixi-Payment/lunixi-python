"""Physical POS payment writes: an uncertain outcome is never lost (review Y-1, Y-2, O-1, O-2, D-1, D-3, D-4, O-4).

Every payment write (start, reversal, cancel) runs one attempt loop with the
same Idempotency-Key and body. Once any attempt was uncertain — no answer, an
unreadable or payment-less 2xx, a 5xx without a "not started" code — the call
ends with PhysicalPosOutcomeUnknownError carrying the key, whatever the last
answer was. Ids and values below are synthetic.
"""

from __future__ import annotations

import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi.errors import (
    ApiError,
    ConfigurationError,
    PhysicalPosCardDataRejectedError,
    PhysicalPosOutcomeUnknownError,
    PhysicalPosRateLimitError,
    RateLimitError,
    ServiceUnavailableError,
)
from lunixi.http.transport import HttpResponse

from .support.recording_transport import envelope, json_response, transport_failure

PAYMENT_ID = "0192f3a1-0000-7000-8000-000000000001"
DEVICE_ID = "5f0c2b1e-1111-4222-8333-444455556666"
KEY = "pos-outcome-key-0001"
SALE = {
    "operation": "SALE",
    "target": {"deviceId": DEVICE_ID},
    "amountMinor": "4500",
    "currency": "TRY",
    "merchantReference": "ORD-2026-000123",
}
VOID = {"operation": "VOID", "currency": "TRY"}


def payment(**overrides):
    view = {
        "paymentId": PAYMENT_ID,
        "rootPaymentId": PAYMENT_ID,
        "operation": "SALE",
        "paymentStatus": "NOT_STARTED",
    }
    view.update(overrides)
    return view


def accepted(replayed=False):
    status = 200 if replayed else 202
    return json_response(
        envelope({"payment": payment(), "replayed": replayed}, statusCode=status),
        status_code=status,
    )


def failure(status, code, details=None, headers=None):
    body = {"status": "failure", "code": code, "message": "refused", "statusCode": status}
    if details is not None:
        body["details"] = details
    return json_response(body, status_code=status, headers=headers)


def raw(status, body: bytes):
    return HttpResponse(status_code=status, headers={"content-type": "text/html"}, body=body)


def sent_keys(transport, fragment="/physical-pos/payments"):
    return [request.header("Idempotency-Key") for request in transport.requests_to(fragment)]


def query_of(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


# ── Y-2: a 2xx is a success only with a usable payment ─────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        raw(202, b"<html>proxy page</html>"),
        raw(202, b""),
        json_response(envelope({"replayed": False}, statusCode=202), status_code=202),
        json_response(
            envelope({"payment": None, "replayed": False}, statusCode=202), status_code=202
        ),
        json_response(
            envelope({"payment": {"paymentStatus": "NOT_STARTED"}}, statusCode=202), status_code=202
        ),
        json_response(envelope({"payment": {"paymentId": ""}}, statusCode=202), status_code=202),
        json_response(envelope([1, 2]), status_code=202),
    ],
)
def test_an_unusable_2xx_is_an_unknown_outcome_with_the_key(client_factory, answer):
    _, client = client_factory(answer, max_retries=0)
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert caught.value.idempotency_key == KEY


def test_a_deeply_nested_2xx_body_is_an_unknown_outcome(client_factory):
    _, client = client_factory(raw(202, b"[" * 100000 + b"]" * 100000), max_retries=0)
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert caught.value.idempotency_key == KEY


@pytest.mark.parametrize("with_payment", [False, True])
def test_decoded_nesting_failure_preserves_unknown_outcome_and_operation_key(
    client_factory, with_payment
):
    # Exercise validation independently of each interpreter's JSON decoder limit.
    nested = []
    for _ in range(1500):
        nested = [nested]
    decoded = {"data": {"payment": payment(), "children": nested} if with_payment else nested}

    class DeepDecodedResponse(HttpResponse):
        def json(self):
            return decoded

    response = DeepDecodedResponse(202, {"content-type": "application/json"}, b"{}")
    transport, client = client_factory(response, max_retries=0)
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert caught.value.idempotency_key == KEY
    assert sent_keys(transport) == [KEY]


def test_a_dropped_connection_while_reading_is_an_unknown_outcome(client_factory):
    _, client = client_factory(transport_failure("body read timed out"), max_retries=0)
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().cancel_payment(PAYMENT_ID)
    assert caught.value.status_code == 0
    assert caught.value.idempotency_key is not None
    assert isinstance(caught.value.__cause__, ApiError)


def test_an_unusable_2xx_is_retried_with_the_same_key_and_a_good_answer_wins(client_factory):
    transport, client = client_factory(raw(202, b"not json"), accepted(replayed=True))
    result = client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert sent_keys(transport) == [KEY, KEY]
    bodies = [r.body for r in transport.requests_to("/physical-pos/payments")]
    assert bodies[0] == bodies[1]
    assert result.replayed is True and result.status_code == 200


# ── O-1: the attempt history is never lost ──────────────────────────────────


def test_an_uncertain_attempt_then_429_is_an_unknown_outcome(client_factory):
    transport, client = client_factory(
        failure(504, "GATEWAY_TIMEOUT"),
        failure(429, "RATE_LIMITED", {"retryAfterSeconds": 30}, {"retry-after": "12"}),
    )
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert not isinstance(caught.value, PhysicalPosRateLimitError)
    assert caught.value.idempotency_key == KEY
    assert caught.value.retry_after == 12
    assert caught.value.status_code == 429
    assert caught.value.code == "RATE_LIMITED"
    assert isinstance(caught.value.__cause__, RateLimitError)
    assert sent_keys(transport) == [KEY, KEY]


def test_no_answer_then_409_is_an_unknown_outcome(client_factory):
    _, client = client_factory(
        transport_failure(), failure(409, "physical_pos.idempotency_mismatch")
    )
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        client.physical_pos().create_reversal(PAYMENT_ID, VOID, idempotency_key=KEY)
    assert caught.value.idempotency_key == KEY
    assert caught.value.code == "physical_pos.idempotency_mismatch"


def test_a_not_started_503_then_4xx_is_the_plain_refusal(client_factory):
    _, client = client_factory(
        failure(503, "physical_pos.presence.unavailable", {"retryable": True}),
        failure(409, "physical_pos.payment.device_offline", {"retryable": True}),
    )
    with pytest.raises(ApiError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert not isinstance(caught.value, PhysicalPosOutcomeUnknownError)
    assert caught.value.code == "physical_pos.payment.device_offline"
    assert caught.value.idempotency_key == KEY


def test_a_not_started_503_then_success_is_a_success(client_factory):
    transport, client = client_factory(failure(503, "physical_pos.signing.unavailable"), accepted())
    result = client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert result.status_code == 202 and result.accepted
    assert sent_keys(transport) == [KEY, KEY]


def test_a_not_started_503_alone_keeps_its_class(client_factory):
    _, client = client_factory(failure(503, "physical_pos.service.clock_skew"), max_retries=0)
    with pytest.raises(ServiceUnavailableError) as caught:
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert not isinstance(caught.value, PhysicalPosOutcomeUnknownError)
    assert caught.value.idempotency_key == KEY


def test_a_4xx_stops_the_loop_at_once(client_factory):
    transport, client = client_factory(
        failure(400, "physical_pos.payment.amount_invalid", {"field": "amountMinor"})
    )
    with pytest.raises(ApiError):
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert len(sent_keys(transport)) == 1


def test_the_transport_never_retries_on_its_own_inside_the_loop(client_factory):
    transport, client = client_factory(
        transport_failure(), transport_failure(), transport_failure()
    )
    with pytest.raises(PhysicalPosOutcomeUnknownError):
        client.physical_pos().create_payment(SALE, idempotency_key=KEY)
    assert len(sent_keys(transport)) == 3  # 1 + max_retries (2), not 3 × 3


# ── Y-1 / O-2: the key ──────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["", "   ", "        ", " pos-key-01", "pos-key-01 "])
def test_an_empty_or_padded_key_is_refused_never_replaced(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.physical_pos().create_payment(SALE, idempotency_key=key)
    with pytest.raises(ConfigurationError):
        client.physical_pos().cancel_payment(PAYMENT_ID, idempotency_key=key)
    with pytest.raises(ConfigurationError):
        client.physical_pos_management().create_store(code="IST-01", name="x", idempotency_key=key)
    assert transport.requests == []


def test_the_key_is_sent_exactly_as_given(client_factory):
    transport, client = client_factory(accepted())
    client.physical_pos().create_payment(SALE, idempotency_key="Pos-Key-!~01")
    assert sent_keys(transport) == ["Pos-Key-!~01"]


def test_a_cancel_without_a_key_gets_one_reused_by_its_attempts(client_factory):
    transport, client = client_factory(transport_failure(), accepted())
    result = client.physical_pos().cancel_payment(PAYMENT_ID)
    keys = sent_keys(transport, "/cancel")
    assert len(keys) == 2 and keys[0] == keys[1] == result.idempotency_key


# ── O-4: card numbers in values ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"merchantReference": "4111 1111 1111 1111"}, "merchantReference"),
        (
            {
                "items": [
                    {
                        "lineNo": 1,
                        "name": "card 4111-1111-1111-1111",
                        "quantityMilli": 1000,
                        "unitCode": "C62",
                        "unitPriceMinor": "4500",
                        "taxGroupCode": "KDV20",
                        "lineTotalMinor": "4500",
                    }
                ]
            },
            "items[0].name",
        ),
        (
            {
                "items": [
                    {
                        "lineNo": 1,
                        "name": "Tea",
                        "quantityMilli": 1000,
                        "unitCode": "C62",
                        "unitPriceMinor": "4500",
                        "taxGroupCode": "4111111111111111",
                        "lineTotalMinor": "4500",
                    }
                ]
            },
            "items[0].taxGroupCode",
        ),
    ],
)
def test_a_card_number_in_a_value_is_refused_without_echo(client_factory, change, field):
    transport, client = client_factory()
    with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
        client.physical_pos().create_payment(dict(SALE, **change), idempotency_key=KEY)
    assert caught.value.field == field
    assert caught.value.status_code == 0
    assert "4111" not in str(caught.value)
    assert transport.requests == []


def test_a_barcode_in_an_item_name_is_not_a_card_number(client_factory):
    transport, client = client_factory(accepted())
    item = {
        "lineNo": 1,
        "name": "Simit 8691234567012",
        "quantityMilli": 1000,
        "unitCode": "C62",
        "unitPriceMinor": "4500",
        "taxGroupCode": "KDV1",
        "lineTotalMinor": "4500",
    }
    client.physical_pos().create_payment(dict(SALE, items=[item]), idempotency_key=KEY)
    assert len(transport.requests_to("/physical-pos/payments")) == 1


@pytest.mark.parametrize("call", ["list_payments", "list_transactions"])
def test_a_card_number_in_a_merchant_reference_filter_never_reaches_the_url(client_factory, call):
    transport, client = client_factory()
    with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
        getattr(client.physical_pos(), call)(merchant_reference="4111111111111111")
    assert caught.value.field == "merchantReference"
    assert "4111" not in str(caught.value)
    assert transport.requests == []


def test_a_card_number_in_a_search_filter_is_refused(client_factory):
    transport, client = client_factory()
    with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
        client.physical_pos_management().list_devices(q="5500 0000 0000 0004")
    assert caught.value.field == "q"
    assert transport.requests == []


def test_a_reversal_merchant_reference_is_scanned(client_factory):
    transport, client = client_factory()
    with pytest.raises(PhysicalPosCardDataRejectedError):
        client.physical_pos().create_reversal(
            PAYMENT_ID, dict(VOID, merchantReference="378282246310005"), idempotency_key=KEY
        )
    assert transport.requests == []


# ── D-3 / D-4: dates, empty values ──────────────────────────────────────────


def test_report_dates_are_the_given_calendar_day(client_factory):
    report = {
        "environment": "LIVE",
        "dateFrom": "2026-10-24",
        "dateTo": "2026-10-30",
        "rows": [],
        "amountTotals": [],
    }
    transport, client = client_factory(json_response(envelope(report)))
    late = dt.datetime(2026, 10, 30, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    client.physical_pos().get_tax_summary(date_from=dt.date(2026, 10, 24), date_to=late)
    assert query_of(transport.last) == {"dateFrom": "2026-10-24", "dateTo": "2026-10-30"}


def test_created_filters_take_an_aware_datetime_as_utc(client_factory):
    info = {"hasMore": False, "nextCursor": None, "totalCount": None}
    transport, client = client_factory(
        json_response(envelope({"items": [], "pageInfo": info}, pageInfo=info))
    )
    istanbul = dt.timezone(dt.timedelta(hours=3))
    client.physical_pos().list_payments(
        created_from=dt.datetime(2026, 10, 1, 3, 0, 0, 250000, tzinfo=istanbul)
    )
    assert query_of(transport.last) == {"createdFrom": "2026-10-01T00:00:00.250Z"}
    with pytest.raises(ConfigurationError):
        client.physical_pos().list_payments(created_from=dt.datetime(2026, 10, 1))
    with pytest.raises(ConfigurationError):
        client.physical_pos().list_payments(created_from=dt.date(2026, 10, 1))


def test_empty_and_null_values_are_not_sent(client_factory):
    transport, client = client_factory(accepted())
    client.physical_pos().create_payment(
        dict(
            SALE,
            merchantReference="",
            instrument=None,
            allowDuplicateReference=None,
            terminalAcquirerId="",
        ),
        idempotency_key=KEY,
    )
    body = json.loads(transport.last.body)
    assert "merchantReference" not in body
    assert "instrument" not in body
    assert "allowDuplicateReference" not in body
    assert "terminalAcquirerId" not in body


def test_an_empty_required_value_is_refused(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.physical_pos().create_payment(dict(SALE, operation=""), idempotency_key=KEY)
    assert transport.requests == []


def test_malformed_money_then_local_error_preserves_unknown_history():
    from lunixi.physical_pos import _support

    local = ConfigurationError("The signing configuration became unavailable.")

    class Api:
        max_retries = 1
        calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"data": {"payment": {"paymentId": PAYMENT_ID, "amountMinor": 4500}}}
            raise local

    api = Api()
    with pytest.raises(PhysicalPosOutcomeUnknownError) as caught:
        _support.payment_write(api, "/api/v1/physical-pos/payments", SALE, KEY)
    assert caught.value.idempotency_key == KEY
    assert caught.value.__cause__ is local
    assert api.calls == 2


def test_invalid_money_read_helper_raises_configuration_error():
    from lunixi.physical_pos import _support

    with pytest.raises(ConfigurationError):
        _support.member(
            {"data": {"payment": {"paymentId": PAYMENT_ID, "amountMinor": 4500}}}, "payment"
        )
