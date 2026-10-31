"""The fraud surface is exactly five routes — measured, not grepped.

This lock DRIVES every public method of the fraud client against a recording
transport and collects the paths that were actually requested. A lock that
searched the source text instead would pass on a path that is written down but
never called, and fail on one built from a constant — it would be checking the
file, not the client.

Why it exists: the console's own fraud routes are not a customer surface. They
carry no stability guarantee, and an integration built on them breaks without
notice. If a method is ever added here that reaches one, this test fails.
"""

from __future__ import annotations

import inspect
import re

import pytest

from lunixi.fraud.fraud_client import (
    FraudClient,
    FraudDecisionsClient,
    FraudEventsClient,
)
from lunixi.fraud.taxonomy import (
    AUTH_MODE_VALUES,
    CHANNEL_VALUES,
    DECISION_VALUES,
    OPERATION_KIND_VALUES,
    PRODUCT_CONTEXT_VALUES,
    STAGE_VALUES,
    SURFACE_VALUES,
    AuthMode,
    Channel,
    Decision,
    OperationKind,
    ProductContext,
    Stage,
    Surface,
)

from .support.recording_transport import envelope, json_response

#: The documented machine surface, as the gateway publishes it.
EXPECTED_ROUTES = {
    ("POST", "/api/v1/fraud/decisions/evaluate"),
    ("GET", "/api/v1/fraud/decision-logs"),
    ("GET", "/api/v1/fraud/decision-logs/{id}"),
    ("POST", "/api/v1/fraud/events/transactions"),
    ("POST", "/api/v1/fraud/events/transactions/batch"),
}

_TRACE_ID = "trace-surface-probe"


def _normalize(method: str, path: str) -> "tuple[str, str]":
    """Strips the query string and templates the trace-id segment."""
    bare = path.split("?", 1)[0]
    bare = re.sub(r"/decision-logs/[^/]+$", "/decision-logs/{id}", bare)
    return method.upper(), bare


def _drive_every_method(transport, client) -> "set[tuple[str, str]]":
    """Calls every public fraud method once and returns the routes reached."""
    fraud = client.fraud()
    event = {
        "eventId": "evt-surface",
        "eventType": "card_sale",
        "subjectType": "customer",
        "occurredAt": "2026-10-11T08:29:00Z",
    }

    fraud.evaluate(channel=Channel.STANDALONE_API)
    fraud.decisions.list(limit=1)
    fraud.decisions.get(_TRACE_ID)
    fraud.decisions.latest_for_payment("pay-surface")
    list(fraud.decisions.iterate(limit=1))
    fraud.events.record(event)
    fraud.events.record_batch([event])

    return {
        _normalize(request.method, request.path)
        for request in transport.requests
        if "/fraud" in request.path
    }


@pytest.fixture
def driven_client(client_factory):
    """A client whose queued answers let each route be visited exactly once.

    Every list answer is a TERMINAL page, so `iterate` and
    `latest_for_payment` do not paginate: the probe must visit each route, not
    walk through it.
    """
    responses = [
        json_response(envelope({"decision": "allow"})),  # evaluate
        json_response(envelope([{"traceId": _TRACE_ID}])),  # list
        json_response(envelope({"traceId": _TRACE_ID})),  # get
        json_response(envelope([{"traceId": _TRACE_ID}])),  # latest_for_payment
        json_response(envelope([{"traceId": _TRACE_ID}])),  # iterate
        json_response(envelope({"eventId": "evt-surface"})),  # record
        json_response(envelope({"total": 1, "inserted": 1, "results": []})),  # record_batch
    ]
    return client_factory(*responses)


