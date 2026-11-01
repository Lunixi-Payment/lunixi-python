"""Results of the physical POS write calls that carry an Idempotency-Key."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

__all__ = ["PhysicalPosPaymentWriteResult", "PhysicalPosWriteResult"]


@dataclass(frozen=True)
class PhysicalPosPaymentWriteResult:
    """Answer of ``create_payment``, ``create_reversal`` and ``cancel_payment``.

    Attributes:
        payment: The payment view (for a reversal, the new child payment).
        replayed: ``True`` when the same key and body were seen before; the
            payment is then its CURRENT state, not a copy of the first answer.
        status_code: 202 for a new payment or reversal (accepted — the outcome
            follows by webhook or ``get_payment``), 200 for a replay and for
            every cancel. A 202 never means "paid".
        idempotency_key: The key sent. Keep it with your order: an uncertain
            retry must reuse it.
    """

    payment: Dict[str, Any] = field(repr=False)
    replayed: bool
    status_code: int
    idempotency_key: Optional[str]

    @property
    def accepted(self) -> bool:
        """``True`` for a newly accepted payment or reversal (HTTP 202)."""
        return self.status_code == 202


@dataclass(frozen=True)
class PhysicalPosWriteResult:
    """Answer of a management write that carries an Idempotency-Key.

    Attributes:
        data: The route's payload, unchanged (``{"store": …}``,
            ``{"device": …, "closedAssignment": …}`` …). ``result["store"]``
            reads it directly.
        replayed: ``True`` when the same key and body were seen before.
        status_code: 201 for a created record, 200 for a replay or a state
            change.
        idempotency_key: The key sent.
    """

    data: Dict[str, Any] = field(repr=False)
    replayed: bool
    status_code: int
    idempotency_key: str

    def __getitem__(self, name: str) -> Any:
        return self.data[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.data.get(name, default)
