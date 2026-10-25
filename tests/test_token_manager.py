"""Token exchange: the signed request, the cache and the failure paths."""

from __future__ import annotations

import base64
import threading

import pytest

from lunixi.auth.canonical_request import build_canonical_request
from lunixi.auth.ed25519_signer import Ed25519Signer, verify_signature
from lunixi.auth.token_manager import (
    InMemoryTokenStore,
    TokenManager,
    new_nonce,
    utc_timestamp,
)
from lunixi.configuration import Configuration
from lunixi.errors import ApiError, AuthenticationError

from .conftest import BASE_URL, KEY_ID, TEST_ACCESS_TOKEN, token_response
from .support.recording_transport import (
    RecordingTransport,
    envelope,
    json_response,
    transport_failure,
)


def _manager(transport, private_key, **kwargs):
    config = Configuration(base_url=BASE_URL, key_id=KEY_ID, transport=transport, **kwargs)
    return TokenManager(config, Ed25519Signer(private_key)), config


class TestSignedExchange:
    def test_the_exchange_is_a_post_to_the_token_path(self, test_key_pair):
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])

        assert manager.get_token() == TEST_ACCESS_TOKEN
        assert transport.last.method == "POST"
        assert transport.last.url == f"{BASE_URL}/api/v1/auth/token"

    def test_the_exchange_carries_no_body_and_therefore_no_digest(self, test_key_pair):
        """The gateway appends the Digest line only when the header is sent.

        A Digest header on a bodyless request would produce a canonical string
        the gateway does not build, and the signature would never verify.
        """
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()

        assert transport.last.body is None
        assert transport.last.header("Digest") is None

    def test_the_signature_verifies_against_the_public_key(self, test_key_pair):
        private_key, public_key = test_key_pair
        transport = RecordingTransport([token_response()])
        manager, config = _manager(transport, private_key)
        manager.get_token()

        request = transport.last
        canonical = build_canonical_request(
            "POST",
            config.auth_token_path,
            request.header("X-Date"),
            request.header("X-Nonce"),
        )
        assert verify_signature(public_key, request.header("X-Signature"), canonical) is True

    def test_the_key_id_header_carries_the_configured_key_id(self, test_key_pair):
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()
        assert transport.last.header("X-Key-Id") == KEY_ID

    def test_no_authorization_header_is_sent_on_the_exchange(self, test_key_pair):
        # The exchange is what produces the token; sending one would be circular.
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()
        assert transport.last.header("Authorization") is None


