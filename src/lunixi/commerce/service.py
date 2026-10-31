"""Durable checkout orchestration: reservations commit before network I/O."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Callable, Mapping, Optional

from ..client import LunixiClient
from ..payments import CreateIntent, IntentResult
from ..validation import amount_minor, identifier
from ..webhook.verifier import WebhookEvent
from .models import CommerceError, OrderSnapshot, PaymentDecision, evaluate
from .secret_box import SecretBox
from .store import LedgerStore, Transaction

Apply = Callable[[Transaction, OrderSnapshot, PaymentDecision], None]
_RANK = {
    "reserved": 0,
    "pending": 0,
    "review": 0,
    "failed": 1,
    "authorized": 2,
    "partially_captured": 3,
    "paid": 4,
    "partially_refunded": 5,
    "refunded": 6,
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class CheckoutService:
    def __init__(
        self,
        client: LunixiClient,
        store: LedgerStore,
        box: SecretBox,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not client.configuration().base_url.startswith("https://"):
            raise CommerceError("Checkout requires a trusted HTTPS gateway origin.")
        self.client = client
        self.store = store
        self.box = box
        self.clock = clock

    def _load(self, key: str) -> dict[str, Any]:
        with self.store.transaction(key) as tx:
            value = tx.load()
            if value is None:
                raise CommerceError("A durable reserved checkout is required.")
            return value

    def _window(self, created_at: Any) -> None:
        if (
            isinstance(created_at, bool)
            or not isinstance(created_at, (int, float))
            or not -300 <= self.clock() - created_at < 23 * 3600
        ):
            raise CommerceError(
                "Financial retry window expired; use authenticated reconciliation and operator review."
            )

    def start(
        self,
        key: str,
        order: OrderSnapshot,
        callback_url: str,
        *,
        hosted: bool = False,
        preauth: bool = False,
        locale: str = "en",
    ) -> IntentResult:
        metadata: dict[str, Any] = {"lunixiCommerce": {"fingerprint": order.fingerprint}}
        if hosted:
            metadata["allowedOrigin"] = "https://pay.lunixi.com"
        request = CreateIntent(
            order.amount, order.currency, order.order_id, callback_url, preauth, locale, metadata
        )
        digest = _hash(json.dumps(request.to_dict(), separators=(",", ":")))
        with self.store.transaction(key) as tx:
            record = tx.load()
            if record is None:
                record = {
                    "snapshot": order.to_dict(),
                    "requestHash": digest,
                    "key": "lunixi-" + secrets.token_hex(24),
                    "createdAt": self.clock(),
                    "state": "reserved",
                    "paymentId": "",
                }
                tx.save(record)
            elif record.get("requestHash") != digest:
                raise CommerceError(
                    "Order or checkout settings changed; reconcile the existing attempt."
                )
        if record.get("capturedAmount", 0) > 0 or record["state"] in (
            "authorized",
            "paid",
            "partially_captured",
            "partially_refunded",
            "refunded",
            "failed",
        ):
            raise CommerceError("Checkout already concluded; reconcile before another attempt.")
        if record["paymentId"] and record.get("token"):
            if self.clock() - record["createdAt"] >= 840:
                raise CommerceError("Checkout token expired; reconcile before another attempt.")
            return IntentResult(record["paymentId"], self.box.decrypt(record["token"], key))
        self._window(record.get("createdAt"))
        metadata["lunixiCommerce"]["attempt"] = _hash(record["key"])
        result = self.client.payments().create_intent(request, idempotency_key=record["key"])
        with self.store.transaction(key) as tx:
            current = tx.load()
            if (
                current is None
                or current["key"] != record["key"]
                or current["paymentId"] not in ("", result.payment_id)
            ):
                raise CommerceError("Concurrent checkout identity changed.")
            current["paymentId"] = result.payment_id
            current["token"] = self.box.encrypt(result.token, key)
            if current["state"] == "reserved":
                current["state"] = "pending"
            tx.save(current)
        return result

    def _evidence(
        self, record: dict[str, Any], candidate: Optional[str] = None
    ) -> tuple[PaymentDecision, Mapping[str, Any]]:
        payment_id = candidate or record["paymentId"]
        identifier(payment_id)
        response = self.client.payments().get(payment_id)
        payment = response.get("data", response)
        if not isinstance(payment, dict):
            raise CommerceError("Authenticated payment response is invalid.")
        ref = payment.get("split")
        split = (
            self.client.payments().get_split(ref["splitPaymentId"])
            if isinstance(ref, dict) and isinstance(ref.get("splitPaymentId"), str)
            else None
        )
        return evaluate(
            OrderSnapshot.from_dict(record["snapshot"]), payment_id, response, split
        ), payment

    def verify_webhook(self, raw: bytes, headers: Mapping[str, Any], secret: str) -> WebhookEvent:
        return self.client.webhooks(secret).verify(raw, headers)

    @staticmethod
    def event_payment_id(event: WebhookEvent) -> str:
        values = [
            event.data[k] for k in ("intentId", "paymentId", "paymentIntentId") if k in event.data
        ]
        if not values or any(not isinstance(v, str) or v != values[0] for v in values):
            raise CommerceError("Verified event payment identity is missing or conflicting.")
        return identifier(values[0])

    def webhook(
        self, raw: bytes, headers: Mapping[str, Any], secret: str, apply: Apply
    ) -> PaymentDecision:
        event = self.verify_webhook(raw, headers, secret)
        payment_id = self.event_payment_id(event)
        key = self.store.find_payment(payment_id)
        if key is None:
            candidate = event.data.get("orderId")
            if not isinstance(candidate, str) or not 1 <= len(candidate) <= 128:
                raise CommerceError("Verified webhook cannot locate a reserved order.")
            key = candidate
        return self.reconcile(key, apply, event=event)

    def reconcile(
        self, key: str, apply: Apply, *, event: Optional[WebhookEvent] = None
    ) -> PaymentDecision:
        record = self._load(key)
        candidate = record["paymentId"]
        if event is not None:
            if (
                event.raw_body_hash is None
                or not event.type
                or not event.type.startswith("payment.")
            ):
                raise CommerceError("A verified raw payment event is required.")
            candidate = self.event_payment_id(event)
            if record["paymentId"] and record["paymentId"] != candidate:
                raise CommerceError("Verified webhook does not match the bound payment.")
            if (
                event.data.get("orderId", record["snapshot"]["orderId"])
                != record["snapshot"]["orderId"]
            ):
                raise CommerceError("Verified webhook order does not match the reserved order.")
        if not candidate:
            raise CommerceError("Unbound recovery requires a verified payment event.")
        decision, payment = self._evidence(record, candidate)
        order = OrderSnapshot.from_dict(record["snapshot"])
        if not record["paymentId"]:
            metadata = payment.get("metadata")
            if not isinstance(metadata, dict) and isinstance(payment.get("metadataJson"), str):
                try:
                    metadata = json.loads(payment["metadataJson"])
                except ValueError:
                    metadata = None
            proof = metadata.get("lunixiCommerce", {}) if isinstance(metadata, dict) else {}
            if (
                event is None
                or proof.get("attempt") != _hash(record["key"])
                or proof.get("fingerprint") != order.fingerprint
            ):
                raise CommerceError("Unbound payment does not prove the original reserved attempt.")
        with self.store.transaction(key) as tx:
            current = tx.load()
            if (
                current is None
                or current["key"] != record["key"]
                or current["paymentId"] not in ("", decision.payment_id)
            ):
                raise CommerceError("Checkout changed during reconciliation.")
            current["paymentId"] = decision.payment_id
            if event is not None and not tx.claim_event(
                order.merchant_id, str(event.id), str(event.raw_body_hash)
            ):
                return self._stored(current)
            before = current.get("capturedAmount", 0)
            release = (
                current["state"] == "authorized"
                and decision.state == "failed"
                and decision.gateway_status in ("VOIDED", "EXPIRED")
            )
            stale = (
                decision.captured_amount < before
                or decision.refunded_amount < current.get("refundedAmount", 0)
                or (
                    _RANK.get(decision.state, 0) < _RANK.get(current["state"], 0)
                    and not release
                    and decision.captured_amount <= before
                )
            )
            if stale:
                return self._stored(current)
            # The idempotent native callback also revalidates the current native
            # snapshot/hold when settlement itself did not change.
            apply(tx, order, decision)
            for op in current.get("operations", {}).values():
                confirmed = (
                    (
                        op["action"] == "capture"
                        and decision.captured_amount >= op["initialCaptured"] + op["amount"]
                    )
                    or (
                        op["action"] == "refund"
                        and decision.refunded_amount >= op["initialRefunded"] + op["amount"]
                    )
                    or (
                        op["action"] == "void"
                        and decision.state == "failed"
                        and decision.gateway_status in ("VOIDED", "EXPIRED")
                        and decision.captured_amount == 0
                    )
                )
                if confirmed:
                    op["state"] = "confirmed"
            current.update(
                state=decision.state,
                chargedAmount=decision.charged_amount,
                capturedAmount=decision.captured_amount,
                refundedAmount=decision.refunded_amount,
                gatewayStatus=decision.gateway_status,
                splitId=decision.split_id,
            )
            tx.save(current)
        return decision

    @staticmethod
    def _stored(record: dict[str, Any]) -> PaymentDecision:
        return PaymentDecision(
            record["state"],
            record["paymentId"],
            record.get("chargedAmount", record["snapshot"]["amount"]),
            record.get("capturedAmount", 0),
            record.get("refundedAmount", 0),
            record.get("gatewayStatus", ""),
            record.get("splitId"),
        )

    def operation_status(self, key: str, operation_id: str) -> Optional[dict[str, Any]]:
        op = self._load(key).get("operations", {}).get(_hash(operation_id))
        return {k: v for k, v in op.items() if k != "key"} if op else None

    def mutate(
        self, key: str, operation_id: str, action: str, amount: Optional[int], apply: Apply
    ) -> PaymentDecision:
        if (
            not isinstance(operation_id, str)
            or not 1 <= len(operation_id) <= 191
            or action not in ("capture", "refund", "void")
            or (action == "void" and amount is not None)
        ):
            raise CommerceError("A stable operation ID and supported action are required.")
        if action != "void":
            amount_minor(amount)
        record = self._load(key)
        op_id = _hash(operation_id)
        op = record.get("operations", {}).get(op_id)
        if op is not None and (op["action"] != action or op["amount"] != amount):
            raise CommerceError("Operation ID was reused with different parameters.")
        if op is None:
            evidence, _ = self._evidence(record)
            invalid = (
                (
                    action == "refund"
                    and (
                        evidence.state not in ("paid", "partially_captured", "partially_refunded")
                        or amount is None
                        or amount > evidence.captured_amount - evidence.refunded_amount
                    )
                )
                or (
                    action == "capture"
                    and (
                        evidence.state not in ("authorized", "partially_captured")
                        or amount is None
                        or amount > evidence.charged_amount - evidence.captured_amount
                        or evidence.split_id is not None
                    )
                )
                or (
                    action == "void"
                    and (evidence.state != "authorized" or evidence.split_id is not None)
                )
            )
            if invalid:
                raise CommerceError("Authenticated balance/state does not permit this operation.")
            with self.store.transaction(key) as tx:
                current = tx.load()
                if current is None or current["key"] != record["key"]:
                    raise CommerceError("Checkout changed before operation reservation.")
                operations = current.setdefault("operations", {})
                op = operations.get(op_id)
                if op is not None:
                    if op["action"] != action or op["amount"] != amount:
                        raise CommerceError("Concurrent operation identity changed.")
                else:
                    if any(other["state"] != "confirmed" for other in operations.values()):
                        raise CommerceError("Retry or reconcile the unresolved operation first.")
                    op = {
                        "action": action,
                        "amount": amount,
                        "key": "lunixi-op-" + secrets.token_hex(24),
                        "state": "pending",
                        "createdAt": self.clock(),
                        "splitId": evidence.split_id,
                        "initialCaptured": evidence.captured_amount,
                        "initialRefunded": evidence.refunded_amount,
                    }
                    operations[op_id] = op
                    tx.save(current)
        try:
            if op["state"] != "confirmed":
                self._window(op.get("createdAt"))
                if action == "capture":
                    self.client.payments().capture(
                        record["paymentId"], amount_minor(amount), idempotency_key=op["key"]
                    )
                elif action == "refund":
                    method = (
                        self.client.payments().refund_split
                        if op["splitId"]
                        else self.client.payments().refund
                    )
                    method(
                        op["splitId"] or record["paymentId"],
                        amount_minor(amount),
                        idempotency_key=op["key"],
                    )
                else:
                    self.client.payments().void(record["paymentId"], idempotency_key=op["key"])
            return self.reconcile(key, apply)
        except Exception:
            with self.store.transaction(key) as tx:
                current = tx.load()
                if (
                    current is not None
                    and current["key"] == record["key"]
                    and op_id in current.get("operations", {})
                    and current["operations"][op_id]["state"] != "confirmed"
                ):
                    current["operations"][op_id]["state"] = "uncertain"
                    tx.save(current)
            raise
