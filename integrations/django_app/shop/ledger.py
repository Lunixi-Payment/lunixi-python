"""Real ORM transaction adapter; order and inbox commit together."""

from __future__ import annotations

import hashlib
import hmac
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from django.db import transaction

from lunixi.commerce import CommerceError, Transaction

from .models import Attempt, Event, Order


class DjangoTransaction:
    def __init__(self, order: Order) -> None:
        self.order = order

    def load(self) -> Optional[dict[str, Any]]:
        attempt = Attempt.objects.filter(order=self.order).first()
        return attempt.payload if attempt is not None else None

    def save(self, record: dict[str, Any]) -> None:
        Attempt.objects.update_or_create(
            order=self.order,
            defaults={"payload": record, "payment_id": record.get("paymentId", "")},
        )

    def claim_event(self, merchant_id: str, event_id: str, payload_hash: str) -> bool:
        key = hashlib.sha256((merchant_id + "\0" + event_id).encode()).hexdigest()
        row, created = Event.objects.get_or_create(
            event_key=key, defaults={"payload_hash": payload_hash}
        )
        if not hmac.compare_digest(row.payload_hash, payload_hash):
            raise CommerceError("Verified event content collision.")
        return created


class DjangoLedger:
    @contextmanager
    def transaction(self, key: str) -> Iterator[Transaction]:
        # SQLite uses OPTIONS.transaction_mode=IMMEDIATE. PostgreSQL would use this native row lock.
        with transaction.atomic(durable=True):
            try:
                order = Order.objects.select_for_update().get(pk=key)
            except Order.DoesNotExist:
                raise CommerceError("A persisted native order is required.") from None
            yield DjangoTransaction(order)

    def find_payment(self, payment_id: str) -> Optional[str]:
        rows = list(
            Attempt.objects.filter(payment_id=payment_id).values_list("order_id", flat=True)[:2]
        )
        return str(rows[0]) if len(rows) == 1 else None
