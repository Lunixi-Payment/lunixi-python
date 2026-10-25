"""The customer-facing fraud surface.

🔴 THIS SURFACE IS EXACTLY FIVE ROUTES. They are the documented machine
surface, and nothing else belongs here:

===========================================  ==================================
``POST /api/v1/fraud/decisions/evaluate``     :meth:`FraudClient.evaluate`
``GET  /api/v1/fraud/decision-logs``          :meth:`FraudDecisionsClient.list`
``GET  /api/v1/fraud/decision-logs/{id}``     :meth:`FraudDecisionsClient.get`
``POST /api/v1/fraud/events/transactions``    :meth:`FraudEventsClient.record`
``POST .../events/transactions/batch``        :meth:`FraudEventsClient.record_batch`
===========================================  ==================================

The console's own routes are NOT a customer surface. They are not published
here, they carry no stability guarantee, and an integration built on them
breaks without notice.

⚠️ THE ``/api/v1`` PREFIX IS PART OF EVERY PATH. The gateway applies it as a
global prefix and the fraud routes are not excluded from it; a path written
without the prefix returns 404 for the whole surface.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, Optional

from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page, data_of
from ..http.transport import encode_path_segment
from .evaluate_request import to_evaluate_body
from .results import EventBatchResult, EventResult, FraudDecision

__all__ = ["FraudClient", "FraudEventsClient", "FraudDecisionsClient", "EVENT_BATCH_LIMIT"]

_BASE = "/api/v1/fraud"

#: Hard upper bound on events per batch call, enforced by the gateway.
#:
#: Checked locally as well, because the gateway rejects the WHOLE batch when it
#: is exceeded: failing before the network keeps a caller from losing 500 good
#: events to one oversized call.
EVENT_BATCH_LIMIT = 500

#: Filters the decision-log list accepts, as Python name → query parameter.
_LOG_FILTERS: Dict[str, str] = {
    "payment_id": "paymentId",
    "decision": "decision",
    "integration_mode": "integrationMode",
    "product_context": "productContext",
    "limit": "limit",
    "cursor": "cursor",
}


class FraudEventsClient:
    """Transaction event ingest — the history that counting rules read.

    🔴 THESE TWO ROUTES ARE SIGNED PER REQUEST, not bearer-only like the
    decision surface. The signature is what binds an event to your account, so
    a body value cannot claim a different one: the merchant is stamped from the
    authenticated key and the body is never read for it.
    """

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def record(
        self,
        event: Mapping[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> EventResult:
        """Records one transaction event.

        Required keys: ``eventId``, ``eventType``, ``subjectType``,
        ``occurredAt``. ``eventType`` must be a value the gateway's vocabulary
        knows — an unknown type is a 400 rather than a row that is stored and
        never read.

        Retrying with the same ``eventId`` is safe: the second call is
        deduplicated and reports :attr:`~lunixi.fraud.results.EventResult.deduplicated`.

        Args:
            event: The event body. Event fields are passed through as given;
                the dictionary is open, so it is not re-keyed here.
            idempotency_key: Sent as ``Idempotency-Key``. Supplying one also
                makes this write eligible for automatic retry after a network
                failure — without it a timed-out call is not retried, because
                the SDK cannot tell a lost request from a lost response.
        """
        if not isinstance(event, Mapping) or not event:
            raise ConfigurationError("A fraud event must be a non-empty mapping.")

        response = self._api.request(
            "POST",
            f"{_BASE}/events/transactions",
            dict(event),
            step_up=True,
            idempotency_key=idempotency_key,
        )
        return EventResult(data_of(response))

    def record_batch(
        self,
        events: "List[Mapping[str, Any]]",
        *,
        idempotency_key: Optional[str] = None,
    ) -> EventBatchResult:
        """Records up to :data:`EVENT_BATCH_LIMIT` events in one signed call.

        🔴 The result can be PARTIAL. Check
        :meth:`~lunixi.fraud.results.EventBatchResult.failures` — a 200 does
        not mean every event landed.

        Raises:
            ConfigurationError: when the list is empty, holds a non-mapping, or
                exceeds :data:`EVENT_BATCH_LIMIT`.
        """
        if not isinstance(events, (list, tuple)) or len(events) == 0:
            raise ConfigurationError("A fraud event batch must be a non-empty list of events.")
        if any(not isinstance(event, Mapping) for event in events):
            raise ConfigurationError("Every item in a fraud event batch must be a mapping.")
        if len(events) > EVENT_BATCH_LIMIT:
            raise ConfigurationError(
                f"This batch holds {len(events)} events; the per-request limit is "
                f"{EVENT_BATCH_LIMIT}. Split the feed into chunks."
            )

        response = self._api.request(
            "POST",
            f"{_BASE}/events/transactions/batch",
            [dict(event) for event in events],
            step_up=True,
            idempotency_key=idempotency_key,
        )
        return EventBatchResult(data_of(response))


class FraudDecisionsClient:
    """The stored decision logs — what the engine decided and why."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def list(self, **filters: Any) -> Page:
        """Lists decision logs, newest first.

        Paging is cursor-based: pass the previous page's ``next_cursor`` back
        as ``cursor``. ``limit`` is the page size.

        Keyword Args:
            payment_id: Filter by payment intent.
            decision: Filter by outcome (see
                :class:`~lunixi.fraud.taxonomy.Decision`).
            integration_mode: Filter by integration mode.
            product_context: Filter by product context.
            limit: Page size.
            cursor: Cursor from the previous page.

        Raises:
            ConfigurationError: for an unrecognised filter name.
        """
        unknown = sorted(set(filters) - set(_LOG_FILTERS))
        if unknown:
            raise ConfigurationError(
                "Unknown decision-log filter(s): {}. Accepted filters: {}.".format(
                    ", ".join(unknown), ", ".join(_LOG_FILTERS)
                )
            )

        query = {
            _LOG_FILTERS[name]: value for name, value in filters.items() if value is not None
        }
        return Page(self._api.request("GET", f"{_BASE}/decision-logs", None, query=query))

    def get(self, trace_id: str) -> Dict[str, Any]:
        """Returns one decision log by trace id."""
        if not isinstance(trace_id, str) or trace_id.strip() == "":
            raise ConfigurationError("trace_id is required.")
        path = f"{_BASE}/decision-logs/{encode_path_segment(trace_id.strip())}"
        payload = data_of(self._api.request("GET", path))
        return dict(payload) if isinstance(payload, Mapping) else {}

    def latest_for_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """The most recent decision for one payment intent, or ``None``."""
        page = self.list(payment_id=payment_id, limit=1)
        if not page.items:
            return None
        first = page.items[0]
        return dict(first) if isinstance(first, Mapping) else None

    def iterate(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Yields every decision log matching the filters, following cursors.

        Stops when the server reports no further page. A ``cursor`` passed in
        is used as the starting point.
        """
        cursor = filters.pop("cursor", None)
        while True:
            page = self.list(cursor=cursor, **filters)
            for item in page.items:
                yield item
            if not page.has_more or not page.next_cursor:
                return
            cursor = page.next_cursor


class FraudClient:
    """Entry point for the fraud surface.

    Attributes:
        events: :class:`FraudEventsClient` — event ingest.
        decisions: :class:`FraudDecisionsClient` — stored decision logs.
    """

    def __init__(self, api: ApiClient) -> None:
        self._api = api
        self.events = FraudEventsClient(api)
        self.decisions = FraudDecisionsClient(api)

    def evaluate(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> FraudDecision:
        """Evaluates a transaction and returns the decision.

        Call it either with a mapping or with keyword arguments:

        .. code-block:: python

            decision = client.fraud().evaluate(
                integration_mode=INTEGRATION_MODE_STANDALONE,
                channel=Channel.STANDALONE_API,
                transaction_ref="order-2026-0001",
                payment={"amount": "149.90", "currency": "TRY"},
            )

        Fields use Python names; the camelCase spelling from the API reference
        is accepted as an alias. An unknown field raises locally rather than
        costing a 400.

        ⚠️ There is no automatic retry on this route. It runs inside your
        payment flow, so whether a timed-out decision is retried, treated as a
        soft allow, or held is YOUR policy — the SDK will not decide it for
        you.
        """
        merged: Dict[str, Any] = dict(request or {})
        overlap = sorted(set(merged) & set(fields))
        if overlap:
            raise ConfigurationError(
                "Field(s) given both in the request mapping and as keyword "
                "arguments: {}. Pass each one once.".format(", ".join(overlap))
            )
        merged.update(fields)

        response = self._api.request(
            "POST", f"{_BASE}/decisions/evaluate", to_evaluate_body(merged)
        )
        return FraudDecision(data_of(response))
