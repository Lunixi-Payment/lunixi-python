from dataclasses import replace

import pytest

from integrations.common import Settings
from lunixi.commerce import CommerceError
from lunixi.errors import ApiError
from lunixi.payments import IntentResult

PAGE = "https://pay.lunixi.com/payment/server-issued-page-0123456789"


def test_backend_url_is_independent_of_browser_token_and_not_printed():
    result = IntentResult.from_response(
        {"data": {"paymentId": "pi_example", "token": "browser_token", "paymentPageUrl": PAGE}}
    )
    assert result.hosted_url == PAGE
    assert result.browser_config()["options"]["token"] == "browser_token"
    assert PAGE not in repr(result)
    assert "browser_token" not in repr(result)


@pytest.mark.parametrize(
    "url",
    [
        None,
        False,
        12,
        [],
        "https://evil.invalid/payment/server-issued-page-0123456789",
        "https://pay.lunixi.com.evil.invalid/payment/server-issued-page-0123456789",
        "http://pay.lunixi.com/payment/server-issued-page-0123456789",
        "https://user@pay.lunixi.com/payment/server-issued-page-0123456789",
        "https://pay.lunixi.com:443/payment/server-issued-page-0123456789",
        PAGE + "?next=evil",
        PAGE + "#x",
        PAGE + "\n",
        "https://pay.lunixi.com/payment/short",
        "https://pay.lunixi.com/payment/" + "x" * 4097,
        "https://pay.lunixi.com/payment/" + "%2f" * 16,
    ],
)
def test_unsafe_backend_url_is_rejected_without_echoing_it(url):
    with pytest.raises(ApiError) as raised:
        IntentResult.from_response(
            {"data": {"paymentId": "pi_example", "token": "browser_token", "paymentPageUrl": url}}
        )
    assert "server-issued-page" not in str(raised.value)


def test_missing_backend_url_keeps_embedded_usable_but_never_builds_a_redirect():
    result = IntentResult.from_response(
        {"data": {"paymentId": "pi_example", "token": "browser_token"}}
    )
    assert result.payment_page_url == ""
    assert result.browser_config()["options"]["token"] == "browser_token"
    with pytest.raises(ApiError):
        _ = result.hosted_url


def test_hosted_backend_url_is_encrypted_reused_and_mode_stays_frozen(payment_setup):
    orders, gateway = payment_setup
    orders.settings = replace(orders.settings, mode="hosted")
    key, _ = orders.seed("owner")
    assert orders.start(key, "owner") == {"redirect": PAGE}
    record = orders.service._load(key)
    assert PAGE not in record["paymentPageUrl"]
    calls = len(gateway.calls)
    assert orders.start(key, "owner") == {"redirect": PAGE}
    assert len(gateway.calls) == calls
    orders.settings = replace(orders.settings, mode="embedded")
    with pytest.raises(CommerceError):
        orders.start(key, "owner")
    after = orders.service._load(key)
    assert after["key"] == record["key"]
    assert after["requestHash"] == record["requestHash"]
    assert len(gateway.calls) == calls


def test_legacy_missing_url_does_not_replace_a_hosted_attempt(payment_setup):
    orders, gateway = payment_setup
    orders.settings = replace(orders.settings, mode="hosted")
    key, _ = orders.seed("owner")
    orders.start(key, "owner")
    with orders.store.transaction(key) as tx:
        record = tx.load()
        record.pop("paymentPageUrl")
        tx.save(record)
    calls = len(gateway.calls)
    with pytest.raises(ApiError):
        orders.start(key, "owner")
    assert len(gateway.calls) == calls
    assert orders.service._load(key)["key"] == record["key"]


def test_new_framework_settings_default_to_embedded(payment_setup):
    orders, gateway = payment_setup
    assert Settings.__dataclass_fields__["mode"].default == "embedded"
    key, _ = orders.seed("owner")
    result = orders.start(key, "owner")
    assert result["config"]["target"] == "lunixi-checkout-form"
    assert "redirect" not in result
    assert "allowedOrigin" not in next(iter(gateway.payments.values()))["data"]["metadata"]
