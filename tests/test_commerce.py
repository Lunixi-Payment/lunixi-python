from __future__ import annotations

import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from integrations.common import Orders
from lunixi import ApiError, ConfigurationError, CreateIntent, WebhookVerificationError
from lunixi.commerce import (
    CommerceError,
    OrderSnapshot,
    SecretBox,
    evaluate,
    minor_units,
)
from lunixi.http.transport import serialize_body


def fresh_event(
    payment_id,
    key,
    secret="synthetic_webhook_secret_0123456789",
    event_id="evt_one",
    kind="payment.captured",
):
    raw = json.dumps(
        {"id": event_id, "type": kind, "data": {"intentId": payment_id, "orderId": key}},
        separators=(",", ":"),
    ).encode()
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sig = hmac.new(
        secret.encode(), event_id.encode() + b"." + stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return raw, {
        "x-lunixi-event-id": event_id,
        "x-lunixi-event-type": kind,
        "x-lunixi-signature-timestamp": stamp,
        "x-lunixi-signature": "v2=" + sig,
    }


def test_js_serialization_numeric_keys_and_ecmascript_numbers():
    assert (
        serialize_body({"z": {"2024": "x", "4": "y", "a": -0.0}, "2": 1e20, "1": 1e-7})
        == '{"1":1e-7,"2":100000000000000000000,"z":{"4":"y","2024":"x","a":0}}'
    )
    with pytest.raises(ConfigurationError):
        serialize_body({"n": 9007199254740992})


@pytest.mark.parametrize("value", [True, 0, -1, 1.01, "100", 9007199254740992])
def test_money_rejected_before_network(payment_setup, value):
    orders, gateway = payment_setup
    before = len(gateway.calls)
    with pytest.raises(ConfigurationError):
        orders.service.client.payments().create_intent(
            CreateIntent(value, "TRY", "order"), idempotency_key="stable-key"
        )
    assert len(gateway.calls) == before


def test_exact_decimal_and_currency():
    assert minor_units("19.90") == 1990
    assert minor_units("1", "JPY") == 1
    assert minor_units("1.001", "KWD") == 1001
    for value in ("1e3", "1.001", "nan"):
        with pytest.raises(ConfigurationError):
            minor_units(value)


def test_signed_replay_collision_native_rollback_and_encrypted_token(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("customer")
    orders.start(key, "customer")
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, key)
    original = orders.apply

    def crash(tx, snapshot, decision):
        original(tx, snapshot, decision)
        raise CommerceError("Synthetic native failure after stock write")

    with pytest.raises(CommerceError):
        orders.service.webhook(raw, headers, orders.settings.webhook_secret, crash)
    assert orders.owned(key, "customer")["state"] == "pending"
    connection = orders.store.connect()
    assert connection.execute("SELECT COUNT(*) FROM lunixi_event").fetchone()[0] == 0
    connection.close()
    orders.webhook(raw, headers)
    orders.webhook(raw, headers)
    assert orders.complete(key, "customer")
    with orders.store.transaction(key) as tx:
        record = tx.load()
    assert "synthetic_browser_token" not in record["token"]
    assert "synthetic_browser_token" not in repr(SecretBox(b"t" * 32))
    bad, bad_headers = fresh_event(payment_id, key, event_id="evt_one", kind="payment.failed")
    with pytest.raises(CommerceError):
        orders.webhook(bad, bad_headers)
    connection = orders.store.connect()
    assert connection.execute("SELECT quantity FROM sample_stock").fetchone()[0] == 99
    assert connection.execute("SELECT COUNT(*) FROM sample_outbox").fetchone()[0] == 1
    connection.close()


def test_concurrent_store_instances_apply_once(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("customer")
    orders.start(key, "customer")
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, key)

    def consume(_):
        instance = Orders(orders.settings, orders.service.client)
        instance.webhook(raw, headers)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(consume, range(12)))
    connection = orders.store.connect()
    assert connection.execute("SELECT quantity FROM sample_stock").fetchone()[0] == 99
    assert connection.execute("SELECT COUNT(*) FROM lunixi_event").fetchone()[0] == 1
    connection.close()


