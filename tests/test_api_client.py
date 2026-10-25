"""The authenticated request path: headers, step-up signing, retries, errors."""

from __future__ import annotations

import pytest

from lunixi.auth.canonical_request import build_canonical_request, digest_for_body
from lunixi.auth.ed25519_signer import verify_signature
from lunixi.configuration import Configuration
from lunixi.errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)

from .conftest import BASE_URL, KEY_ID, TEST_ACCESS_TOKEN, token_response
from .support.recording_transport import (
    RecordingTransport,
    envelope,
    error_envelope,
    json_response,
    transport_failure,
)


class TestBearerHeaders:
    def test_every_call_carries_the_bearer_token(self, client_factory):
        transport, client = client_factory(json_response(envelope({"ok": True})))
        client.api().request("GET", "/api/v1/fraud/decision-logs")

        assert transport.last.header("Authorization") == f"Bearer {TEST_ACCESS_TOKEN}"

    def test_the_user_agent_names_the_sdk(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("GET", "/api/v1/x")
        assert transport.last.header("User-Agent").startswith("lunixi-sdk/")

    def test_a_custom_user_agent_is_sent(self, client_factory):
        transport, client = client_factory(json_response(envelope({})), user_agent="acme/2.1")
        client.api().request("GET", "/api/v1/x")
        assert transport.last.header("User-Agent") == "acme/2.1"

    def test_a_body_sets_the_content_type(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/x", {"a": 1})
        assert transport.last.header("Content-Type") == "application/json"

    def test_a_bodyless_call_sets_no_content_type(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("GET", "/api/v1/x")
        assert transport.last.header("Content-Type") is None
        assert transport.last.body is None

    def test_an_idempotency_key_is_sent_as_a_header(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/x", {"a": 1}, idempotency_key="idem-1")
        assert transport.last.header("Idempotency-Key") == "idem-1"


class TestBodySerialization:
    def test_the_body_on_the_wire_is_compact_json(self, client_factory):
        """🔴 Whitespace in the body makes the gateway's digest check fail."""
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/x", {"a": 1, "b": {"c": 2}})
        assert transport.last.body == '{"a":1,"b":{"c":2}}'
        assert ", " not in transport.last.body
        assert ": " not in transport.last.body


class TestStepUpSigning:
    def test_step_up_adds_the_four_signature_headers_and_the_digest(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/fraud/events/transactions", {"eventId": "e1"}, step_up=True)

        request = transport.last
        for header in ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature", "Digest"):
            assert request.header(header), header
        assert request.header("X-Key-Id") == KEY_ID
        assert request.header("Authorization") == f"Bearer {TEST_ACCESS_TOKEN}"

    def test_the_digest_matches_the_exact_body_bytes_sent(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/x", {"eventId": "e1"}, step_up=True)

        request = transport.last
        assert request.header("Digest") == digest_for_body(request.body)

    def test_the_signature_verifies_over_the_path_and_digest_actually_sent(
        self, client_factory, test_key_pair
    ):
        _, public_key = test_key_pair
        transport, client = client_factory(json_response(envelope({})))
        client.api().request(
            "POST",
            "/api/v1/fraud/events/transactions",
            [{"eventId": "e1"}],
            step_up=True,
        )

        request = transport.last
        canonical = build_canonical_request(
            request.method,
            request.path,
            request.header("X-Date"),
            request.header("X-Nonce"),
            request.header("Digest"),
        )
        assert verify_signature(public_key, request.header("X-Signature"), canonical) is True

    def test_a_signed_get_with_filters_signs_the_query_string_too(
        self, client_factory, test_key_pair
    ):
        _, public_key = test_key_pair
        transport, client = client_factory(json_response(envelope([])))
        client.api().request(
            "GET", "/api/v1/fraud/decision-logs", None, query={"limit": 25}, step_up=True
        )

        request = transport.last
        assert "?" in request.path
        assert request.header("Digest") is None  # no body, no digest
        canonical = build_canonical_request(
            "GET", request.path, request.header("X-Date"), request.header("X-Nonce")
        )
        assert verify_signature(public_key, request.header("X-Signature"), canonical) is True

    def test_without_step_up_no_signature_headers_are_sent(self, client_factory):
        transport, client = client_factory(json_response(envelope({})))
        client.api().request("POST", "/api/v1/x", {"a": 1})
        assert transport.last.header("X-Signature") is None
        assert transport.last.header("X-Key-Id") is None


class TestQueryBuilding:
    def test_empty_values_are_dropped(self, client_factory):
        transport, client = client_factory(json_response(envelope([])))
        client.api().request(
            "GET",
            "/api/v1/fraud/decision-logs",
            None,
            query={"limit": 25, "cursor": None, "decision": ""},
        )
        assert transport.last.path == "/api/v1/fraud/decision-logs?limit=25"

    def test_an_all_empty_query_leaves_the_path_bare(self, client_factory):
        transport, client = client_factory(json_response(envelope([])))
        client.api().request("GET", "/api/v1/x", None, query={"cursor": None})
        assert transport.last.path == "/api/v1/x"

    def test_values_are_percent_encoded(self, client_factory):
        transport, client = client_factory(json_response(envelope([])))
        client.api().request("GET", "/api/v1/x", None, query={"q": "a b&c"})
        assert "a+b%26c" in transport.last.path


class TestErrorMapping:
    def test_a_400_is_a_validation_error_carrying_the_gateway_code(self, client_factory):
        transport, client = client_factory(
            json_response(
                error_envelope("FRAUD_CHANNEL_NOT_DECLARABLE", "channel is not declarable"),
                status_code=400,
            )
        )
        with pytest.raises(ValidationError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})

        assert caught.value.code == "FRAUD_CHANNEL_NOT_DECLARABLE"
        assert caught.value.status_code == 400
        assert "not declarable" in caught.value.message

    def test_a_403_product_gate_refusal_is_an_authentication_error(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("PRODUCT_NOT_ENABLED", "not enabled", 403), status_code=403)
        )
        with pytest.raises(AuthenticationError) as caught:
            client.api().request("GET", "/api/v1/x")
        assert caught.value.code == "PRODUCT_NOT_ENABLED"

    def test_a_429_carries_retry_after_and_the_quota_headers(self, client_factory):
        transport, client = client_factory(
            json_response(
                error_envelope("QUOTA_EXCEEDED", "quota exceeded", 429),
                status_code=429,
                headers={
                    "retry-after": "30",
                    "x-ratelimit-limit": "100",
                    "x-ratelimit-remaining": "0",
                    "x-quota-limit": "5000",
                },
            )
        )
        with pytest.raises(RateLimitError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})

        error = caught.value
        assert error.retry_after == 30
        assert error.quota["rate_limit"] == 100
        assert error.quota["rate_remaining"] == 0
        assert error.quota["daily_limit"] == 5000
        # The gateway omits a header rather than guessing, so an absent one is
        # None — never a fabricated default.
        assert error.quota["daily_remaining"] is None

    def test_a_503_carries_retry_after(self, client_factory):
        transport, client = client_factory(
            json_response(
                error_envelope("SERVICE_UNAVAILABLE", "unavailable", 503),
                status_code=503,
                headers={"retry-after": "5"},
            )
        )
        with pytest.raises(ServiceUnavailableError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})
        assert caught.value.retry_after == 5

    def test_a_429_without_quota_headers_reports_none_rather_than_zeros(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("QUOTA_EXCEEDED", "quota", 429), status_code=429)
        )
        with pytest.raises(RateLimitError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})
        assert caught.value.retry_after is None
        assert caught.value.quota is None

    def test_an_unparsable_retry_after_reads_as_none(self, client_factory):
        transport, client = client_factory(
            json_response(
                error_envelope("QUOTA_EXCEEDED", "quota", 429),
                status_code=429,
                headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
            )
        )
        with pytest.raises(RateLimitError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})
        # A guessed number would make the client retry at the wrong rate.
        assert caught.value.retry_after is None

    def test_the_request_id_is_carried_for_support(self, client_factory):
        transport, client = client_factory(
            json_response(
                error_envelope("INTERNAL", "boom", 500),
                status_code=500,
                headers={"x-request-id": "req_abc123"},
            )
        )
        with pytest.raises(ApiError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})
        assert caught.value.request_id == "req_abc123"

    def test_an_html_error_page_still_produces_a_readable_error(self, client_factory):
        from lunixi.http.transport import HttpResponse

        transport, client = client_factory(
            HttpResponse(502, {"content-type": "text/html"}, b"<html>bad gateway</html>")
        )
        with pytest.raises(ApiError) as caught:
            client.api().request("POST", "/api/v1/x", {"a": 1})
        assert caught.value.status_code == 502


