"""Event ingest: per-request signing, the batch limit and partial success."""

from __future__ import annotations

import pytest

from lunixi.auth.canonical_request import build_canonical_request, digest_for_body
from lunixi.auth.ed25519_signer import verify_signature
from lunixi.errors import ApiError, ConfigurationError
from lunixi.fraud.fraud_client import EVENT_BATCH_LIMIT

from .support.recording_transport import envelope, json_response, transport_failure

EVENT = {
    "eventId": "evt-0001",
    "eventType": "card_sale",
    "subjectType": "customer",
    "occurredAt": "2026-10-11T08:29:00Z",
}


def _event(index: int) -> dict:
    return dict(EVENT, eventId=f"evt-{index:04d}")


class TestSingleEvent:
    def test_the_route_is_the_documented_ingest_path(self, client_factory):
        transport, client = client_factory(
            json_response(envelope({"eventId": "evt-0001", "id": "row-1", "deduplicated": False}))
        )
        client.fraud().events.record(EVENT)

        assert transport.last.method == "POST"
        assert transport.last.path == "/api/v1/fraud/events/transactions"

    def test_the_call_is_signed_per_request_not_bearer_only(self, client_factory):
        """🔴 The signature is what binds an event to the account.

        These routes accept nothing less: a bearer-only call is a 401. The
        merchant is stamped from the authenticated key, so a body value cannot
        claim a different one.
        """
        transport, client = client_factory(json_response(envelope({"eventId": "evt-0001"})))
        client.fraud().events.record(EVENT)

        request = transport.last
        for header in ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature", "Digest"):
            assert request.header(header), header

    def test_the_digest_and_signature_match_the_exact_body_sent(
        self, client_factory, test_key_pair
    ):
        _, public_key = test_key_pair
        transport, client = client_factory(json_response(envelope({"eventId": "evt-0001"})))
        client.fraud().events.record(EVENT)

        request = transport.last
        assert request.header("Digest") == digest_for_body(request.body)
        canonical = build_canonical_request(
            "POST",
            request.path,
            request.header("X-Date"),
            request.header("X-Nonce"),
            request.header("Digest"),
        )
        assert verify_signature(public_key, request.header("X-Signature"), canonical) is True

    def test_the_body_is_compact_json(self, client_factory):
        transport, client = client_factory(json_response(envelope({"eventId": "evt-0001"})))
        client.fraud().events.record(EVENT)
        assert ", " not in transport.last.body
        assert transport.last.body.startswith('{"eventId":"evt-0001"')

    def test_an_idempotency_key_is_sent_and_makes_the_write_retryable(self, client_factory):
        transport, client = client_factory(
            transport_failure(), json_response(envelope({"eventId": "evt-0001"}))
        )
        client.fraud().events.record(EVENT, idempotency_key="idem-evt-0001")

        requests = transport.requests_to("/events/transactions")
        assert len(requests) == 2
        assert requests[0].header("Idempotency-Key") == "idem-evt-0001"

    def test_without_an_idempotency_key_a_failed_write_is_not_replayed(self, client_factory):
        transport, client = client_factory(transport_failure(), json_response(envelope({})))
        with pytest.raises(ApiError):
            client.fraud().events.record(EVENT)
        assert len(transport.requests_to("/events/transactions")) == 1

    def test_an_empty_or_non_mapping_event_is_refused_locally(self, client_factory):
        transport, client = client_factory()
        for value in ({}, [], None, "evt"):
            with pytest.raises(ConfigurationError, match="non-empty mapping"):
                client.fraud().events.record(value)

    def test_the_result_reports_the_row_id_and_matched_flows(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope(
                    {
                        "eventId": "evt-0001",
                        "id": "row-1",
                        "deduplicated": False,
                        "matchedFlowCount": 2,
                    }
                )
            )
        )
        result = client.fraud().events.record(EVENT)

        assert result.event_id == "evt-0001"
        assert result.row_id == "row-1"
        assert result.deduplicated is False
        assert result.matched_flow_count == 2
        assert result.failed is False

    def test_a_deduplicated_event_reports_no_row_id(self, client_factory):
        """Branch on `deduplicated`, not on the absence of an id.

        Retrying with the same eventId is therefore safe, which is what makes
        an idempotency key usable at all.
        """
        transport, client = client_factory(
            json_response(envelope({"eventId": "evt-0001", "deduplicated": True}))
        )
        result = client.fraud().events.record(EVENT)

        assert result.deduplicated is True
        assert result.row_id is None
        assert result.failed is False


