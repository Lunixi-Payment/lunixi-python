import pytest

from lunixi.errors import ConfigurationError
from lunixi.payments import CreateIntent, PaymentsClient
from lunixi.validation import amount_minor, decimal_to_minor, validate_money_fields

LARGE = "9007199254740993"


@pytest.mark.parametrize("value", [1, True, 1.5, "0", "-0", "01", "+1", " 1", "1.0", "1e3", "9223372036854775808"])
def test_public_money_rejects_numbers_and_noncanonical_strings(value):
    with pytest.raises(ConfigurationError):
        CreateIntent(value, "TRY", "order").to_dict()


def test_exact_currency_conversions_and_signed_balance():
    for decimal, currency in [(LARGE, "JPY"), ("90071992547409.93", "TRY"), ("9007199254740.993", "KWD")]:
        assert decimal_to_minor(decimal, currency) == LARGE
    assert amount_minor("-9007199254740993", signed=True) == "-9007199254740993"
    assert CreateIntent(LARGE, "TRY", "order").to_dict()["amount"] == LARGE
    for decimal, currency in [("1.1", "JPY"), ("1.001", "TRY"), ("1", "ZZZ")]:
        with pytest.raises(ConfigurationError):
            decimal_to_minor(decimal, currency)


def test_explicit_dto_fields_preserve_opaque_payloads_and_reject_numeric_responses():
    validate_money_fields({"amount": LARGE, "metadata": {"amount": 1}, "providerPayload": {"amount": 1}, "rate": 1.5})
    with pytest.raises(ConfigurationError):
        validate_money_fields({"data": {"amount": 1}}, response=True)


def test_absent_capture_and_refund_mean_remaining_but_zero_is_invalid():
    class RecordingApi:
        def __init__(self):
            self.bodies = []

        def request(self, method, path, body=None, **options):
            self.bodies.append(body)
            return {"data": {"amount": LARGE}}

    api = RecordingApi()
    payments = PaymentsClient(api)
    payments.capture("pi-1", idempotency_key="stable-operation-key")
    payments.refund("pi-1", idempotency_key="stable-operation-key")
    assert api.bodies == [{}, {}]
    for method in [payments.capture, payments.refund]:
        for invalid in [None, "0"]:
            with pytest.raises(ConfigurationError):
                method("pi-1", invalid, idempotency_key="stable-operation-key")
    assert api.bodies == [{}, {}]


@pytest.mark.parametrize("operation", ["capture", "refund"])
def test_raw_mutation_null_is_rejected_before_auth_or_transport(client_factory, operation):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.api().request("POST", f"/api/v1/payments/pi-1/{operation}", {"amount": None}, idempotency_key="stable-operation-key")
    assert transport.requests == []
