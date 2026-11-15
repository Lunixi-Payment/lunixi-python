"""Insurance: signed calls, Idempotency-Key rules, basket source rule, binary documents, helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lunixi import BinaryResponse
from lunixi.errors import ConfigurationError
from lunixi.http.transport import HttpResponse
from lunixi.insurance import (
    InsuranceClient,
    InsuranceEvents,
    InsuranceLeadWebhookData,
    InsuranceReconciliationExport,
    InsuranceReferenceKind,
    InsuranceWebhookData,
)
from lunixi.webhook.verifier import WebhookEvent

from .support.recording_transport import envelope, json_response
from .support.wire import assert_signed, body_of, path_of, query_of

PAYMENT = "7c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
CONNECTION = "2b3c4d5e-6f70-4182-9a3b-4c5d6e7f8091"
ORDER = "inso_0123456789abcdef0123456789abcdef"
QUOTE = "insq_0123456789abcdef0123456789abcdef"
POLICY = "insp_0123456789abcdef0123456789abcdef"
KEY = "insurance-op-0001"
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
ITEM = {"id": "item-1", "name": "Ticket", "price": "120000", "insuranceCategory": "TICKET"}
OPTION = {
    "quoteId": QUOTE,
    "premiumAmount": "4500",
    "terms": {"version": "v3", "sha256": "ab" * 32},
}


def ok(data, status=200):
    return json_response(envelope(data), status)


def test_create_quote_from_basket_items(client_factory, test_key_pair):
    transport, client = client_factory(ok({"options": [OPTION], "excludedOptions": []}, 201))
    client.insurance().create_quote(
        insurance_type="TICKET_CANCELLATION",
        currency="try",
        context={"items": [ITEM]},
        insured=[{"identityType": "TCKN", "identityNumber": "10000000146"}],
    )
    request = transport.last
    assert (request.method, path_of(request)) == ("POST", "/api/v1/insurance/quotes")
    assert body_of(request) == {
        "insuranceType": "TICKET_CANCELLATION",
        "currency": "TRY",
        "context": {"items": [ITEM]},
        "insured": [{"identityType": "TCKN", "identityNumber": "10000000146"}],
    }
    assert request.header("Idempotency-Key") is None
    assert_signed(request, test_key_pair[1])


def test_create_quote_takes_an_optional_key(client_factory):
    transport, client = client_factory(ok({"options": []}, 201))
    client.insurance().create_quote(
        {"insuranceType": "TRAVEL_HEALTH", "currency": "TRY", "paymentIntentId": PAYMENT},
        idempotency_key=KEY,
    )
    assert transport.last.header("Idempotency-Key") == KEY
    with pytest.raises(ConfigurationError, match="8-200"):
        client.insurance().create_quote(
            {"insuranceType": "TRAVEL_HEALTH", "currency": "TRY"}, idempotency_key="short"
        )


@pytest.mark.parametrize(
    "fields, message",
    [
        (
            {"paymentIntentId": PAYMENT, "context": {"items": [ITEM]}},
            "not both",
        ),
        ({"paymentIntentId": "pi-1"}, "UUID"),
        ({"context": {"items": []}}, "1 to 100"),
        ({"context": {"items": [ITEM], "currency": "TRY"}}, "Unknown context field"),
        ({"amount": "4500"}, "Unknown createQuote request field"),
        ({"merchantOrderId": "m" * 129}, "at most 128"),
    ],
)
def test_create_quote_is_refused_before_sending(client_factory, fields, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.insurance().create_quote(
            {"insuranceType": "TICKET_CANCELLATION", "currency": "TRY", **fields}
        )
    assert transport.requests == []


def test_create_order_requires_a_key_and_sends_the_consent(client_factory):
    transport, client = client_factory(ok({"orderId": ORDER}, 201))
    accepted = datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc)
    consent = InsuranceClient.consent_from_quote(OPTION, accepted)
    with pytest.raises(ConfigurationError, match="Idempotency-Key is required"):
        client.insurance().create_order(quote_id=QUOTE, consent=consent)
    assert transport.requests == []
    client.insurance().create_order(
        quote_id=QUOTE, merchant_order_id="order-42", consent=consent, idempotency_key=KEY
    )
    assert path_of(transport.last) == "/api/v1/insurance/orders"
    assert transport.last.header("Idempotency-Key") == KEY
    assert body_of(transport.last) == {
        "quoteId": QUOTE,
        "merchantOrderId": "order-42",
        "consent": {
            "termsVersion": "v3",
            "termsSha256": "ab" * 32,
            "acceptedAt": "2026-11-15T09:30:00.000Z",
        },
    }


def test_consent_from_quote_needs_terms():
    with pytest.raises(ConfigurationError, match="terms"):
        InsuranceClient.consent_from_quote({"quoteId": QUOTE}, "2026-11-15T09:30:00Z")
    with pytest.raises(ConfigurationError, match="timezone-aware"):
        InsuranceClient.consent_from_quote(OPTION, datetime(2026, 11, 15))


@pytest.mark.parametrize(
    "call",
    [
        lambda insurance: insurance.issue_policy(ORDER),
        lambda insurance: insurance.cancel_order(ORDER),
        lambda insurance: insurance.refund_premium(ORDER),
        lambda insurance: insurance.create_lead(insurance_type="CARGO_TRANSIT"),
        lambda insurance: insurance.confirm_payment(
            ORDER,
            {
                "externalPaymentId": "ext-1",
                "paidAmount": "4500",
                "paidCurrency": "TRY",
                "paidAt": "2026-11-15T09:30:00Z",
            },
        ),
    ],
)
def test_keyed_writes_refuse_a_missing_key(client_factory, call):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match="Idempotency-Key is required"):
        call(client.insurance())
    assert transport.requests == []


def test_confirm_payment_body(client_factory):
    transport, client = client_factory(ok({"orderId": ORDER}))
    client.insurance().confirm_payment(
        ORDER,
        {
            "external_payment_id": "ext-1",
            "paid_amount": "4500",
            "paid_currency": "TRY",
            "paid_at": "2026-11-15T09:30:00+03:00",
        },
        idempotency_key=KEY,
    )
    assert path_of(transport.last) == f"/api/v1/insurance/orders/{ORDER}/confirm-payment"
    assert body_of(transport.last) == {
        "payment": {
            "externalPaymentId": "ext-1",
            "paidAmount": "4500",
            "paidCurrency": "TRY",
            "paidAt": "2026-11-15T09:30:00+03:00",
        }
    }
    with pytest.raises(ConfigurationError, match="paidAmount"):
        client.insurance().confirm_payment(
            ORDER,
            {
                "externalPaymentId": "ext-1",
                "paidAmount": 4500,
                "paidCurrency": "TRY",
                "paidAt": "2026-11-15T09:30:00Z",
            },
            idempotency_key=KEY,
        )


def test_refund_premium_sends_an_empty_object_or_the_external_refund(client_factory):
    transport, client = client_factory(ok({"orderId": ORDER}), ok({"orderId": ORDER}))
    client.insurance().refund_premium(ORDER, idempotency_key=KEY)
    assert transport.last.body == "{}"
    client.insurance().refund_premium(
        ORDER,
        external_refund={"externalRefundId": "r-1", "refundedAt": "2026-11-15T10:00:00Z"},
        idempotency_key=KEY,
    )
    assert body_of(transport.last) == {
        "externalRefund": {"externalRefundId": "r-1", "refundedAt": "2026-11-15T10:00:00Z"}
    }


def test_issue_policy_and_cancel_send_no_body(client_factory):
    transport, client = client_factory(ok({"orderId": ORDER}), ok({"orderId": ORDER}))
    client.insurance().issue_policy(ORDER, idempotency_key=KEY)
    assert path_of(transport.last) == f"/api/v1/insurance/orders/{ORDER}/issue-policy"
    assert transport.last.body is None
    client.insurance().cancel_order(ORDER, idempotency_key=KEY)
    assert path_of(transport.last) == f"/api/v1/insurance/orders/{ORDER}/cancel"


def test_bind_payment_key_is_optional(client_factory):
    transport, client = client_factory(ok({"orderId": ORDER}))
    client.insurance().bind_payment(ORDER, PAYMENT)
    assert body_of(transport.last) == {"paymentIntentId": PAYMENT}
    assert transport.last.header("Idempotency-Key") is None


@pytest.mark.parametrize("name", ["get_policy_document", "get_policy_receipt"])
def test_policy_files_are_bytes(client_factory, test_key_pair, name):
    transport, client = client_factory(HttpResponse(200, {"content-type": "application/pdf"}, PDF))
    file = getattr(client.insurance(), name)(POLICY)
    assert isinstance(file, BinaryResponse)
    assert (file.content_type, file.content) == ("application/pdf", PDF)
    suffix = name.rsplit("_", 1)[1]
    assert path_of(transport.last) == f"/api/v1/insurance/policies/{POLICY}/{suffix}"
    assert transport.last.header("Accept").startswith("application/pdf")
    assert_signed(transport.last, test_key_pair[1])


def test_policy_certificate_path(client_factory):
    transport, client = client_factory(HttpResponse(200, {"content-type": "application/pdf"}, PDF))
    assert client.insurance().get_policy_certificate(POLICY).content == PDF
    assert path_of(transport.last).endswith("/certificate")


def test_export_reconciliation_reads_the_trailer(client_factory):
    csv = (
        "\ufefforderId,policyId\r\ninso_1,insp_1\r\n"
        "# truncated=true orderCap=20000 nextCursor=abc123\r\n"
    )
    transport, client = client_factory(
        HttpResponse(200, {"content-type": "text/csv; charset=utf-8"}, csv.encode("utf-8"))
    )
    export = client.insurance().export_reconciliation(
        from_="2026-10-01T00:00:00Z", to=datetime(2026, 11, 1, tzinfo=timezone.utc)
    )
    assert isinstance(export, InsuranceReconciliationExport)
    assert (export.truncated, export.next_cursor, export.aborted) == (True, "abc123", False)
    assert query_of(transport.last) == {
        "from": ["2026-10-01T00:00:00Z"],
        "to": ["2026-11-01T00:00:00.000Z"],
    }
    assert transport.last.header("Accept").startswith("text/csv")


def test_export_reconciliation_aborted_line(client_factory):
    csv = b"orderId\ninso_1\n# export-aborted=true\n"
    transport, client = client_factory(HttpResponse(200, {"content-type": "text/csv"}, csv))
    period = {"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"}
    export = client.insurance().export_reconciliation(**period)
    assert (export.truncated, export.next_cursor, export.aborted) == (False, None, True)


@pytest.mark.parametrize(
    "call, message",
    [
        (lambda insurance: insurance.list_products(), "requires 'currency'"),
        (lambda insurance: insurance.get_reconciliation_summary(to="2026-11-01"), "'from'"),
        (lambda insurance: insurance.list_orders(payment_intent_id="pi-1"), "UUID"),
        (lambda insurance: insurance.list_leads(status="DONE"), "status"),
        (lambda insurance: insurance.list_orders(limit=101), "limit"),
        (lambda insurance: insurance.list_orders(environment="TEST"), "Unknown insurance filter"),
        (lambda insurance: insurance.list_reference_values("ADDRESS_STREET"), "Reference kind"),
    ],
)
def test_filters_are_refused_before_sending(client_factory, call, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        call(client.insurance())
    assert transport.requests == []


def test_list_products_and_reference_values(client_factory):
    transport, client = client_factory(
        ok({"products": []}),
        json_response(envelope({"items": [{"code": "34"}]}, pageInfo={"hasMore": False})),
    )
    client.insurance().list_products(currency="TRY", payment_intent_id=PAYMENT)
    assert query_of(transport.last) == {"currency": ["TRY"], "paymentIntentId": [PAYMENT]}
    district = InsuranceReferenceKind.DISTRICT
    page = client.insurance().list_reference_values(district, parent_code="34")
    assert page.items == [{"code": "34"}]
    assert path_of(transport.last) == "/api/v1/insurance/reference/DISTRICT"
    assert query_of(transport.last) == {"parentCode": ["34"]}


def test_create_lead_sends_the_note_as_given(client_factory):
    transport, client = client_factory(ok({"leadId": "insl_1", "status": "SUBMITTED"}, 201))
    note = "  call after 18:00  "
    client.insurance().create_lead(
        insurance_type="CARGO_TRANSIT",
        policyholder={"identityType": "TCKN"},
        shipment={"cargoDescription": "Boxes"},
        note=note,
        idempotency_key=KEY,
    )
    assert body_of(transport.last)["note"] == note
    assert path_of(transport.last) == "/api/v1/insurance/leads"
    with pytest.raises(ConfigurationError, match="1000"):
        client.insurance().create_lead(
            insurance_type="CARGO_TRANSIT", note="n" * 1001, idempotency_key=KEY
        )
    with pytest.raises(ConfigurationError, match="Unknown createLead request field"):
        client.insurance().create_lead(
            insurance_type="CARGO_TRANSIT", currency="TRY", idempotency_key=KEY
        )


def test_premium_basket_item():
    order = {"orderId": ORDER, "premiumAmount": "4500", "premiumCollectedBy": "MERCHANT"}
    assert InsuranceClient.premium_basket_item(order, name="Insurance", category1="Insurance") == {
        "id": ORDER,
        "price": "4500",
        "name": "Insurance",
        "category1": "Insurance",
        "itemType": "VIRTUAL",
    }
    with pytest.raises(ConfigurationError, match="MERCHANT"):
        InsuranceClient.premium_basket_item(
            {**order, "premiumCollectedBy": "PROVIDER"}, name="Insurance", category1="Insurance"
        )
    with pytest.raises(ConfigurationError, match="premiumAmount"):
        InsuranceClient.premium_basket_item(
            {**order, "premiumAmount": 4500}, name="Insurance", category1="Insurance"
        )


def event(event_type, data):
    return WebhookEvent(id="evt_1", type=event_type, timestamp=None, data=data, raw={"data": data})


def test_order_event_reader():
    data = {
        "eventId": "evt_1",
        "eventType": InsuranceEvents.POLICY_ISSUED,
        "insuranceOrderId": ORDER,
        "premiumAmount": "4500",
        "currency": "TRY",
        "policyStatus": "ISSUED",
        "provider": {"code": "P1", "name": "Provider", "logoUrl": None, "connectionId": CONNECTION},
        "policies": [{"policyId": POLICY, "documentUrl": ""}],
        "createdAt": "2026-11-15T09:30:00Z",
    }
    order = InsuranceWebhookData.from_event(event(InsuranceEvents.POLICY_ISSUED, data))
    assert (order.insurance_order_id, order.premium_amount) == (ORDER, "4500")
    assert order.policies[0].policy_id == POLICY and order.policies[0].document_url == ""
    assert order.error_code is None
    with pytest.raises(ConfigurationError, match="does not read"):
        InsuranceWebhookData.from_event(event(InsuranceEvents.LEAD_SUBMITTED, data))


def test_lead_event_reader():
    data = {
        "eventId": "evt_2",
        "eventType": InsuranceEvents.LEAD_SUBMITTED,
        "merchantId": "m-1",
        "lead": {"leadId": "insl_1", "schemaVersion": 1, "status": "SUBMITTED"},
        "createdAt": "2026-11-15T09:30:00Z",
    }
    lead = InsuranceLeadWebhookData.from_event(event(InsuranceEvents.LEAD_SUBMITTED, data))
    assert lead.lead is not None
    assert (lead.lead.lead_id, lead.lead.schema_version) == ("insl_1", 1)
    assert lead.lead.submitted_at is None
