from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client

from integrations.django_app.shop import views
from integrations.django_app.shop.models import Event, Order, Outbox, Stock
from integrations.django_app.shop.service import DjangoOrders
from tests.test_commerce import fresh_event

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def native(payment_setup, monkeypatch):
    sample, gateway = payment_setup
    orders = DjangoOrders(sample.settings, sample.service.client)
    monkeypatch.setattr(views, "get_orders", lambda: orders)
    user = get_user_model().objects.create_user(
        username="owner", password="synthetic-password-used-only-in-tests"
    )
    other = get_user_model().objects.create_user(
        username="other", password="synthetic-password-used-only-in-tests"
    )
    stock = Stock.objects.create(sku="sample", quantity=10)
    order = Order.objects.create(owner=user, stock=stock, amount=1990, currency="TRY")
    client = Client(enforce_csrf_checks=True)
    return orders, gateway, user, other, order, client


def csrf(client, key):
    response = client.get("/checkout/" + key, secure=True)
    assert response.status_code == 200
    data = json.loads(
        re.search(r"const config=(.*?);const button", response.content.decode()).group(1)
    )
    return data["csrf"]


def test_native_login_csrf_and_customer_ownership(native):
    orders, gateway, user, other, order, client = native
    assert client.get("/checkout/" + order.pk, secure=True).status_code == 403
    client.force_login(other)
    assert client.get("/checkout/" + order.pk, secure=True).status_code == 403
    client.force_login(user)
    token = csrf(client, order.pk)
    assert (
        client.post(
            "/checkout/" + order.pk, secure=True, HTTP_ORIGIN="https://testserver"
        ).status_code
        == 403
    )
    response = client.post(
        "/checkout/" + order.pk,
        secure=True,
        HTTP_X_CSRF_TOKEN=token,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 200
    assert response.json()["config"]["type"] == "payment"
    assert "redirect" not in response.json()
    assert "synthetic_webhook_secret" not in response.content.decode()
    assert "PRIVATE KEY" not in response.content.decode()


def test_native_browser_return_tamper_signed_replay_and_stock(native):
    orders, gateway, user, other, order, client = native
    client.force_login(user)
    token = csrf(client, order.pk)
    client.post(
        "/checkout/" + order.pk,
        secure=True,
        HTTP_X_CSRF_TOKEN=token,
        HTTP_ORIGIN="https://testserver",
    )
    client.post("/return/" + order.pk, {"status": "success", "success": "true"}, secure=True)
    order.refresh_from_db()
    assert order.state == "pending"
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, order.pk)
    native_headers = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in headers.items()}
    assert (
        client.post(
            "/webhook",
            data=raw + b" ",
            content_type="application/json",
            secure=True,
            **native_headers,
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/webhook", data=raw, content_type="application/json", secure=True, **native_headers
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/webhook", data=raw, content_type="application/json", secure=True, **native_headers
        ).status_code
        == 204
    )
    assert orders.complete(order.pk, user)
    assert Stock.objects.get(pk="sample").quantity == 9
    assert Event.objects.count() == 1
    assert Outbox.objects.count() == 1
    Order.objects.filter(pk=order.pk).update(amount=2990)
    assert not orders.complete(order.pk, user)


def test_native_atomic_rollback_concurrency_and_fulfillment_hold(native, monkeypatch):
    orders, gateway, user, other, order, client = native
    Order.objects.filter(pk=order.pk).update(fulfillment_hold=True)
    orders.start(order.pk, user)
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, order.pk)
    original = orders.apply

    def crash(tx, snapshot, decision):
        original(tx, snapshot, decision)
        raise RuntimeError("Synthetic failure after ORM stock/order writes")

    with pytest.raises(RuntimeError):
        orders.service.webhook(raw, headers, orders.settings.webhook_secret, crash)
    order.refresh_from_db()
    assert order.state == "pending"
    assert Event.objects.count() == 0
    assert Outbox.objects.count() == 0

    def consume(_):
        close_old_connections()
        try:
            orders.service.webhook(raw, headers, orders.settings.webhook_secret, orders.apply)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(consume, range(6)))
    order.refresh_from_db()
    assert order.state == "paid"
    assert not orders.complete(order.pk, user)
    assert Stock.objects.get(pk="sample").quantity == 10
    assert Event.objects.count() == 1
    assert Outbox.objects.count() == 1


def test_optional_hosted_uses_exact_backend_url_and_keeps_original_attempt(native):
    orders, gateway, user, other, order, client = native
    orders.settings = replace(orders.settings, mode="hosted")
    client.force_login(user)
    token = csrf(client, order.pk)
    response = client.post(
        "/checkout/" + order.pk,
        secure=True,
        HTTP_X_CSRF_TOKEN=token,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 200
    assert response.json() == {"redirect": gateway.payment_page_url}
    record = orders.service._load(order.pk)
    assert gateway.payment_page_url not in record["paymentPageUrl"]
    calls = len(gateway.calls)
    orders.settings = replace(orders.settings, mode="embedded")
    assert (
        client.post(
            "/checkout/" + order.pk,
            secure=True,
            HTTP_X_CSRF_TOKEN=token,
            HTTP_ORIGIN="https://testserver",
        ).status_code
        == 409
    )
    assert orders.service._load(order.pk)["key"] == record["key"]
    assert len(gateway.calls) == calls


def test_rendered_checkout_csp_default_and_operator_origins_fail_closed(native):
    orders, gateway, user, other, order, client = native
    client.force_login(user)
    response = client.get("/checkout/" + order.pk, secure=True)
    assert response.status_code == 200
    policy = response["Content-Security-Policy"]
    assert "form-action 'self' https://api-gateway.lunixi.com" in policy
    nonce = re.search(r'<script[^>]*nonce="([^"]+)"', response.content.decode()).group(1)
    assert "'nonce-" + nonce + "'" in policy
    assert response["Referrer-Policy"] == "no-referrer"
    orders.settings = replace(
        orders.settings,
        form_action_origins=("https://api-gateway.lunixi.com", "https://provider.example:8443"),
    )
    response = client.get("/checkout/" + order.pk, secure=True)
    assert response.status_code == 200
    assert (
        "form-action 'self' https://api-gateway.lunixi.com https://provider.example:8443"
        in response["Content-Security-Policy"]
    )
    orders.settings = replace(
        orders.settings, form_action_origins=("https://safe.example;form-action https:",)
    )
    response = client.get("/checkout/" + order.pk, secure=True)
    assert response.status_code == 403
    assert "https://safe.example" not in response.content.decode()
    assert "https://cdn.lunixi.com" not in response.content.decode()
    assert gateway.calls == []