class TestRetryPolicy:
    def test_a_get_is_retried_after_a_transport_failure(self, client_factory):
        transport, client = client_factory(
            transport_failure(), json_response(envelope({"ok": True}))
        )
        result = client.api().request("GET", "/api/v1/x")
        assert result["data"] == {"ok": True}
        assert len(transport.requests_to("/api/v1/x")) == 2

    def test_a_get_is_retried_after_a_500(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("INTERNAL", "boom", 500), status_code=500),
            json_response(envelope({"ok": True})),
        )
        assert client.api().request("GET", "/api/v1/x")["data"] == {"ok": True}

    def test_an_unkeyed_post_is_never_retried(self, client_factory):
        """🔴 Replaying an unkeyed write can record the same event twice.

        The SDK cannot tell a lost request from a lost response, so it does not
        guess: without an idempotency key the failure surfaces.
        """
        transport, client = client_factory(transport_failure(), json_response(envelope({})))
        with pytest.raises(ApiError, match="Gateway request failed"):
            client.api().request("POST", "/api/v1/x", {"a": 1})
        assert len(transport.requests_to("/api/v1/x")) == 1

    def test_a_keyed_post_is_retried(self, client_factory):
        transport, client = client_factory(
            transport_failure(), json_response(envelope({"ok": True}))
        )
        result = client.api().request("POST", "/api/v1/x", {"a": 1}, idempotency_key="idem-1")
        assert result["data"] == {"ok": True}
        assert len(transport.requests_to("/api/v1/x")) == 2

    def test_a_retry_resigns_with_a_fresh_nonce(self, client_factory):
        """A replayed nonce is rejected with NONCE_REPLAY.

        A retry that reused the signature headers of the failed attempt would
        be refused for a reason unrelated to the original failure.
        """
        transport, client = client_factory(
            transport_failure(), json_response(envelope({"ok": True}))
        )
        client.api().request(
            "POST", "/api/v1/x", {"a": 1}, step_up=True, idempotency_key="idem-1"
        )

        first, second = transport.requests_to("/api/v1/x")
        assert first.header("X-Nonce") != second.header("X-Nonce")
        assert first.header("X-Signature") != second.header("X-Signature")

    def test_retries_stop_at_max_retries(self, client_factory):
        transport, client = client_factory(
            transport_failure(), transport_failure(), transport_failure(), max_retries=1
        )
        with pytest.raises(ApiError):
            client.api().request("GET", "/api/v1/x")
        assert len(transport.requests_to("/api/v1/x")) == 2  # original + 1 retry

    def test_retries_can_be_disabled(self, client_factory):
        transport, client = client_factory(transport_failure(), max_retries=0)
        with pytest.raises(ApiError):
            client.api().request("GET", "/api/v1/x")
        assert len(transport.requests_to("/api/v1/x")) == 1

    def test_a_400_is_not_retried(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("BAD", "bad", 400), status_code=400)
        )
        with pytest.raises(ValidationError):
            client.api().request("GET", "/api/v1/x")
        assert len(transport.requests_to("/api/v1/x")) == 1


