from __future__ import annotations

import json
import re

import pytest

from tests.test_commerce import fresh_event


class Web:
    def __init__(self, kind, app):
        self.kind = kind
        if kind == "flask":
            self.client = app.test_client()
            self.orders = app.extensions["lunixi_orders"]
        else:
            from fastapi.testclient import TestClient

            self.client = TestClient(app, base_url="https://testserver", follow_redirects=False)
            self.orders = app.state.orders

    def get(self, path, **kwargs):
        return (
            self.client.get(path, base_url="https://testserver", **kwargs)
            if self.kind == "flask"
            else self.client.get(path, **kwargs)
        )

    def post(self, path, *, body=None, headers=None):
        if self.kind == "flask":
            return self.client.post(
                path, data=body, headers=headers or {}, base_url="https://testserver"
            )
        return self.client.post(path, content=body, headers=headers or {})

    def text(self, response):
        return response.get_data(as_text=True) if self.kind == "flask" else response.text

    def json(self, response):
        return response.get_json() if self.kind == "flask" else response.json()


@pytest.fixture(params=["flask", "fastapi"])
def web(request, payment_setup):
    orders, gateway = payment_setup
    if request.param == "flask":
        from integrations.flask_app import create_app
    else:
        from integrations.fastapi_app import create_app
    return Web(request.param, create_app(orders.settings, orders.service.client)), gateway


def csrf(web, key):
    page = web.get("/checkout/" + key)
    assert page.status_code == 200
    match = re.search(r"const config=(.*?);const button", web.text(page))
    return json.loads(match.group(1))["csrf"]


def test_native_secure_cookie_csrf_ownership_and_host_guard(web):
    web, gateway = web
    key, token = web.orders.seed("owner")
    assert web.get("/checkout/" + key).status_code == 403
    response = web.get("/claim/" + token)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert web.get("/claim/" + token).status_code == 403
    nonce = csrf(web, key)
    assert web.post("/checkout/" + key).status_code == 409
    other, _ = web.orders.seed("other")
    assert web.post("/checkout/" + other, headers={"X-CSRF-Token": nonce}).status_code == 409
    assert gateway.calls == []
    page = web.get("/checkout/" + key)
    assert "https://cdn.lunixi.com" in page.headers["Content-Security-Policy"]
    assert page.headers["Cache-Control"] == "no-store"
    assert web.get("/checkout/" + key, headers={"host": "evil.example"}).status_code == 400


def test_native_checkout_browser_return_is_not_payment_and_signed_webhook_is(web):
    web, gateway = web
    key, token = web.orders.seed("owner")
    web.get("/claim/" + token)
    nonce = csrf(web, key)
    response = web.post("/checkout/" + key, headers={"X-CSRF-Token": nonce})
    assert response.status_code == 200
    assert web.json(response)["redirect"].startswith("https://pay.lunixi.com/payment/")
    assert "PRIVATE KEY" not in web.text(response)
    assert web.post("/return/" + key, body=b"status=success&success=true").status_code == 303
    assert web.orders.owned(key, "owner")["state"] == "pending"
    assert web.json(web.get("/status/" + key))["complete"] is False
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, key)
    assert web.post("/webhook", body=raw + b" ", headers=headers).status_code == 503
    assert web.post("/webhook", body=raw, headers=headers).status_code == 204
    assert web.post("/webhook", body=raw, headers=headers).status_code == 204
    assert web.orders.complete(key, "owner")
    connection = web.orders.store.connect()
    assert connection.execute("SELECT quantity FROM sample_stock").fetchone()[0] == 99
    assert connection.execute("SELECT COUNT(*) FROM lunixi_event").fetchone()[0] == 1
    connection.close()


def test_native_callback_rollback_retries_and_manual_hold(web, monkeypatch):
    web, gateway = web
    key, token = web.orders.seed("owner", hold=True)
    web.get("/claim/" + token)
    web.orders.start(key, "owner")
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, key)
    original = web.orders.apply

    def crash(tx, snapshot, decision):
        original(tx, snapshot, decision)
        raise RuntimeError("Synthetic failure after native write")

    monkeypatch.setattr(web.orders, "apply", crash)
    assert web.post("/webhook", body=raw, headers=headers).status_code == 503
    assert web.orders.owned(key, "owner")["state"] == "pending"
    monkeypatch.setattr(web.orders, "apply", original)
    assert web.post("/webhook", body=raw, headers=headers).status_code == 204
    assert web.orders.owned(key, "owner")["state"] == "paid"
    assert not web.orders.complete(key, "owner")
    connection = web.orders.store.connect()
    assert connection.execute("SELECT quantity FROM sample_stock").fetchone()[0] == 100
    assert connection.execute("SELECT COUNT(*) FROM sample_outbox").fetchone()[0] == 1
    connection.close()
    assert web.post("/webhook", body=b"x" * (1024 * 1024 + 1)).status_code == 413