class TestTimestampAndNonce:
    def test_the_timestamp_is_second_precision_utc_with_a_trailing_z(self):
        """The gateway parses X-Date and enforces a ±5 minute window."""
        value = utc_timestamp()
        assert value.endswith("Z")
        assert len(value) == 20  # YYYY-MM-DDTHH:MM:SSZ
        assert "." not in value

    def test_each_nonce_is_fresh_and_32_hex_characters(self):
        """A repeated nonce is rejected with NONCE_REPLAY."""
        nonces = {new_nonce() for _ in range(200)}
        assert len(nonces) == 200
        for nonce in nonces:
            assert len(nonce) == 32
            int(nonce, 16)

    def test_two_exchanges_use_different_nonces(self, test_key_pair):
        transport = RecordingTransport([token_response(), token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()
        manager.invalidate()
        manager.get_token()

        first, second = transport.requests
        assert first.header("X-Nonce") != second.header("X-Nonce")


class TestResponseReading:
    @pytest.mark.parametrize("key", ["access_token", "accessToken", "token"])
    def test_every_published_token_spelling_is_read(self, test_key_pair, key):
        transport = RecordingTransport([json_response({key: "at_x", "expires_in": 600})])
        manager, _ = _manager(transport, test_key_pair[0])
        assert manager.get_token() == "at_x"

    def test_a_token_inside_the_standard_envelope_is_read(self, test_key_pair):
        transport = RecordingTransport(
            [json_response(envelope({"access_token": "at_wrapped", "expires_in": 600}))]
        )
        manager, _ = _manager(transport, test_key_pair[0])
        assert manager.get_token() == "at_wrapped"

    def test_a_response_without_a_token_raises_rather_than_caching_nothing(self, test_key_pair):
        transport = RecordingTransport([json_response({"token_type": "Bearer"})])
        manager, _ = _manager(transport, test_key_pair[0])
        with pytest.raises(ApiError, match="no access token"):
            manager.get_token()

    def test_a_401_becomes_an_authentication_error_carrying_the_code(self, test_key_pair):
        transport = RecordingTransport(
            [json_response({"code": "INVALID_SIGNATURE", "message": "nope"}, status_code=401)]
        )
        manager, _ = _manager(transport, test_key_pair[0])
        with pytest.raises(AuthenticationError) as caught:
            manager.get_token()
        assert caught.value.code == "INVALID_SIGNATURE"
        assert caught.value.status_code == 401

    def test_a_403_is_also_an_authentication_error(self, test_key_pair):
        transport = RecordingTransport(
            [json_response({"code": "IP_NOT_ALLOWED", "message": "blocked"}, status_code=403)]
        )
        manager, _ = _manager(transport, test_key_pair[0])
        with pytest.raises(AuthenticationError):
            manager.get_token()

    def test_a_transport_failure_is_not_retried_blindly(self, test_key_pair):
        """The nonce is spent and the time window is already running.

        Replaying the SAME signed request could be refused as a replay, so the
        failure surfaces and the caller's retry signs afresh.
        """
        transport = RecordingTransport([transport_failure("dns failure")])
        manager, _ = _manager(transport, test_key_pair[0], max_retries=5)
        with pytest.raises(ApiError, match="Token request failed"):
            manager.get_token()
        assert len(transport.requests) == 1


class TestCaching:
    def test_a_cached_token_is_reused_without_a_second_exchange(self, test_key_pair):
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])

        assert manager.get_token() == manager.get_token() == TEST_ACCESS_TOKEN
        assert len(transport.requests) == 1

    def test_invalidate_forces_a_fresh_exchange(self, test_key_pair):
        transport = RecordingTransport([token_response(), token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()
        manager.invalidate()
        manager.get_token()
        assert len(transport.requests) == 2

    def test_a_token_expiring_within_the_skew_window_is_treated_as_stale(self, test_key_pair):
        """A token fetched at the edge of its window can expire in flight.

        Storing a 10-second token must not hand it back: the skew is what keeps
        a request from failing with an unexplained 401.
        """
        store = InMemoryTokenStore()
        store.set("at_short", ttl_seconds=10)
        assert store.get() is None

    def test_a_comfortable_ttl_is_cached(self):
        store = InMemoryTokenStore()
        store.set("at_long", ttl_seconds=1800)
        assert store.get() == "at_long"

    def test_clear_empties_the_store(self):
        store = InMemoryTokenStore()
        store.set("at_long", ttl_seconds=1800)
        store.clear()
        assert store.get() is None

    def test_a_cold_start_burst_exchanges_exactly_one_token(self, test_key_pair):
        """Without the exchange lock, every thread fetches its own token."""
        transport = RecordingTransport([token_response()], default=token_response())
        manager, _ = _manager(transport, test_key_pair[0])

        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(manager.get_token())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == [TEST_ACCESS_TOKEN] * 8
        assert len(transport.requests) == 1

    def test_a_custom_store_is_used_instead_of_the_default(self, test_key_pair):
        class CountingStore:
            def __init__(self):
                self.reads = 0
                self.value = None

            def get(self):
                self.reads += 1
                return self.value

            def set(self, token, ttl_seconds):
                self.value = token

            def clear(self):
                self.value = None

        store = CountingStore()
        transport = RecordingTransport([token_response()])
        config = Configuration(base_url=BASE_URL, key_id=KEY_ID, transport=transport)
        manager = TokenManager(config, Ed25519Signer(test_key_pair[0]), store)

        manager.get_token()
        assert store.value == TEST_ACCESS_TOKEN
        assert store.reads >= 1


class TestSignatureShape:
    def test_the_signature_header_is_base64_of_64_bytes(self, test_key_pair):
        transport = RecordingTransport([token_response()])
        manager, _ = _manager(transport, test_key_pair[0])
        manager.get_token()
        assert len(base64.b64decode(transport.last.header("X-Signature"))) == 64