class TestRouteSurface:
    def test_the_client_reaches_exactly_the_five_documented_routes(self, driven_client):
        transport, client = driven_client
        reached = _drive_every_method(transport, client)
        assert reached == EXPECTED_ROUTES

    def test_no_console_route_is_reached(self, driven_client):
        """The console's routes live under a different prefix."""
        transport, client = driven_client
        _drive_every_method(transport, client)
        for request in transport.requests:
            assert "/panel/" not in request.path
            assert "/api/panel" not in request.path

    def test_every_fraud_path_carries_the_api_v1_prefix(self, driven_client):
        transport, client = driven_client
        _drive_every_method(transport, client)
        for request in transport.requests:
            if "/fraud" in request.path:
                assert request.path.startswith("/api/v1/fraud")

    def test_only_the_event_routes_are_signed_per_request(self, driven_client):
        """The two authentication levels are not interchangeable.

        An event route called bearer-only is a 401; signing a read adds a
        nonce and a replay record for nothing.
        """
        transport, client = driven_client
        _drive_every_method(transport, client)

        for request in transport.requests:
            if "/auth/token" in request.path:
                continue
            signed = request.header("X-Signature") is not None
            assert signed == ("/fraud/events/transactions" in request.path), request.path

    def test_the_public_method_surface_is_closed(self):
        """A new public method must come with a decision about the surface."""

        def public(cls):
            return {
                name
                for name, member in inspect.getmembers(cls, inspect.isfunction)
                if not name.startswith("_")
            }

        assert public(FraudClient) == {"evaluate"}
        assert public(FraudEventsClient) == {"record", "record_batch"}
        assert public(FraudDecisionsClient) == {"list", "get", "latest_for_payment", "iterate"}


class TestTaxonomyCompleteness:
    @pytest.mark.parametrize(
        "holder,values",
        [
            (Channel, CHANNEL_VALUES),
            (Surface, SURFACE_VALUES),
            (Stage, STAGE_VALUES),
            (OperationKind, OPERATION_KIND_VALUES),
            (AuthMode, AUTH_MODE_VALUES),
            (ProductContext, PRODUCT_CONTEXT_VALUES),
            (Decision, DECISION_VALUES),
        ],
    )
    def test_each_value_tuple_matches_its_constant_holder(self, holder, values):
        """🔴 A value list that drifts from its constants is worse than none.

        The SDK validates against the tuple while a caller writes the constant;
        if one gains a member and the other does not, a legitimate value is
        refused locally and never reaches the gateway.
        """
        declared = {
            value
            for name, value in vars(holder).items()
            if not name.startswith("_") and isinstance(value, str)
        }
        assert declared == set(values)
        assert len(values) == len(set(values))

    def test_the_counts_match_the_published_dictionaries(self):
        assert len(CHANNEL_VALUES) == 2
        assert len(SURFACE_VALUES) == 4
        assert len(STAGE_VALUES) == 5
        assert len(OPERATION_KIND_VALUES) == 14
        assert len(AUTH_MODE_VALUES) == 2
        assert len(PRODUCT_CONTEXT_VALUES) == 4
        assert len(DECISION_VALUES) == 4

    def test_the_platform_only_channels_are_absent(self):
        for value in ("lunixi_checkout", "wallet", "direct_api", "event_ingest", "backoffice"):
            assert value not in CHANNEL_VALUES

    def test_the_unbilled_lane_contexts_are_absent(self):
        for value in ("simulation", "post_hoc_backfill", "manual_review"):
            assert value not in PRODUCT_CONTEXT_VALUES


class TestLockNegativeControl:
    """Proves the lock above would actually fail.

    A lock nobody can break is not a lock. Each test introduces the exact
    drift the lock exists to catch, then asserts the lock's own machinery
    rejects it.
    """

    def test_a_console_route_would_be_caught(self, client_factory):
        transport, client = client_factory(json_response(envelope({"items": []})))
        from lunixi.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            client.api().request("GET", "/api/panel/v1/fraud/cases")
        assert transport.requests == []

    def test_a_missing_route_would_be_caught(self, client_factory):
        transport, client = client_factory(json_response(envelope({"decision": "allow"})))
        client.fraud().evaluate(channel=Channel.STANDALONE_API)

        reached = {
            _normalize(request.method, request.path)
            for request in transport.requests
            if "/fraud" in request.path
        }
        # Only one of the five routes was visited, so the lock's equality
        # assertion must not hold.
        assert reached == {("POST", "/api/v1/fraud/decisions/evaluate")}
        assert reached != EXPECTED_ROUTES

    def test_an_unsigned_event_call_would_be_caught(self, client_factory):
        """What a new method that forgot `step_up=True` would produce."""
        transport, client = client_factory(json_response(envelope({"eventId": "evt-unsigned"})))
        client.api().request(
            "POST", "/api/v1/fraud/events/transactions", {"eventId": "evt-unsigned"}
        )

        request = transport.last
        signed = request.header("X-Signature") is not None
        assert signed is False
        # This is the very comparison the lock makes, and it fails here.
        assert signed != ("/fraud/events/transactions" in request.path)