class TestTokenRefreshOnUnauthorized:
    def test_a_401_triggers_one_refresh_and_one_retry(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("TOKEN_EXPIRED", "expired", 401), status_code=401),
            token_response(),
            json_response(envelope({"ok": True})),
        )
        assert client.api().request("GET", "/api/v1/x")["data"] == {"ok": True}
        assert len(transport.requests_to("/auth/token")) == 2

    def test_a_second_401_surfaces_rather_than_looping(self, client_factory):
        transport, client = client_factory(
            json_response(error_envelope("TOKEN_EXPIRED", "expired", 401), status_code=401),
            token_response(),
            json_response(error_envelope("INVALID_TOKEN", "invalid", 401), status_code=401),
        )
        with pytest.raises(AuthenticationError) as caught:
            client.api().request("GET", "/api/v1/x")
        assert caught.value.code == "INVALID_TOKEN"


class TestConfigurationValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"base_url": "", "key_id": "k"},
            {"base_url": "https://x.test", "key_id": ""},
            {"base_url": "x.test", "key_id": "k"},
            {"base_url": "https://x.test", "key_id": "k", "timeout_seconds": 0},
            {"base_url": "https://x.test", "key_id": "k", "max_retries": -1},
            {"base_url": "https://x.test", "key_id": "k", "auth_token_path": "auth/token"},
        ],
    )
    def test_a_bad_field_fails_at_construction_naming_the_field(self, kwargs):
        with pytest.raises(ConfigurationError):
            Configuration(**kwargs)

    def test_a_trailing_slash_on_the_base_url_is_stripped(self):
        config = Configuration(base_url="https://x.test/", key_id="k")
        assert config.base_url == "https://x.test"
        assert config.url_for("/api/v1/x") == "https://x.test/api/v1/x"

    def test_the_private_key_is_not_stored_on_the_configuration(self):
        """Configuration ends up in logs and crash reports; the key must not.

        `__slots__` without a `private_key` entry makes that structural rather
        than a convention someone has to remember.
        """
        config = Configuration(base_url="https://x.test", key_id="k", private_key="SECRET-PEM")
        assert not hasattr(config, "private_key")
        assert "SECRET-PEM" not in repr(config)
