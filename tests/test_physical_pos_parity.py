"""Physical POS parity with the gateway and the other SDKs (review O-5).

``tests/fixtures/physical-pos-parity.json`` is byte-identical in the Node,
PHP, Java and Python SDKs. Its expected values were computed from the gateway
rules (card-data key tokens, the guard's field paths, the service's PAN value
scan); the closed field and filter lists are the gateway DTOs. A rule or list
that drifts in one SDK turns this test red.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from lunixi.errors import ConfigurationError, PhysicalPosCardDataRejectedError
from lunixi.physical_pos import (
    PHYSICAL_POS_EVENT_TYPES,
    PAYMENT_FIELDS,
    PAYMENT_TARGET_FIELDS,
    PHYSICAL_POS_FILTERS,
    PHYSICAL_POS_NOT_STARTED_CODES,
    REFUND_ITEM_FIELDS,
    REVERSAL_FIELDS,
    SALE_ITEM_FIELDS,
    contains_pan_like_value,
    find_card_data_field,
    is_card_data_key,
)
from lunixi.physical_pos import _support, card_data, management
from lunixi.physical_pos.webhook import webhook_original

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "physical-pos-parity.json").read_text(encoding="utf-8")
)
KEY = "pos-parity-key-0001"
SALE = {
    "operation": "SALE",
    "target": {"deviceId": "5f0c2b1e-1111-4222-8333-444455556666"},
    "amountMinor": "4500",
    "currency": "TRY",
}

#: Python route names → the fixture's route names (audit / link / assignment lists share "history").
_ROUTES = {
    "list_payments": "listPayments",
    "list_transactions": "listTransactions",
    "list_ambiguous_payments": "listAmbiguousPayments",
    "get_sales_summary": "getSalesSummary",
    "get_tax_summary": "getTaxSummary",
    "list_settlements": "listSettlements",
    "list_device_models": "listDeviceModels",
    "list_stores": "listStores",
    "list_registers": "listRegisters",
    "list_terminals": "listTerminals",
    "list_terminal_acquirers": "listTerminalAcquirers",
    "list_devices": "listDevices",
    "list_store_audit": "history",
    "list_register_audit": "history",
    "list_terminal_links": "history",
    "list_terminal_audit": "history",
    "list_device_assignments": "history",
    "list_device_audit": "history",
}


def test_card_data_term_lists_match():
    rule = FIXTURE["cardDataKeyRule"]
    assert list(card_data._CARD_NUMBER_TERMS) == rule["numberTerms"]
    assert list(card_data._CARD_SECRET_TERMS) == rule["secretTerms"]
    assert list(card_data._SUFFIX_TERMS) == rule["suffixTerms"]
    assert card_data._WHOLE_KEY_TERMS == frozenset(rule["wholeKeyTerms"])
    assert card_data._MASK_TOKENS == frozenset(rule["maskTokens"])
    assert card_data._DIGIT_RUN.pattern == rule["digitRunKeyPattern"]


@pytest.mark.parametrize("case", FIXTURE["cardDataKeyCases"], ids=lambda c: c["key"])
def test_card_data_key_cases(case):
    assert is_card_data_key(case["key"]) is case["cardData"]


@pytest.mark.parametrize("case", FIXTURE["cardDataPathCases"], ids=lambda c: json.dumps(c["body"]))
def test_card_data_path_cases(case):
    assert find_card_data_field(case["body"]) == case["field"]


@pytest.mark.parametrize("case", FIXTURE["panValueCases"], ids=lambda c: f'{c["mode"]}:{c["value"]}')
def test_pan_value_cases(case):
    assert contains_pan_like_value(case["value"], case["mode"]) is case["pan"]


@pytest.mark.parametrize("case", FIXTURE["idempotencyKeyCases"], ids=lambda c: repr(c["key"][:20]))
def test_idempotency_key_cases(case):
    if case["valid"]:
        assert _support.checked_idempotency_key(case["key"]) == case["key"]
    else:
        with pytest.raises(ConfigurationError):
            _support.checked_idempotency_key(case["key"])


@pytest.mark.parametrize("field", FIXTURE["forbiddenFields"])
def test_forbidden_fields_are_refused_before_sending(client_factory, field):
    transport, client = client_factory()
    with pytest.raises((ConfigurationError, PhysicalPosCardDataRejectedError)):
        client.physical_pos().create_payment(dict(SALE, **{field: "x"}), idempotency_key=KEY)
    assert transport.requests == []


def test_request_field_lists_match_the_gateway_dtos():
    fields = FIXTURE["requestFields"]
    assert list(PAYMENT_FIELDS) == fields["createPayment"]
    assert list(PAYMENT_TARGET_FIELDS) == fields["paymentTarget"]
    assert list(SALE_ITEM_FIELDS) == fields["saleItem"]
    assert list(REVERSAL_FIELDS) == fields["createReversal"]
    assert list(REFUND_ITEM_FIELDS) == fields["refundItem"]
    from lunixi.physical_pos import client as payments

    assert list(payments._PAYMENT) == fields["createPayment"]
    assert list(payments._TARGET) == fields["paymentTarget"]
    assert list(payments._SALE_ITEM) == fields["saleItem"]
    assert list(payments._REVERSAL) == fields["createReversal"]
    assert list(payments._REFUND_ITEM) == fields["refundItem"]
    schemas = {
        "createStore": management._CREATE_STORE,
        "updateStore": management._UPDATE_STORE,
        "statusChange": management._STATUS_CHANGE,
        "createRegister": management._CREATE_REGISTER,
        "updateRegister": management._UPDATE_REGISTER,
        "createTerminal": management._CREATE_TERMINAL,
        "updateTerminal": management._UPDATE_TERMINAL,
        "addTerminalAcquirer": management._ADD_ACQUIRER,
        "updateTerminalAcquirer": management._UPDATE_ACQUIRER,
        "changeTerminalDevice": management._CHANGE_TERMINAL_DEVICE,
        "createDevice": management._CREATE_DEVICE,
        "updateDevice": management._UPDATE_DEVICE,
        "assignDevice": management._ASSIGN_DEVICE,
        "changeDeviceLifecycle": management._DEVICE_LIFECYCLE,
    }
    for name, schema in schemas.items():
        assert sorted(schema) == sorted(fields[name]), name


def test_filter_lists_match_the_gateway_dtos():
    for route, wire in PHYSICAL_POS_FILTERS.items():
        assert sorted(wire) == sorted(FIXTURE["filters"][_ROUTES[route]]), route
    assert set(_ROUTES.values()) == set(FIXTURE["filters"])


def test_event_types_match():
    assert list(PHYSICAL_POS_EVENT_TYPES) == FIXTURE["eventTypes"]


@pytest.mark.parametrize("case", FIXTURE["webhookOriginalCases"], ids=lambda case: case["name"])
def test_webhook_original_cases(case):
    assert webhook_original(case["data"]) == case["original"]


def test_not_started_codes_match():
    assert PHYSICAL_POS_NOT_STARTED_CODES == frozenset(FIXTURE["notStartedCodes"])


@pytest.mark.parametrize("case", FIXTURE["pathIdCases"], ids=lambda c: repr(c["id"]))
def test_path_id_cases(case):
    if case["valid"]:
        encoded = _support.path_id(case["id"], "payment_id")
        assert encoded == case.get("encoded", case["id"])
    else:
        with pytest.raises(ConfigurationError):
            _support.path_id(case["id"], "payment_id")
