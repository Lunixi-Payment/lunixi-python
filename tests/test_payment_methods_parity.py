"""Payment methods, promissory notes, split payments and Para Transferi (BANK_TRANSFER)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi import (
    BANK_TRANSFER_OTHER_BANKS_CODE,
    METHOD_BLOCK_FIELDS,
    SPLIT_LEG_BLOCK_FIELDS,
    SPLIT_LEG_EVENTS_SUBSCRIPTION,
    BankTransferInstruction,
    BinaryResponse,
    DirectMethodPaymentRequest,
    PaymentActionType,
    PaymentBankTransferEvents,
    PaymentBankTransferExceptionKind,
    PaymentBankTransferExceptionStatus,
    PaymentMethod,
    PromissoryNoteEvents,
    ProviderSelection,
    ProviderSelectionMode,
    SplitPaymentEvents,
    SplitPaymentRequest,
)
from lunixi.auth.canonical_request import build_canonical_request
from lunixi.auth.ed25519_signer import verify_signature
from lunixi.errors import ApiError, ConfigurationError, ValidationError
from lunixi.http.transport import HttpResponse
from lunixi.payments import (
    BANK_TRANSFER_EXCEPTION_LIMIT_MAX,
    CARD_ONLY_FIELDS,
    DIRECT_METHOD_PAYMENT_FIELDS,
    PAYMENT_ACTION_CONFIRM_FIELDS,
    PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS,
    SHOPPING_LOAN_MAX_BASKET_ITEMS,
    SPLIT_PAYMENT_IN_PROGRESS_STATUSES,
    PromissoryNoteCancelErrorCode,
    PromissoryNoteCancelResult,
    PromissoryNoteDocumentLocale,
    PromissoryNoteDocumentType,
    PromissoryNoteStatus,
    block_name_of,
    normalize_payment_method,
)

from .support.recording_transport import envelope, error_envelope, json_response

EXCEPTION_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def assert_signed(request, public_key):
    for header in ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature"):
        assert request.header(header), header
    canonical = build_canonical_request(
        request.method,
        request.path,
        request.header("X-Date"),
        request.header("X-Nonce"),
        request.header("Digest"),
    )
    assert verify_signature(public_key, request.header("X-Signature"), canonical) is True


def query_of(request):
    return parse_qs(urlsplit(request.url).query)


def bank_transfer_request():
    return DirectMethodPaymentRequest("15000", "TRY", "order-1").with_method_fields(
        PaymentMethod.BANK_TRANSFER, None, {"bankCode": "0062"}
    )


def raw_body(**overrides):
    body = {
        "paymentMethod": "MOBILE_BILLING",
        "amount": "15000",
        "currency": "TRY",
        "orderId": "order-1",
        "mobileBilling": {"providerCode": "provider_a", "gsmNumber": "+905321234567"},
    }
    body.update(overrides)
    return body


def schedule(*rows):
    return [{"amount": amount, "dueDate": due} for amount, due in rows]


# ── constants ────────────────────────────────────────────────────────────────


def test_payment_method_codes_match_the_gateway():
    assert PaymentMethod.ALL == (
        "CARD",
        "BNPL",
        "SHOPPING_LOAN",
        "PROMISSORY_NOTE",
        "MEAL_CARD",
        "GIFT_CARD",
        "CASH",
        "CASH_ON_DELIVERY",
        "WALLET",
        "BANK_TRANSFER",
        "OPEN_BANKING",
        "MOBILE_BILLING",
        "QR_CODE",
        "CRYPTO",
        "OTHER",
    )
    assert normalize_payment_method("QR") == "QR_CODE"
    assert block_name_of("BANK_TRANSFER") == "bankTransfer"
    assert block_name_of("MOBILE_BILLING") == "mobileBilling"


def test_action_and_provider_selection_values():
    assert [
        PaymentActionType.OTP,
        PaymentActionType.REDIRECT,
        PaymentActionType.DISPLAY,
        PaymentActionType.APP_APPROVAL,
        PaymentActionType.INPUT,
    ] == ["OTP", "REDIRECT", "DISPLAY", "APP_APPROVAL", "INPUT"]
    assert (ProviderSelection.ROUTED, ProviderSelection.OPTIONAL, ProviderSelection.REQUIRED) == (
        "ROUTED",
        "OPTIONAL",
        "REQUIRED",
    )
    assert (ProviderSelectionMode.BUYER, ProviderSelectionMode.PLATFORM) == ("BUYER", "PLATFORM")


def test_field_lists():
    assert METHOD_BLOCK_FIELDS == (
        "mobileBilling",
        "wallet",
        "promissoryNote",
        "mealCard",
        "openBanking",
        "shoppingLoan",
        "bankTransfer",
    )
    assert DIRECT_METHOD_PAYMENT_FIELDS[-len(METHOD_BLOCK_FIELDS) :] == METHOD_BLOCK_FIELDS
    for field in ("paymentMethod", "amount", "currency", "orderId", "card", "metadata"):
        assert field in DIRECT_METHOD_PAYMENT_FIELDS
    assert CARD_ONLY_FIELDS == ("card", "installment", "installmentQuoteToken", "force3D")
    assert PAYMENT_ACTION_CONFIRM_FIELDS == ("otp", "consentAccepted", "fields")
    assert SPLIT_LEG_BLOCK_FIELDS == ("mobileBilling", "wallet", "promissoryNote")
    assert SHOPPING_LOAN_MAX_BASKET_ITEMS == 100


def test_bank_transfer_constants():
    assert BANK_TRANSFER_OTHER_BANKS_CODE == "9999"
    assert BANK_TRANSFER_EXCEPTION_LIMIT_MAX == 200
    assert (
        PaymentBankTransferExceptionKind.LATE,
        PaymentBankTransferExceptionKind.UNDERPAID,
        PaymentBankTransferExceptionKind.OVERPAID,
    ) == ("LATE", "UNDERPAID", "OVERPAID")
    assert PaymentBankTransferExceptionStatus.ALL == (
        "PENDING_DECISION",
        "ACCEPTED",
        "REFUND_PENDING",
        "REFUNDED",
    )


def test_event_names():
    assert (
        PaymentBankTransferEvents.PARTIALLY_RECEIVED,
        PaymentBankTransferEvents.UNDERPAID,
        PaymentBankTransferEvents.OVERPAID,
        PaymentBankTransferEvents.LATE_ARRIVAL,
    ) == (
        "payment.bank_transfer.partially_received",
        "payment.bank_transfer.underpaid",
        "payment.bank_transfer.overpaid",
        "payment.bank_transfer.late_arrival",
    )
    assert (
        PromissoryNoteEvents.PAID,
        PromissoryNoteEvents.PROTESTED,
        PromissoryNoteEvents.CANCELLED,
    ) == (
        "payment.promissory_note.paid",
        "payment.promissory_note.protested",
        "payment.promissory_note.cancelled",
    )
    assert (
        SplitPaymentEvents.COMPLETED,
        SplitPaymentEvents.VOIDED,
        SplitPaymentEvents.COMPENSATING,
        SplitPaymentEvents.OUTCOME_PENDING,
        SplitPaymentEvents.RECONCILIATION_REQUIRED,
        SplitPaymentEvents.LEG_REFUND_PENDING,
    ) == (
        "payment.split.completed",
        "payment.split.voided",
        "payment.split.compensating",
        "payment.split.outcome_pending",
        "payment.split.reconciliation_required",
        "payment.split.leg_refund_pending",
    )
    assert SPLIT_LEG_EVENTS_SUBSCRIPTION == "payment.split.leg_events"


def test_promissory_note_values():
    assert PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS == 24
    assert (
        PromissoryNoteStatus.ISSUED,
        PromissoryNoteStatus.PAID,
        PromissoryNoteStatus.PROTESTED,
        PromissoryNoteStatus.CANCELLED,
    ) == ("ISSUED", "PAID", "PROTESTED", "CANCELLED")
    assert (
        PromissoryNoteDocumentType.PROMISSORY_NOTE,
        PromissoryNoteDocumentType.PAYMENT_ORDER,
    ) == ("PROMISSORY_NOTE", "PAYMENT_ORDER")
    assert (
        PromissoryNoteCancelResult.CANCELLED,
        PromissoryNoteCancelResult.ALREADY_CLOSED,
        PromissoryNoteCancelResult.NOT_CANCELLABLE,
        PromissoryNoteCancelResult.FAILED,
    ) == ("CANCELLED", "ALREADY_CLOSED", "NOT_CANCELLABLE", "FAILED")
    assert (
        PromissoryNoteCancelErrorCode.NOT_CANCELLABLE,
        PromissoryNoteCancelErrorCode.PROVIDER_UNAVAILABLE,
        PromissoryNoteCancelErrorCode.CANCEL_REJECTED,
    ) == (
        "payment.promissory_note.not_cancellable",
        "payment.promissory_note.provider_unavailable",
        "payment.promissory_note.cancel_rejected",
    )
    assert (PromissoryNoteDocumentLocale.TR, PromissoryNoteDocumentLocale.EN) == ("tr-TR", "en-GB")


# ── list_payment_methods ─────────────────────────────────────────────────────


def test_list_payment_methods_sends_the_alias_as_qr_code(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"methods": []})))
    client.payments().list_payment_methods("QR")
    request = transport.last
    assert urlsplit(request.url).path == "/api/v1/payments/methods"
    assert query_of(request) == {"paymentMethod": ["QR_CODE"]}
    assert_signed(request, public_key)


def test_methods_keeps_working_without_and_with_a_filter(client_factory):
    transport, client = client_factory(
        json_response(envelope({"methods": []})), json_response(envelope({"methods": []}))
    )
    client.payments().methods()
    assert transport.last.path == "/api/v1/payments/methods"
    client.payments().methods("MOBILE_BILLING")
    assert query_of(transport.last) == {"paymentMethod": ["MOBILE_BILLING"]}


@pytest.mark.parametrize("code", ["qr", "mobile_billing", "", "1CARD", "A" * 33, 5])
def test_an_invalid_method_code_is_refused_locally(client_factory, code):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().list_payment_methods(code)
    assert transport.requests == []


# ── direct_method_payment: BANK_TRANSFER ─────────────────────────────────────


def test_bank_transfer_body_has_the_bank_and_no_provider_code():
    assert bank_transfer_request().to_dict() == {
        "paymentMethod": "BANK_TRANSFER",
        "amount": "15000",
        "currency": "TRY",
        "orderId": "order-1",
        "bankTransfer": {"bankCode": "0062"},
    }


def test_bank_transfer_is_sent_signed_with_the_idempotency_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"paymentId": "pay_1", "status": "PENDING"}), 202)
    )
    client.payments().direct_method_payment(bank_transfer_request(), idempotency_key="order-1-a1")
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/payments/direct/payment"
    assert request.body == (
        '{"paymentMethod":"BANK_TRANSFER","amount":"15000","currency":"TRY",'
        '"orderId":"order-1","bankTransfer":{"bankCode":"0062"}}'
    )
    assert "providerCode" not in request.body
    assert request.header("Idempotency-Key") == "order-1-a1"
    assert_signed(request, public_key)


def test_other_banks_option_is_a_bank_code():
    body = (
        DirectMethodPaymentRequest("15000", "TRY", "order-1")
        .with_method_fields("BANK_TRANSFER", None, {"bankCode": BANK_TRANSFER_OTHER_BANKS_CODE})
        .to_dict()
    )
    assert body["bankTransfer"] == {"bankCode": "9999"}


def test_bank_transfer_with_a_provider_code_is_refused_by_the_builder():
    with pytest.raises(ConfigurationError, match="BANK_TRANSFER"):
        DirectMethodPaymentRequest("15000", "TRY", "order-1").with_method_fields(
            "BANK_TRANSFER", "provider_a", {"bankCode": "0062"}
        )


def test_bank_transfer_with_a_provider_code_is_refused_in_a_raw_body(client_factory):
    transport, client = client_factory()
    body = raw_body(paymentMethod="BANK_TRANSFER", mobileBilling=None)
    del body["mobileBilling"]
    body["bankTransfer"] = {"providerCode": "provider_a", "bankCode": "0062"}
    with pytest.raises(ConfigurationError, match="providerCode"):
        client.payments().direct_method_payment(body, idempotency_key="key-1")
    assert transport.requests == []


# ── direct_method_payment: body rules ────────────────────────────────────────


def test_a_valid_raw_body_is_sent_as_given(client_factory):
    transport, client = client_factory(json_response(envelope({"paymentId": "pay_1"}), 202))
    client.payments().direct_method_payment(raw_body(), idempotency_key="key-1")
    assert json.loads(transport.last.body) == raw_body()


@pytest.mark.parametrize(
    "body",
    [
        raw_body(wallet={"providerCode": "provider_b"}),
        raw_body(installment=3),
        raw_body(force3D=True),
        raw_body(card={"cardToken": "tok"}),
        raw_body(unknownField="x"),
        raw_body(price="15000"),
        raw_body(paidPrice="15000"),
        raw_body(mobileBilling=None),
        raw_body(amount=15000),
        raw_body(preauth="false"),
        raw_body(paymentMethod="GIFT_CARD", giftCard={}),
        raw_body(paymentMethod="GIFT_CARD", mobileBilling=None),
        {key: value for key, value in raw_body().items() if key != "orderId"},
    ],
)
def test_a_broken_raw_body_is_refused_before_sending(client_factory, body):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().direct_method_payment(body, idempotency_key="key-1")
    assert transport.requests == []


@pytest.mark.parametrize("key", [None, "", " key", "k" * 201])
def test_the_idempotency_key_is_required(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().direct_method_payment(bank_transfer_request(), idempotency_key=key)
    assert transport.requests == []


def test_card_fields_are_refused_on_another_method_in_the_builder():
    request = (
        DirectMethodPaymentRequest("15000", "TRY", "order-1")
        .with_method_fields("WALLET", "provider_b", {})
        .with_installment(3)
    )
    with pytest.raises(ConfigurationError, match="installment"):
        request.to_dict()


def test_card_payment_carries_card_fields():
    body = (
        DirectMethodPaymentRequest("15000", "TRY", "order-1")
        .with_card({"cardUserKey": "cuk_1", "cardToken": "ct_1"})
        .with_force3d(True)
        .with_installment(3, "quote-token")
        .with_callback_url("https://shop.example/return/order-1")
        .to_dict()
    )
    assert body["paymentMethod"] == "CARD"
    assert body["card"] == {"cardUserKey": "cuk_1", "cardToken": "ct_1"}
    assert body["force3D"] is True
    assert body["installment"] == 3
    assert body["installmentQuoteToken"] == "quote-token"


def test_card_through_with_method_fields_and_a_method_without_block_are_refused():
    request = DirectMethodPaymentRequest("15000", "TRY", "order-1")
    with pytest.raises(ConfigurationError, match="with_card"):
        request.with_method_fields("CARD", None, {})
    with pytest.raises(ConfigurationError, match="GIFT_CARD"):
        request.with_method_fields("GIFT_CARD", None, {})
    with pytest.raises(ConfigurationError):
        request.to_dict()


@pytest.mark.parametrize("count", [0, 101])
def test_shopping_loan_basket_must_have_1_to_100_items(count):
    request = (
        DirectMethodPaymentRequest("15000", "TRY", "order-1")
        .with_method_fields("SHOPPING_LOAN", "provider_c", {"bankCode": "0062"})
        .with_basket_items([{"id": f"sku-{i}", "name": "Phone"} for i in range(count)])
    )
    with pytest.raises(ConfigurationError, match="basket"):
        request.to_dict()


def test_shopping_loan_without_basket_is_refused():
    request = DirectMethodPaymentRequest("15000", "TRY", "order-1").with_method_fields(
        "SHOPPING_LOAN", "provider_c", {"bankCode": "0062"}
    )
    with pytest.raises(ConfigurationError, match="basketItems"):
        request.to_dict()


# ── promissory-note plan ─────────────────────────────────────────────────────


def promissory_request(amount="30000"):
    return DirectMethodPaymentRequest(amount, "TRY", "order-1").with_method_fields(
        PaymentMethod.PROMISSORY_NOTE, "provider_d", {"debtorTckn": "10000000146"}
    )


def test_a_valid_schedule_is_sent_in_the_block():
    body = (
        promissory_request()
        .with_promissory_note_schedule(
            schedule(("10000", "2027-01-15"), ("10000", "2027-02-15"), ("10000", "2027-02-15"))
        )
        .to_dict()
    )
    assert body["promissoryNote"] == {
        "providerCode": "provider_d",
        "debtorTckn": "10000000146",
        "schedule": [
            {"amount": "10000", "dueDate": "2027-01-15"},
            {"amount": "10000", "dueDate": "2027-02-15"},
            {"amount": "10000", "dueDate": "2027-02-15"},
        ],
    }


def test_a_note_count_is_sent_as_a_string():
    body = promissory_request().with_promissory_note_count(6).to_dict()
    assert body["promissoryNote"]["noteCount"] == "6"


@pytest.mark.parametrize(
    "rows",
    [
        schedule(("10000", "2027-01-15"), ("10000", "2027-02-15")),
        schedule(("15000", "2027-01-15"), ("15000", "2027-02-30")),
        schedule(("15000", "2027-03-15"), ("15000", "2027-02-15")),
        schedule(("15000", "2027-1-15"), ("15000", "2027-02-15")),
        schedule(("0", "2027-01-15"), ("30000", "2027-02-15")),
        [{"amount": 30000, "dueDate": "2027-01-15"}],
        [{"amount": "30000", "dueDate": "2027-01-15", "note": "x"}],
        schedule(*[("1250", "2027-01-15")] * 24 + [("0", "2027-01-15")]),
        schedule(*[("1200", "2027-01-15")] * 25),
        [],
    ],
)
def test_a_broken_schedule_is_refused(rows):
    with pytest.raises(ConfigurationError):
        promissory_request().with_promissory_note_schedule(rows).to_dict()


def test_twenty_five_rows_are_refused_even_when_they_add_up():
    rows = schedule(*[("1200", "2027-01-15")] * 25)
    with pytest.raises(ConfigurationError, match="at most 24"):
        promissory_request().with_promissory_note_schedule(rows)


def test_schedule_and_note_count_together_are_refused_in_a_raw_body(client_factory):
    transport, client = client_factory()
    body = raw_body(
        paymentMethod="PROMISSORY_NOTE",
        mobileBilling=None,
        amount="30000",
        promissoryNote={
            "providerCode": "provider_d",
            "noteCount": "3",
            "schedule": schedule(("30000", "2027-01-15")),
        },
    )
    del body["mobileBilling"]
    with pytest.raises(ConfigurationError, match="not both"):
        client.payments().direct_method_payment(body, idempotency_key="key-1")
    assert transport.requests == []


def test_a_plan_is_required_and_given_once():
    with pytest.raises(ConfigurationError, match="plan"):
        promissory_request().to_dict()
    request = DirectMethodPaymentRequest("30000", "TRY", "order-1").with_method_fields(
        "PROMISSORY_NOTE", "provider_d", {"noteCount": 3}
    )
    assert request.to_dict()["promissoryNote"]["noteCount"] == "3"
    with pytest.raises(ConfigurationError, match="twice"):
        request.with_promissory_note_count(2).to_dict()
    with pytest.raises(ConfigurationError, match="with_promissory_note_schedule"):
        DirectMethodPaymentRequest("30000", "TRY", "order-1").with_method_fields(
            "PROMISSORY_NOTE", "provider_d", {"schedule": []}
        )


@pytest.mark.parametrize("count", [0, 25, "07", "x", True, 2.0])
def test_an_invalid_note_count_is_refused(count):
    with pytest.raises(ConfigurationError):
        promissory_request().with_promissory_note_count(count)


# ── method block structure ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fields",
    [
        {f"field{i}": "x" for i in range(33)},
        {"gsmNumber": "x" * 1025},
        {"items": [{"name": "x"}] * 11},
        {"__proto__": "x"},
        {"constructor": "x"},
        {"1field": "x"},
        {"field_name": "x"},
        {"address": {f"k{i}": "x" for i in range(17)}},
        {"address": {"nested": {"deeper": "x"}}},
        {"items": [{"inner": [{"x": "y"}]}]},
        {"items": ["x"]},
        {"amount": float("nan")},
        {"providerCode": "provider_a"},
    ],
)
def test_a_block_with_a_broken_shape_is_refused(fields):
    with pytest.raises(ConfigurationError):
        DirectMethodPaymentRequest("15000", "TRY", "order-1").with_method_fields(
            "MOBILE_BILLING", "provider_a", fields
        )


def test_a_block_with_a_broken_shape_is_refused_in_a_raw_body(client_factory):
    transport, client = client_factory()
    block = {"providerCode": "provider_a", **{f"field{i}": "x" for i in range(33)}}
    with pytest.raises(ConfigurationError, match="at most 32"):
        client.payments().direct_method_payment(
            raw_body(mobileBilling=block), idempotency_key="key-1"
        )
    with pytest.raises(ConfigurationError, match="provider_code"):
        client.payments().direct_method_payment(
            raw_body(mobileBilling={"providerCode": "bad code"}), idempotency_key="key-1"
        )
    assert transport.requests == []


def test_address_and_group_values_are_accepted():
    fields = {
        "debtorAddress": {
            "provinceCode": "06",
            "districtCode": "1231",
            "neighborhoodCode": "40012",
            "line": "Example Street 1",
        },
        "guarantors": [{"fullName": "A B", "address": {"provinceCode": "34"}}] * 10,
        "consent": True,
        "count": 2,
    }
    body = (
        DirectMethodPaymentRequest("15000", "TRY", "order-1")
        .with_method_fields("MOBILE_BILLING", "provider_a", fields)
        .to_dict()
    )
    assert body["mobileBilling"] == {"providerCode": "provider_a", **fields}


# ── payment actions ──────────────────────────────────────────────────────────


def test_confirm_sends_only_the_given_fields_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"paymentId": "pay_1"})))
    client.payments().confirm_payment_action("pay_1", "act_1", otp="123456", consent_accepted=True)
    request = transport.last
    assert request.method == "POST"
    assert request.path == "/api/v1/payments/pay_1/actions/act_1/confirm"
    assert request.body == '{"otp":"123456","consentAccepted":true}'
    assert request.header("Idempotency-Key") is None
    assert_signed(request, public_key)


def test_confirm_with_fields(client_factory):
    transport, client = client_factory(json_response(envelope({"paymentId": "pay_1"})))
    client.payments().confirm_payment_action("pay_1", "act_1", fields={"birthDate": "1990-01-01"})
    assert json.loads(transport.last.body) == {"fields": {"birthDate": "1990-01-01"}}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token": "checkout-token"},
        {"checkoutSessionProof": "proof"},
        {"otp": "1234", "unknown": True},
        {"otp": "12a4"},
        {"otp": "12345678901234567"},
        {"otp": 123456},
        {"consent_accepted": "true"},
        {"fields": {"__proto__": "x"}},
        {},
    ],
)
def test_a_broken_confirm_is_refused_locally(client_factory, kwargs):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().confirm_payment_action("pay_1", "act_1", **kwargs)
    assert transport.requests == []


@pytest.mark.parametrize("ids", [("", "act_1"), ("pay_1", " "), (None, "act_1")])
def test_action_path_segments_are_required(client_factory, ids):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().confirm_payment_action(*ids, otp="1234")
    with pytest.raises(ConfigurationError):
        client.payments().resend_payment_action(*ids)
    assert transport.requests == []


def test_action_path_segments_are_encoded(client_factory):
    transport, client = client_factory(json_response(envelope({})))
    client.payments().resend_payment_action("pay 1", "act/1")
    assert transport.last.path == "/api/v1/payments/pay%201/actions/act%2F1/resend"


def test_resend_has_no_body_and_is_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"paymentId": "pay_1"})))
    client.payments().resend_payment_action("pay_1", "act_1")
    request = transport.last
    assert request.path == "/api/v1/payments/pay_1/actions/act_1/resend"
    assert request.body is None
    assert_signed(request, public_key)


# ── DISPLAY instruction ──────────────────────────────────────────────────────


def display_response(**instruction):
    values = {
        "bankCode": "0062",
        "bankName": "Example Bank",
        "holderName": "Example Shop Ltd",
        "iban": "TR000000000000000000000000",
        "amountMinor": "15000",
        "currency": "TRY",
        "paymentCode": "LNX4K7",
        "expiresAt": "2026-11-16T12:00:00Z",
        "otherBank": False,
    }
    values.update(instruction)
    return envelope(
        {
            "paymentId": "pay_1",
            "status": "PENDING",
            "paymentMethod": "BANK_TRANSFER",
            "action": {"id": "act_1", "type": "DISPLAY", "bankTransfer": values},
        }
    )


def test_the_display_instruction_is_read_typed(client_factory):
    transport, client = client_factory(json_response(display_response(), 202))
    response = client.payments().direct_method_payment(
        bank_transfer_request(), idempotency_key="key-1"
    )
    instruction = BankTransferInstruction.from_response(response)
    assert instruction == BankTransferInstruction(
        bank_code="0062",
        bank_name="Example Bank",
        holder_name="Example Shop Ltd",
        iban="TR000000000000000000000000",
        amount_minor="15000",
        currency="TRY",
        payment_code="LNX4K7",
        expires_at="2026-11-16T12:00:00Z",
        other_bank=False,
    )
    assert BankTransferInstruction.from_response(response["data"]) == instruction


def test_no_instruction_without_a_display_action():
    assert BankTransferInstruction.from_response(envelope({"paymentId": "pay_1"})) is None
    otp = envelope({"action": {"type": "OTP", "bankTransfer": {"iban": "x"}}})
    assert BankTransferInstruction.from_response(otp) is None
    qr = envelope({"action": {"type": "DISPLAY", "display": {"qrCode": "x"}}})
    assert BankTransferInstruction.from_response(qr) is None
    assert BankTransferInstruction.from_response(None) is None


def test_an_unreadable_instruction_raises():
    with pytest.raises(ApiError):
        BankTransferInstruction.from_response(display_response(iban=None))
    with pytest.raises(ApiError):
        BankTransferInstruction.from_response(display_response(otherBank="false"))


# ── promissory-note endpoints ────────────────────────────────────────────────


def test_get_promissory_notes_is_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(json_response(envelope({"notes": []})))
    client.payments().get_promissory_notes("pay_1")
    assert transport.last.method == "GET"
    assert transport.last.path == "/api/v1/payments/pay_1/promissory-notes"
    assert_signed(transport.last, public_key)


def test_cancel_promissory_notes_with_and_without_serial_numbers(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"cancelResults": []})),
        json_response(envelope({"cancelResults": []})),
    )
    client.payments().cancel_promissory_notes("pay_1")
    assert transport.last.path == "/api/v1/payments/pay_1/promissory-notes/cancel"
    assert transport.last.body is None
    assert_signed(transport.last, public_key)
    client.payments().cancel_promissory_notes(
        "pay_1", ["SN-0001", "SN-0002"], idempotency_key="cancel-1"
    )
    assert transport.last.body == '{"serialNumbers":["SN-0001","SN-0002"]}'
    assert transport.last.header("Idempotency-Key") == "cancel-1"
    assert_signed(transport.last, public_key)


@pytest.mark.parametrize(
    "serials", [[], ["SN1"], ["SN 0001"], ["x" * 65], [f"SN-{i:04d}" for i in range(25)], [1234]]
)
def test_invalid_serial_numbers_are_refused(client_factory, serials):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().cancel_promissory_notes("pay_1", serials)
    assert transport.requests == []


def test_the_document_is_returned_as_pdf_bytes(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        HttpResponse(200, {"Content-Type": "application/pdf"}, PDF_BYTES)
    )
    document = client.payments().download_promissory_note_document(
        "pay_1", PromissoryNoteDocumentLocale.EN
    )
    assert isinstance(document, BinaryResponse)
    assert document.content == PDF_BYTES
    assert document.content_type == "application/pdf"
    request = transport.last
    assert request.method == "GET"
    assert urlsplit(request.url).path == "/api/v1/payments/pay_1/promissory-notes/document"
    assert query_of(request) == {"locale": ["en-GB"]}
    assert request.header("Accept") == "application/pdf, application/json"
    assert_signed(request, public_key)


def test_the_document_error_is_read_from_the_json_envelope(client_factory):
    transport, client = client_factory(
        json_response(
            error_envelope(
                "payment.promissory_note.document_unavailable", "Unavailable", status_code=409
            ),
            409,
        )
    )
    with pytest.raises(ApiError) as caught:
        client.payments().download_promissory_note_document("pay_1")
    assert caught.value.code == "payment.promissory_note.document_unavailable"
    assert transport.last.path == "/api/v1/payments/pay_1/promissory-notes/document"


def test_a_json_success_is_not_taken_for_a_document(client_factory):
    _, client = client_factory(json_response(envelope({})))
    with pytest.raises(ApiError, match="PDF"):
        client.payments().download_promissory_note_document("pay_1")


@pytest.mark.parametrize("locale", ["tr", "en", "en-US", "TR-tr", ""])
def test_an_unknown_document_locale_is_refused(client_factory, locale):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().download_promissory_note_document("pay_1", locale)
    assert transport.requests == []


# ── bank transfer exceptions ─────────────────────────────────────────────────


def test_exception_list_sends_only_given_filters_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"items": []})), json_response(envelope({"items": []}))
    )
    client.payments().list_bank_transfer_exceptions()
    assert transport.last.path == "/api/v1/payments/bank-transfer/exceptions"
    assert_signed(transport.last, public_key)
    client.payments().list_bank_transfer_exceptions(
        environment="LIVE", status="PENDING_DECISION", limit=200
    )
    assert transport.last.path == (
        "/api/v1/payments/bank-transfer/exceptions"
        "?environment=LIVE&status=PENDING_DECISION&limit=200"
    )
    assert_signed(transport.last, public_key)


@pytest.mark.parametrize(
    "filters",
    [
        {"environment": "PROD"},
        {"environment": "live"},
        {"limit": 0},
        {"limit": 201},
        {"limit": "10"},
        {"limit": True},
        {"status": "OPEN"},
    ],
)
def test_invalid_exception_filters_are_refused(client_factory, filters):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().list_bank_transfer_exceptions(**filters)
    assert transport.requests == []


def test_exception_decisions_go_to_their_paths_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"id": EXCEPTION_ID})), json_response(envelope(None))
    )
    client.payments().accept_bank_transfer_exception(EXCEPTION_ID)
    assert transport.last.method == "POST"
    assert transport.last.path == (
        f"/api/v1/payments/bank-transfer/exceptions/{EXCEPTION_ID}/accept"
    )
    assert transport.last.body is None
    assert_signed(transport.last, public_key)
    upper = EXCEPTION_ID.upper()
    response = client.payments().mark_bank_transfer_exception_refunded(upper)
    assert transport.last.path == f"/api/v1/payments/bank-transfer/exceptions/{upper}/refunded"
    assert response["data"] is None
    assert_signed(transport.last, public_key)


@pytest.mark.parametrize("exception_id", ["exc_1", "", EXCEPTION_ID + "0", None, "../x"])
def test_a_non_uuid_exception_id_is_refused(client_factory, exception_id):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().accept_bank_transfer_exception(exception_id)
    with pytest.raises(ConfigurationError):
        client.payments().mark_bank_transfer_exception_refunded(exception_id)
    assert transport.requests == []


# ── split payments ───────────────────────────────────────────────────────────


def split_request():
    return (
        SplitPaymentRequest("30000", "TRY", "customer-42")
        .with_order_id("order-1")
        .add_card_leg("card_token_1", "20000")
        .add_method_leg("WALLET", "provider_b", "10000", {})
    )


def test_split_payment_is_sent_signed_with_the_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"splitPaymentId": "sp_1", "status": "COMPLETED"}))
    )
    response = client.payments().create_split_payment(split_request(), idempotency_key="split-1")
    assert response["data"]["splitPaymentId"] == "sp_1"
    request = transport.last
    assert request.path == "/api/v1/payments/split"
    assert json.loads(request.body) == {
        "totalAmount": "30000",
        "currency": "TRY",
        "ownerRef": "customer-42",
        "orderId": "order-1",
        "legs": [
            {"cardToken": "card_token_1", "amount": "20000"},
            {
                "paymentMethod": "WALLET",
                "amount": "10000",
                "wallet": {"providerCode": "provider_b"},
            },
        ],
    }
    assert request.header("Idempotency-Key") == "split-1"
    assert_signed(request, public_key)


def test_a_running_split_payment_is_a_result_not_an_error(client_factory):
    running = {
        "status": "error",
        "code": "AWAITING_ACTION",
        "message": "Awaiting action",
        "data": {
            "splitPaymentId": "sp_1",
            "status": "AWAITING_ACTION",
            "pendingStep": {"step": "ACTION", "paymentId": "pay_2", "actionId": "act_2"},
        },
        "statusCode": 400,
    }
    _, client = client_factory(json_response(running, 400))
    response = client.payments().create_split_payment(split_request(), idempotency_key="split-1")
    assert response["code"] in SPLIT_PAYMENT_IN_PROGRESS_STATUSES
    assert response["data"]["pendingStep"]["actionId"] == "act_2"


@pytest.mark.parametrize(
    "answer",
    [
        {"code": "VOIDED", "data": {"splitPaymentId": "sp_1", "status": "VOIDED"}},
        {"code": "AWAITING_ACTION", "data": None},
        {"code": "AWAITING_ACTION", "data": {"splitPaymentId": ""}},
        {"code": "split_pay.validation.amount_mismatch", "data": None},
    ],
)
def test_a_failed_split_payment_raises(client_factory, answer):
    _, client = client_factory(json_response(answer, 400))
    with pytest.raises(ValidationError):
        client.payments().create_split_payment(split_request(), idempotency_key="split-1")


@pytest.mark.parametrize("method", ["BANK_TRANSFER", "OPEN_BANKING", "MEAL_CARD", "SHOPPING_LOAN"])
def test_methods_without_a_leg_block_cannot_be_legs(method):
    with pytest.raises(ConfigurationError, match="cannot be a split payment leg"):
        SplitPaymentRequest("30000", "TRY", "customer-42").add_method_leg(
            method, "provider_x", "10000", {}
        )


@pytest.mark.parametrize(
    "leg",
    [
        {"paymentMethod": "BANK_TRANSFER", "amount": "10000", "bankTransfer": {"bankCode": "1"}},
        {"paymentMethod": "OPEN_BANKING", "amount": "10000", "openBanking": {}},
        {"paymentMethod": "OPEN_BANKING", "amount": "10000", "wallet": {"providerCode": "p"}},
        {"paymentMethod": "WALLET", "amount": "10000", "wallet": {}},
        {"paymentMethod": "WALLET", "amount": "10000"},
        {
            "paymentMethod": "WALLET",
            "amount": "10000",
            "wallet": {"providerCode": "p"},
            "mobileBilling": {"providerCode": "q"},
        },
        {
            "paymentMethod": "WALLET",
            "amount": "10000",
            "wallet": {"providerCode": "p"},
            "force3D": True,
        },
        {
            "paymentMethod": "PROMISSORY_NOTE",
            "amount": "10000",
            "promissoryNote": {"providerCode": "p", "schedule": schedule(("10000", "2027-01-15"))},
        },
        {
            "paymentMethod": "PROMISSORY_NOTE",
            "amount": "10000",
            "promissoryNote": {"providerCode": "p"},
        },
        {"cardToken": "card_token_1", "amount": "10000"},
        {"cardToken": "card_token_2", "amount": "10000", "installment": 3},
        {"cardToken": "card_token_2", "amount": "10000", "wallet": {"providerCode": "p"}},
    ],
)
def test_a_broken_raw_split_leg_is_refused(client_factory, leg):
    transport, client = client_factory()
    body = {
        "totalAmount": "30000",
        "currency": "TRY",
        "ownerRef": "customer-42",
        "legs": [{"cardToken": "card_token_1", "amount": "20000"}, leg],
    }
    with pytest.raises(ConfigurationError):
        client.payments().create_split_payment(body, idempotency_key="split-1")
    assert transport.requests == []


@pytest.mark.parametrize("key", [None, "", "k" * 201])
def test_split_payment_needs_a_key_of_at_most_200_characters(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().create_split_payment(split_request(), idempotency_key=key)
    assert transport.requests == []


def test_split_amounts_must_add_up_and_3ds_needs_a_callback():
    with pytest.raises(ConfigurationError, match="add up"):
        SplitPaymentRequest("30000", "TRY", "c").add_card_leg("card_token_1", "20000").to_dict()
    with pytest.raises(ConfigurationError, match="callbackUrl"):
        SplitPaymentRequest("20000", "TRY", "c").add_card_leg(
            "card_token_1", "20000", force3d=True
        ).to_dict()


def test_list_splits_validates_and_repeats_list_filters(client_factory):
    transport, client = client_factory(json_response(envelope([])))
    client.payments().list_splits(status=["COMPLETED", "VOIDED"], currency="TRY", limit=25)
    assert query_of(transport.last) == {
        "status": ["COMPLETED", "VOIDED"],
        "currency": ["TRY"],
        "limit": ["25"],
    }


@pytest.mark.parametrize(
    "filters",
    [{"status": "DONE"}, {"limit": 0}, {"limit": 101}, {"createdFrom": "yesterday"}, {"page": 2}],
)
def test_list_splits_refuses_invalid_filters(client_factory, filters):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payments().list_splits(**filters)
    assert transport.requests == []


# ── reference address dictionary ─────────────────────────────────────────────


def test_reference_address_routes(client_factory):
    transport, client = client_factory(
        json_response(envelope({"items": []})),
        json_response(envelope({"items": []})),
        json_response(envelope({"items": []})),
    )
    client.reference().list_provinces()
    assert transport.last.path == "/api/v1/reference/tr-address/provinces"
    client.reference().list_districts("06")
    assert transport.last.path == "/api/v1/reference/tr-address/districts?provinceCode=06"
    client.reference().list_neighborhoods("1231")
    assert transport.last.path == "/api/v1/reference/tr-address/neighborhoods?districtCode=1231"


@pytest.mark.parametrize("code", ["6", "00", "82", "6a", 6, ""])
def test_reference_refuses_an_invalid_province_code(client_factory, code):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.reference().list_districts(code)
    assert transport.requests == []


@pytest.mark.parametrize("code", ["", "12a", "1" * 13, 1231])
def test_reference_refuses_an_invalid_district_code(client_factory, code):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.reference().list_neighborhoods(code)
    assert transport.requests == []
