import base64
from dataclasses import replace

import pytest

from integrations.common import Settings, approved_form_action_origins
from lunixi.commerce import CommerceError


@pytest.mark.parametrize(
    "origin",
    [
        "https:",
        "https://*.example.com",
        "https://user@example.com",
        "http://provider.example",
        "https://provider.example/",
        "https://provider.example/post",
        "https://provider.example?x=1",
        "https://provider.example#x",
        "https://provider.example\r\nform-action https:",
        "https://provider.example;form-action https:",
        "https://provider.example\\evil",
        "https://provider.example:0",
        "https://provider.example:65536",
        "https://provider.example,",
    ],
)
def test_operator_form_origin_cannot_widen_csp(origin, payment_setup):
    orders, gateway = payment_setup
    with pytest.raises(CommerceError):
        approved_form_action_origins("https://api-gateway.lunixi.com", origin)
    with pytest.raises(CommerceError):
        replace(orders.settings, form_action_origins=(origin,)).validate()
    assert gateway.calls == []


def test_explicit_operator_origins_keep_https_port_and_deduplicate():
    assert approved_form_action_origins(
        "https://api-gateway.lunixi.com",
        "https://provider.example:8443,https://api-gateway.lunixi.com",
    ) == ("https://api-gateway.lunixi.com", "https://provider.example:8443")


def test_server_environment_controls_origins_and_rejects_injection(payment_setup, monkeypatch):
    orders, gateway = payment_setup
    settings = orders.settings
    for name, value in {
        "LUNIXI_PUBLIC_ORIGIN": settings.public_origin,
        "LUNIXI_MERCHANT_ID": settings.merchant_id,
        "LUNIXI_WEBHOOK_SECRET": settings.webhook_secret,
        "LUNIXI_SESSION_SECRET": settings.session_secret,
        "LUNIXI_ENCRYPTION_KEY": base64.b64encode(settings.encryption_key).decode(),
        "LUNIXI_DATABASE": settings.database,
        "LUNIXI_GATEWAY_ORIGIN": "https://gateway.example:8443",
        "LUNIXI_FORM_ACTION_ORIGINS": "https://provider.example",
    }.items():
        monkeypatch.setenv(name, value)
    assert Settings.from_env().form_action_origins == (
        "https://gateway.example:8443",
        "https://provider.example",
    )
    monkeypatch.setenv("LUNIXI_FORM_ACTION_ORIGINS", "https://*.example")
    with pytest.raises(CommerceError):
        Settings.from_env()
    assert gateway.calls == []