def test_ownership_tamper_and_changed_snapshot(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    with pytest.raises(CommerceError):
        orders.start(key, "other")
    assert gateway.calls == []
    orders.start(key, "owner")
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    raw, headers = fresh_event(payment_id, key)
    with pytest.raises(WebhookVerificationError):
        orders.webhook(raw + b" ", headers)
    orders.webhook(raw, headers)
    connection = orders.store.connect()
    connection.execute("UPDATE sample_order SET amount=2990 WHERE id=?", (key,))
    connection.close()
    assert not orders.complete(key, "owner")
    with pytest.raises(CommerceError):
        orders.service.reconcile(key, orders.apply)


def test_lost_response_signed_recovery_and_no_rebinding(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    gateway.lost_create = True
    with pytest.raises(ApiError):
        orders.start(key, "owner")
    payment_id = next(iter(gateway.payments))
    gateway.capture(payment_id)
    with pytest.raises(CommerceError):
        orders.service.reconcile(key, orders.apply)
    raw, headers = fresh_event(payment_id, key)
    orders.webhook(raw, headers)
    assert orders.complete(key, "owner")
    raw, headers = fresh_event("pi_conflict", key, event_id="evt_conflict")
    with pytest.raises(CommerceError):
        orders.webhook(raw, headers)


def test_mutation_delayed_confirmation_partial_refund_and_void(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    snapshot = OrderSnapshot("merchant_test", key, 1990, "TRY")
    intent = orders.service.start(key, snapshot, "https://testserver/return/" + key, preauth=True)
    assert orders.service.reconcile(key, orders.apply).state == "authorized"
    gateway.defer = True
    orders.service.mutate(key, "capture-operation", "capture", 1000, orders.apply)
    assert orders.service.operation_status(key, "capture-operation")["state"] == "pending"
    with pytest.raises(CommerceError):
        orders.service.mutate(key, "another-operation", "capture", 990, orders.apply)
    gateway.payments[intent.payment_id]["data"]["status"] = "PARTIALLY_CAPTURED"
    gateway.payments[intent.payment_id]["details"]["capturedAmount"] = 1000
    orders.service.reconcile(key, orders.apply)
    assert orders.service.operation_status(key, "capture-operation")["state"] == "confirmed"
    assert not orders.complete(key, "owner")
    gateway.defer = False
    orders.service.mutate(key, "capture-remainder", "capture", 990, orders.apply)
    assert orders.complete(key, "owner")
    orders.service.mutate(key, "refund-part", "refund", 500, orders.apply)
    assert orders.service.operation_status(key, "refund-part")["state"] == "confirmed"
    with pytest.raises(CommerceError):
        orders.service.mutate(key, "overrefund", "refund", 1491, orders.apply)
    orders.service.mutate(key, "refund-rest", "refund", 1490, orders.apply)
    assert not orders.complete(key, "owner")
    connection = orders.store.connect()
    assert connection.execute("SELECT quantity FROM sample_stock").fetchone()[0] == 100
    connection.close()


def test_age_fence_prevents_new_charge_after_gateway_key_retention(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    gateway.lost_create = True
    with pytest.raises(ApiError):
        orders.start(key, "owner")
    before = len(gateway.calls)
    orders.service.clock = lambda: time.time() + 23 * 3600 + 1
    with pytest.raises(CommerceError, match="window expired"):
        orders.start(key, "owner")
    assert len(gateway.calls) == before


def test_failed_without_certainty_is_review_and_does_not_complete(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    orders.start(key, "owner")
    payment_id = next(iter(gateway.payments))
    gateway.payments[payment_id]["data"]["status"] = "FAILED"
    assert orders.service.reconcile(key, orders.apply).state == "review"
    assert not orders.complete(key, "owner")


def test_fee_and_split_parent_require_complete_balanced_evidence():
    order = OrderSnapshot("merchant_test", "order", 1990, "TRY")
    p = {
        "id": "pi_parent",
        "merchantId": "merchant_test",
        "orderId": "order",
        "currency": "TRY",
        "amount": 2090,
        "status": "CAPTURED",
        "metadata": {"lunixiCommerce": {"fingerprint": order.fingerprint}},
    }
    assert evaluate(
        order, "pi_parent", {"data": p, "details": {"capturedAmount": 2090, "refundedAmount": 0}}
    ).paid
    p["metadata"] = {}
    with pytest.raises(CommerceError):
        evaluate(
            order,
            "pi_parent",
            {"data": p, "details": {"capturedAmount": 2090, "refundedAmount": 0}},
        )
    p.update(
        amount=1990,
        status="SETTLED_BY_SPLIT",
        split={"role": "PARENT", "splitPaymentId": "split_one"},
    )
    split = {
        "data": {
            "id": "split_one",
            "parentPaymentId": "pi_parent",
            "currency": "TRY",
            "orderId": "order",
            "status": "COMPLETED",
            "needsReconciliation": False,
            "aggregate": {
                "amountsBalanced": True,
                "totalAmount": 1990,
                "legsAmount": 1990,
                "capturedAmount": 1990,
                "compensatedAmount": 0,
                "authorizedAmount": 0,
            },
        }
    }
    assert evaluate(order, "pi_parent", {"data": p}, split).paid
    split["data"]["status"] = "RECONCILIATION_REQUIRED"
    assert not evaluate(order, "pi_parent", {"data": p}, split).paid


def test_void_requires_authenticated_release_and_does_not_fulfill(payment_setup):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    result = orders.service.start(
        key,
        OrderSnapshot("merchant_test", key, 1990, "TRY"),
        "https://testserver/return/" + key,
        preauth=True,
    )
    orders.service.reconcile(key, orders.apply)
    decision = orders.service.mutate(key, "void-operation", "void", None, orders.apply)
    assert decision.state == "failed"
    assert orders.service.operation_status(key, "void-operation")["state"] == "confirmed"
    assert not orders.complete(key, "owner")
    assert gateway.payments[result.payment_id]["data"]["status"] == "VOIDED"


def test_lost_mutation_confirms_by_get_and_expired_unconfirmed_operation_is_not_replayed(
    payment_setup,
):
    orders, gateway = payment_setup
    key, _ = orders.seed("owner")
    orders.service.start(
        key,
        OrderSnapshot("merchant_test", key, 1990, "TRY"),
        "https://testserver/return/" + key,
        preauth=True,
    )
    gateway.lost_mutation = True
    with pytest.raises(ApiError):
        orders.service.mutate(key, "lost-capture", "capture", 1990, orders.apply)
    assert orders.service.operation_status(key, "lost-capture")["state"] == "uncertain"
    orders.service.clock = lambda: time.time() + 24 * 3600
    calls = len(gateway.calls)
    with pytest.raises(CommerceError, match="window expired"):
        orders.service.mutate(key, "lost-capture", "capture", 1990, orders.apply)
    assert len(gateway.calls) == calls
    assert orders.service.reconcile(key, orders.apply).paid
    assert orders.service.operation_status(key, "lost-capture")["state"] == "confirmed"


def test_unicode_customer_identity_uses_persisted_ownership(payment_setup):
    orders, gateway = payment_setup
    key, token = orders.seed("müşteri_42")
    claimed, owner = orders.claim(token)
    assert claimed == key and owner == "müşteri_42"
    assert orders.owned(key, owner)["owner"] == owner
    assert not orders.complete(key, owner)
    assert gateway.calls == []
