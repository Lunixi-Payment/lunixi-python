"""Webhook verification against the vectors shared with the other SDKs."""

from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import time

import pytest

from lunixi.errors import ConfigurationError, WebhookVerificationError
from lunixi.fraud.fraud_events import FRAUD_EVENT_TYPES, FraudEvents
from lunixi.webhook.verifier import WebhookVerifier

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _headers(vector, signature=None, timestamp=None, event_type="payment.captured"):
    return {
        "X-Lunixi-Signature": signature or f"v2={vector['expectedV2']}",
        "X-Lunixi-Signature-Timestamp": timestamp or vector["timestamp"],
        "X-Lunixi-Event-Id": vector["eventId"],
        "X-Lunixi-Event-Type": event_type,
    }


def _fresh(secret, body, event_id="evt-fresh", event_type="fraud.flow.async_completed"):
    """Builds a webhook whose timestamp is inside the tolerance window."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    raw = body if isinstance(body, bytes) else body.encode("utf-8")
    signature = hmac.new(
        secret.encode(),
        f"{event_id}.{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "x-lunixi-signature": f"v2={signature}",
        "x-lunixi-signature-timestamp": timestamp,
        "x-lunixi-event-id": event_id,
        "x-lunixi-event-type": event_type,
    }
    return raw, headers, signature


class TestSharedVectors:
    def test_every_vector_verifies(self, webhook_vectors):
        for vector in webhook_vectors:
            verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
            event = verifier.verify(vector["rawBody"], _headers(vector))
            assert event.id == vector["eventId"], vector["name"]

    def test_the_computed_hmac_matches_each_vector(self, webhook_vectors):
        for vector in webhook_vectors:
            expected = hmac.new(
                vector["secret"].encode(),
                f"{vector['eventId']}.{vector['timestamp']}.{vector['rawBody']}".encode(),
                hashlib.sha256,
            ).hexdigest()
            assert expected == vector["expectedV2"], vector["name"]

    def test_a_non_ascii_body_verifies_over_its_raw_bytes(self, webhook_vectors):
        vector = next(v for v in webhook_vectors if v["name"] == "unicode-and-slashes")
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        event = verifier.verify(vector["rawBody"], _headers(vector))
        assert "Şükrü" in json.dumps(event.raw, ensure_ascii=False)

    def test_the_vectors_are_byte_identical_to_the_node_suites(self, webhook_vectors):
        """One source of truth across languages.

        A per-language copy that drifts would let one SDK pass its own tests
        while rejecting webhooks the others accept.
        """
        node_file = REPO_ROOT / "node" / "test" / "fixtures" / "webhook-v2-vectors.json"
        if not node_file.exists():
            pytest.skip("the Node fixture is not present in this checkout")
        assert json.loads(node_file.read_text(encoding="utf-8")) == webhook_vectors


class TestRawBodyDiscipline:
    def test_a_reserialized_body_does_not_verify(self, webhook_vectors):
        """🔴 Sign the RAW body, never a re-serialized one.

        Parsing JSON and dumping it again reorders keys, changes spacing and
        rewrites escapes, so the HMAC differs and every webhook is rejected.
        Capture the raw body BEFORE any JSON middleware touches it.
        """
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        reserialized = json.dumps(json.loads(vector["rawBody"]))

        assert reserialized != vector["rawBody"]
        with pytest.raises(WebhookVerificationError, match="verification failed"):
            verifier.verify(reserialized, _headers(vector))

    def test_bytes_and_str_bodies_verify_identically(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        assert verifier.verify(vector["rawBody"].encode("utf-8"), _headers(vector)).id
        assert verifier.verify(vector["rawBody"], _headers(vector)).id

    def test_a_single_changed_byte_fails(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        with pytest.raises(WebhookVerificationError):
            verifier.verify(vector["rawBody"] + " ", _headers(vector))


class TestSecretRotation:
    def test_either_item_of_a_rotation_pair_is_enough(self, webhook_vectors):
        """During rotation the gateway sends both signatures.

        An endpoint holds one secret, so matching ANY item is correct — and
        requiring the first item would break every endpoint mid-rotation.
        """
        current = webhook_vectors[0]
        previous = next(v for v in webhook_vectors if v["name"] == "rotated-previous-secret")
        assert current["rawBody"] == previous["rawBody"]

        header = f"v2={current['expectedV2']},v2={previous['expectedV2']}"
        for vector in (current, previous):
            verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
            assert verifier.verify(vector["rawBody"], _headers(vector, signature=header)).id

    def test_whitespace_around_the_items_is_tolerated(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        header = f" v2={vector['expectedV2']} , v2=deadbeef "
        assert verifier.verify(vector["rawBody"], _headers(vector, signature=header)).id

    def test_an_unknown_scheme_is_ignored_not_accepted(self, webhook_vectors):
        """A new scheme must not break this version, nor satisfy it."""
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)

        header = f"v3=whatever,v2={vector['expectedV2']}"
        assert verifier.verify(vector["rawBody"], _headers(vector, signature=header)).id

        with pytest.raises(WebhookVerificationError, match="no v2 item"):
            verifier.verify(vector["rawBody"], _headers(vector, signature="v3=whatever"))


class TestFailClosed:
    def test_a_header_without_a_v2_item_always_fails(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        with pytest.raises(WebhookVerificationError, match="no v2 item"):
            verifier.verify(vector["rawBody"], _headers(vector, signature="justavalue"))

    @pytest.mark.parametrize(
        "drop",
        ["X-Lunixi-Signature", "X-Lunixi-Signature-Timestamp", "X-Lunixi-Event-Id"],
    )
    def test_a_missing_required_header_fails(self, webhook_vectors, drop):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        headers = _headers(vector)
        del headers[drop]
        with pytest.raises(WebhookVerificationError, match="missing"):
            verifier.verify(vector["rawBody"], headers)

    def test_the_wrong_secret_fails(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier("whsec_not_the_one", tolerance_seconds=None)
        with pytest.raises(WebhookVerificationError):
            verifier.verify(vector["rawBody"], _headers(vector))

    def test_an_empty_secret_is_refused_at_construction(self):
        for value in ("", "   "):
            with pytest.raises(ConfigurationError, match="secret is required"):
                WebhookVerifier(value)

    def test_a_body_that_is_not_json_fails_after_the_signature_verifies(self):
        secret = "whsec_test_verifier_0123456789"
        raw, headers, _ = _fresh(secret, "not json at all")
        with pytest.raises(WebhookVerificationError, match="not valid JSON"):
            WebhookVerifier(secret).verify(raw, headers)

    def test_a_json_array_body_fails(self):
        secret = "whsec_test_verifier_0123456789"
        raw, headers, _ = _fresh(secret, "[1,2,3]")
        with pytest.raises(WebhookVerificationError, match="not a JSON object"):
            WebhookVerifier(secret).verify(raw, headers)


class TestTimestampTolerance:
    def test_a_fresh_webhook_verifies_inside_the_default_window(self):
        secret = "whsec_test_verifier_0123456789"
        raw, headers, _ = _fresh(secret, '{"id":"evt-fresh","type":"fraud.alert.triggered"}')
        event = WebhookVerifier(secret).verify(raw, headers)
        assert event.type == "fraud.alert.triggered"

    def test_an_old_timestamp_is_rejected_by_default(self, webhook_vectors):
        """The vectors are dated, so the default window rejects them.

        A replay window exists precisely so a captured request stops working;
        disabling it is a test-only choice.
        """
        vector = webhook_vectors[0]
        with pytest.raises(WebhookVerificationError, match="tolerance window"):
            WebhookVerifier(vector["secret"]).verify(vector["rawBody"], _headers(vector))

    def test_a_malformed_timestamp_is_rejected_when_the_check_is_on(self, webhook_vectors):
        vector = webhook_vectors[0]
        with pytest.raises(WebhookVerificationError, match="not a valid date"):
            WebhookVerifier(vector["secret"]).verify(
                vector["rawBody"], _headers(vector, timestamp="not-a-date")
            )

    def test_the_exact_timestamp_string_is_what_is_signed(self, webhook_vectors):
        """An equivalent-but-different spelling must not verify.

        Normalising the timestamp before hashing would break every webhook, so
        the header string is used verbatim.
        """
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        equivalent = vector["timestamp"].replace(".000Z", "Z")

        assert equivalent != vector["timestamp"]
        with pytest.raises(WebhookVerificationError):
            verifier.verify(vector["rawBody"], _headers(vector, timestamp=equivalent))


class TestVerifiedEvent:
    def test_the_envelope_fields_are_exposed(self):
        secret = "whsec_test_verifier_0123456789"
        body = json.dumps(
            {
                "id": "evt-abc",
                "type": FraudEvents.FLOW_ASYNC_COMPLETED,
                "data": {"decisionRequestId": "dreq_1"},
            },
            separators=(",", ":"),
        )
        raw, headers, _ = _fresh(secret, body, event_id="evt-abc")
        event = WebhookVerifier(secret).verify(raw, headers)

        assert event.id == "evt-abc"
        assert event.type == FraudEvents.FLOW_ASYNC_COMPLETED
        assert event.data == {"decisionRequestId": "dreq_1"}
        assert event.timestamp is not None and event.timestamp.tzinfo is not None

    def test_headers_are_matched_case_insensitively(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        lowered = {key.lower(): value for key, value in _headers(vector).items()}
        assert verifier.verify(vector["rawBody"], lowered).id

    def test_a_list_valued_header_takes_its_first_item(self, webhook_vectors):
        vector = webhook_vectors[0]
        verifier = WebhookVerifier(vector["secret"], tolerance_seconds=None)
        headers = {key: [value] for key, value in _headers(vector).items()}
        assert verifier.verify(vector["rawBody"], headers).id

    def test_a_body_without_an_envelope_type_falls_back_to_the_header(self):
        secret = "whsec_test_verifier_0123456789"
        raw, headers, _ = _fresh(secret, '{"data":{}}', event_type="fraud.report.ready")
        event = WebhookVerifier(secret).verify(raw, headers)
        assert event.type == "fraud.report.ready"
        assert event.id == "evt-fresh"


class TestFraudEventCatalogue:
    def test_there_are_exactly_seven_fraud_event_types(self):
        assert len(FRAUD_EVENT_TYPES) == 7
        assert len(set(FRAUD_EVENT_TYPES)) == 7

    def test_every_type_is_namespaced_under_fraud(self):
        for event_type in FRAUD_EVENT_TYPES:
            assert event_type.startswith("fraud.")

    def test_the_catalogue_matches_the_published_names(self):
        assert FRAUD_EVENT_TYPES == (
            "fraud.flow.async_completed",
            "fraud.flow.action_triggered",
            "fraud.quota.threshold_reached",
            "fraud.alert.triggered",
            "fraud.service.degraded",
            "fraud.service.recovered",
            "fraud.report.ready",
        )

    def test_no_internal_topic_name_leaked_into_the_catalogue(self):
        """Internal event-bus topics are never delivered to an endpoint.

        Publishing one would invite an integration to subscribe to something
        that never arrives.
        """
        for event_type in FRAUD_EVENT_TYPES:
            assert not event_type.endswith(".v1")

    def test_every_constant_appears_in_the_tuple(self):
        constants = {
            value
            for name, value in vars(FraudEvents).items()
            if not name.startswith("_") and isinstance(value, str)
        }
        assert constants == set(FRAUD_EVENT_TYPES)
