"""Typed read models for the fraud responses.

Each one wraps the decoded payload and exposes the fields an integration acts
on, keeping :attr:`raw` available for everything else. Reading through an
object rather than a dict is what makes a missing or renamed field a visible
failure instead of a ``KeyError`` three layers away.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from .taxonomy import Decision

__all__ = ["FraudDecision", "EventResult", "EventBatchResult"]


class FraudDecision:
    """The answer from the decision endpoint.

    Attributes:
        decision: ``allow`` / ``review`` / ``block`` / ``force_3d``. See
            :class:`~lunixi.fraud.taxonomy.Decision`; ``force_3d`` asks you to
            re-run with 3-D Secure and is not a refusal.
        risk_score: Numeric score when the engine produced one.
        reasons: Reason codes behind the decision.
        trace_id: Identifier of the stored decision log — the value you pass
            to :meth:`~lunixi.fraud.fraud_client.FraudDecisionsClient.get`.
        raw: The whole decoded payload.
    """

    __slots__ = ("decision", "risk_score", "reasons", "trace_id", "decision_request_id", "raw")

    def __init__(self, payload: Any) -> None:
        data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
        self.decision: Optional[str] = _string(data, "decision")
        self.risk_score: Optional[float] = _number(data, "riskScore", "score")
        self.reasons: List[str] = _string_list(data, "reasons", "reasonCodes")
        self.trace_id: Optional[str] = _string(data, "traceId")
        self.decision_request_id: Optional[str] = _string(data, "decisionRequestId")
        self.raw: Mapping[str, Any] = data

    @property
    def allowed(self) -> bool:
        """True only for ``allow``.

        ⚠️ Not the inverse of :attr:`blocked`: ``review`` and ``force_3d`` are
        neither allowed nor blocked, and collapsing them into a boolean is how
        a force-3D decision ends up silently approved.
        """
        return self.decision == Decision.ALLOW

    @property
    def blocked(self) -> bool:
        """True only for ``block``."""
        return self.decision == Decision.BLOCK

    @property
    def requires_three_d(self) -> bool:
        """True for ``force_3d`` — re-run the payment with 3-D Secure."""
        return self.decision == Decision.FORCE_3D

    @property
    def requires_review(self) -> bool:
        """True for ``review`` — hold the transaction for a human decision."""
        return self.decision == Decision.REVIEW

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return f"FraudDecision(decision={self.decision!r}, trace_id={self.trace_id!r})"


class EventResult:
    """The result of recording one transaction event.

    Attributes:
        event_id: The ``event_id`` you sent.
        row_id: Id of the stored row, and ``None`` when the event was
            deduplicated. Branch on :attr:`deduplicated`, not on the absence of
            this id.
        deduplicated: True when an event with this ``event_id`` already
            existed. Retrying with the same id is therefore safe.
        matched_flow_count: How many published flows matched this event and
            ran.
        error: The validation message for THIS event inside a batch response.
            A batch answers 200 even when individual events were rejected, so
            this is the only place a per-event failure is visible.
    """

    __slots__ = ("event_id", "row_id", "deduplicated", "matched_flow_count", "error", "raw")

    def __init__(self, payload: Any) -> None:
        data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
        self.event_id: Optional[str] = _string(data, "eventId")
        self.row_id: Optional[str] = _string(data, "id")
        self.deduplicated: bool = bool(data.get("deduplicated", False))
        self.matched_flow_count: Optional[int] = _integer(data, "matchedFlowCount")
        self.error: Optional[str] = _string(data, "error")
        self.raw: Mapping[str, Any] = data

    @property
    def failed(self) -> bool:
        """True when this event was rejected."""
        return self.error is not None

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"EventResult(event_id={self.event_id!r}, deduplicated={self.deduplicated}, "
            f"failed={self.failed})"
        )


class EventBatchResult:
    """The result of a batch ingest call.

    🔴 A BATCH CAN SUCCEED PARTIALLY. The endpoint answers 200 and keeps
    processing the remaining events when one of them fails validation, so the
    HTTP status alone never proves the batch landed. :attr:`failed` and
    :meth:`failures` are the fields to check — an integration that reads only
    the status code loses events silently.

    Attributes:
        total: Events the gateway received.
        inserted: Events stored as new rows.
        deduplicated: Events that already existed.
        failed: Events rejected by validation.
        results: Per-event results, in the order sent.
    """

    __slots__ = ("total", "inserted", "deduplicated", "failed", "results", "raw")

    def __init__(self, payload: Any) -> None:
        data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
        rows = data.get("results")
        self.total: int = _integer(data, "total") or 0
        self.inserted: int = _integer(data, "inserted") or 0
        self.deduplicated: int = _integer(data, "deduplicated") or 0
        self.failed: int = _integer(data, "failed") or 0
        self.results: List[EventResult] = [
            EventResult(row) for row in rows if isinstance(row, Mapping)
        ] if isinstance(rows, list) else []
        self.raw: Mapping[str, Any] = data

    def failures(self) -> List[EventResult]:
        """Only the rejected events.

        Correct the body and resend them with the SAME ``event_id``: the
        gateway deduplicates, so a resend cannot double-count an event that
        did land.
        """
        return [result for result in self.results if result.failed]

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"EventBatchResult(total={self.total}, inserted={self.inserted}, "
            f"deduplicated={self.deduplicated}, failed={self.failed})"
        )


def _string(data: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value != "":
            return value
    return None


def _integer(data: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _number(data: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _string_list(data: Mapping[str, Any], *keys: str) -> List[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
    return []