class TestBatch:
    def test_the_route_is_the_documented_batch_path(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope({"total": 1, "inserted": 1, "deduplicated": 0, "failed": 0, "results": []})
            )
        )
        client.fraud().events.record_batch([EVENT])
        assert transport.last.path == "/api/v1/fraud/events/transactions/batch"

    def test_the_body_is_a_json_array(self, client_factory):
        transport, client = client_factory(
            json_response(envelope({"total": 2, "inserted": 2, "results": []}))
        )
        client.fraud().events.record_batch([_event(1), _event(2)])
        assert transport.last.body.startswith("[{")
        assert transport.last.body.endswith("}]")

    def test_the_batch_call_is_signed_and_the_array_digest_matches(
        self, client_factory, test_key_pair
    ):
        _, public_key = test_key_pair
        transport, client = client_factory(
            json_response(envelope({"total": 2, "inserted": 2, "results": []}))
        )
        client.fraud().events.record_batch([_event(1), _event(2)])

        request = transport.last
        assert request.header("Digest") == digest_for_body(request.body)
        canonical = build_canonical_request(
            "POST",
            request.path,
            request.header("X-Date"),
            request.header("X-Nonce"),
            request.header("Digest"),
        )
        assert verify_signature(public_key, request.header("X-Signature"), canonical) is True

    def test_the_limit_is_500(self):
        assert EVENT_BATCH_LIMIT == 500

    def test_a_batch_at_the_limit_is_sent(self, client_factory):
        transport, client = client_factory(
            json_response(envelope({"total": 500, "inserted": 500, "results": []}))
        )
        client.fraud().events.record_batch([_event(i) for i in range(EVENT_BATCH_LIMIT)])
        assert len(transport.requests_to("/batch")) == 1

    def test_a_batch_over_the_limit_fails_before_the_network(self, client_factory):
        """🔴 The gateway rejects the WHOLE batch when the limit is exceeded.

        Failing locally keeps the caller from losing 500 good events to one
        oversized call, and the message says what to do about it.
        """
        transport, client = client_factory()
        with pytest.raises(ConfigurationError) as caught:
            client.fraud().events.record_batch([_event(i) for i in range(EVENT_BATCH_LIMIT + 1)])

        assert "501" in str(caught.value)
        assert "500" in str(caught.value)
        assert "chunks" in str(caught.value)
        assert transport.requests == []

    def test_an_empty_batch_is_refused(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.fraud().events.record_batch([])

    def test_a_batch_holding_a_non_mapping_is_refused(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            client.fraud().events.record_batch([EVENT, "evt-2"])

    def test_a_non_list_batch_is_refused(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError, match="non-empty list"):
            client.fraud().events.record_batch(EVENT)


class TestPartialSuccess:
    def _result(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope(
                    {
                        "total": 4,
                        "inserted": 2,
                        "deduplicated": 1,
                        "failed": 1,
                        "results": [
                            {"eventId": "evt-0001", "id": "row-1", "deduplicated": False},
                            {"eventId": "evt-0002", "id": "row-2", "deduplicated": False},
                            {"eventId": "evt-0003", "deduplicated": True},
                            {"eventId": "evt-0004", "error": "occurredAt is required"},
                        ],
                    }
                )
            )
        )
        return client.fraud().events.record_batch([_event(i) for i in range(1, 5)])

    def test_the_counts_are_read_from_the_body(self, client_factory):
        result = self._result(client_factory)
        assert (result.total, result.inserted, result.deduplicated, result.failed) == (4, 2, 1, 1)

    def test_a_200_can_still_hold_failures(self, client_factory):
        """🔴 A batch answers 200 even when individual events were rejected.

        An integration that reads only the status code loses events silently,
        so the per-event error is the only place the failure is visible.
        """
        result = self._result(client_factory)
        failures = result.failures()

        assert len(failures) == 1
        assert failures[0].event_id == "evt-0004"
        assert failures[0].error == "occurredAt is required"
        assert failures[0].failed is True

    def test_the_results_keep_the_order_sent(self, client_factory):
        result = self._result(client_factory)
        assert [row.event_id for row in result.results] == [
            "evt-0001",
            "evt-0002",
            "evt-0003",
            "evt-0004",
        ]

    def test_a_fully_successful_batch_reports_no_failures(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope(
                    {
                        "total": 1,
                        "inserted": 1,
                        "deduplicated": 0,
                        "failed": 0,
                        "results": [{"eventId": "evt-0001", "id": "row-1"}],
                    }
                )
            )
        )
        result = client.fraud().events.record_batch([EVENT])
        assert result.failures() == []

    def test_a_result_body_without_counts_reads_as_zeros_not_as_none(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        result = client.fraud().events.record_batch([EVENT])
        assert (result.total, result.inserted, result.failed) == (0, 0, 0)
        assert result.results == []
