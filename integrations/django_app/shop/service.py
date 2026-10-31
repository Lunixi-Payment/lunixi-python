"""One SDK and native service per process; no network during a DB transaction."""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache

from django.db.models import F

from integrations.common import Settings, sdk_from_env
from lunixi import LunixiClient
from lunixi.commerce import (
    CheckoutService,
    CommerceError,
    OrderSnapshot,
    PaymentDecision,
    SecretBox,
    Transaction,
)

from .ledger import DjangoLedger, DjangoTransaction
from .models import Order, Outbox, Stock


class DjangoOrders:
    def __init__(self, settings: Settings, client: LunixiClient) -> None:
        self.settings = settings
        self.store = DjangoLedger()
        self.service = CheckoutService(client, self.store, SecretBox(settings.encryption_key))

    def owned(self, key: str, user) -> Order:
        if not user.is_authenticated:
            raise CommerceError("Authenticated order ownership is required.")
        try:
            return Order.objects.get(pk=key, owner=user)
        except Order.DoesNotExist:
            raise CommerceError("Authenticated order ownership is required.") from None

    def start(self, key: str, user):
        order = self.owned(key, user)
        snapshot = OrderSnapshot(self.settings.merchant_id, key, order.amount, order.currency)
        result = self.service.start(
            key,
            snapshot,
            self.settings.public_origin + "/return/" + key,
            hosted=self.settings.mode == "hosted",
            preauth=self.settings.preauth,
            locale=self.settings.locale,
        )
        return (
            {"redirect": result.hosted_url}
            if self.settings.mode == "hosted"
            else {"config": result.browser_config()}
        )

    def apply(self, tx: Transaction, snapshot: OrderSnapshot, decision: PaymentDecision) -> None:
        if not isinstance(tx, DjangoTransaction):
            raise CommerceError("Native order and ledger must share the Django transaction.")
        order = tx.order
        if snapshot != OrderSnapshot(
            self.settings.merchant_id, str(order.pk), order.amount, order.currency
        ):
            raise CommerceError("Native order changed after reservation.")
        if decision.paid and not order.fulfillment_hold and not order.stock_applied:
            changed = Stock.objects.filter(pk=order.stock_id, quantity__gt=0).update(
                quantity=F("quantity") - 1
            )
            if changed != 1:
                raise CommerceError("Native stock unavailable; hold for review.")
            order.stock_applied = True
        if decision.state == "refunded" and order.stock_applied:
            Stock.objects.filter(pk=order.stock_id).update(quantity=F("quantity") + 1)
            order.stock_applied = False
        order.state = decision.state
        order.captured = decision.captured_amount
        order.refunded = decision.refunded_amount
        order.save(update_fields=["state", "captured", "refunded", "stock_applied"])
        event_hash = hashlib.sha256(
            (str(order.pk) + json.dumps(decision.to_dict(), sort_keys=True)).encode()
        ).hexdigest()
        Outbox.objects.get_or_create(event_hash=event_hash, defaults={"order": order})

    def complete(self, key: str, user) -> bool:
        self.owned(key, user)
        with self.store.transaction(key) as tx:
            if not isinstance(tx, DjangoTransaction):
                raise CommerceError("Native Django transaction is required.")
            order = tx.order
            record = tx.load()
            return (
                order.owner_id == user.pk
                and record is not None
                and record["snapshot"]
                == OrderSnapshot(
                    self.settings.merchant_id, key, order.amount, order.currency
                ).to_dict()
                and order.state in ("paid", "partially_refunded")
                and order.stock_applied
                and not order.fulfillment_hold
            )

    def status(self, key: str, user):
        self.owned(key, user)
        now = int(time.time())
        if Order.objects.filter(pk=key, next_poll__lte=now).update(next_poll=now + 15):
            self.service.reconcile(key, self.apply)
        return {"complete": self.complete(key, user)}


@lru_cache(maxsize=1)
def get_orders() -> DjangoOrders:
    return DjangoOrders(Settings.from_env(), sdk_from_env())
