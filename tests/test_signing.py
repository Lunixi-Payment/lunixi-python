"""Canonical string, body digest and Ed25519 signature — against fixed vectors.

These are the byte-for-byte contracts with the gateway. A vector test is the
only kind that catches drift here: a hand-rolled assertion would be written
from the same misunderstanding as the code it checks.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from lunixi.auth.canonical_request import build_canonical_request, digest_for_body
from lunixi.auth.ed25519_signer import Ed25519Signer, generate_key_pair, verify_signature
from lunixi.errors import SignatureError
from lunixi.http.transport import serialize_body


def _case(vectors, name):
    for case in vectors["cases"]:
        if case["name"] == name:
            return case
    raise AssertionError(f"No vector named {name!r}")


def _names(vectors):
    return [case["name"] for case in vectors["cases"]]


class TestCanonicalString:
    def test_every_vector_reproduces_its_canonical_string(self, signature_vectors):
        for case in signature_vectors["cases"]:
            built = build_canonical_request(
                case["method"], case["url"], case["date"], case["nonce"], case["digest"]
            )
            assert built == case["canonical"], case["name"]

    def test_a_bodyless_request_has_no_digest_line(self, signature_vectors):
        case = _case(signature_vectors, "token-exchange-no-body")
        canonical = build_canonical_request(
            case["method"], case["url"], case["date"], case["nonce"], None
        )
        assert "Digest:" not in canonical
        assert canonical.count("\n") == 3

    def test_the_digest_line_is_appended_last(self, signature_vectors):
        case = _case(signature_vectors, "event-ingest-compact-body")
        lines = case["canonical"].split("\n")
        assert lines[0] == "POST"
        assert lines[1] == case["url"]
        assert lines[2].startswith("X-Date:")
        assert lines[3].startswith("X-Nonce:")
        assert lines[4] == f"Digest:{case['digest']}"

    def test_the_method_is_upper_cased(self):
        assert build_canonical_request("post", "/x", "d", "n").startswith("POST\n")

    def test_the_signed_url_keeps_its_query_string(self, signature_vectors):
        case = _case(signature_vectors, "list-with-query-string-in-signed-url")
        # Signing the bare path while sending the query string is the classic
        # rejected-signature bug; the URL line must hold both.
        assert "?" in case["canonical"].split("\n")[1]
        assert build_canonical_request(
            case["method"], case["url"], case["date"], case["nonce"]
        ) == case["canonical"]

    def test_an_empty_digest_argument_adds_no_line(self):
        assert "Digest" not in build_canonical_request("GET", "/x", "d", "n", "")


class TestBodyDigest:
    def test_every_vector_reproduces_its_digest(self, signature_vectors):
        for case in signature_vectors["cases"]:
            assert digest_for_body(case["body"]) == case["digest"], case["name"]

    def test_the_prefix_and_base64_shape_are_the_gateways(self, signature_vectors):
        case = _case(signature_vectors, "event-ingest-compact-body")
        digest = digest_for_body(case["body"])
        assert digest.startswith("SHA-256=")
        raw = base64.b64decode(digest[len("SHA-256=") :])
        assert raw == hashlib.sha256(case["body"].encode()).digest()
        assert len(raw) == 32

    def test_a_spaced_body_digests_differently_than_the_compact_one(self, signature_vectors):
        """🔴 The defect this whole module exists to prevent.

        `json.dumps` with its default separators produces a body whose digest
        does not match what the gateway computes, and the request is refused
        with INVALID_DIGEST. The two vectors hold the SAME object in both
        serializations; their digests must differ, and the SDK's serializer must
        produce the compact one.
        """
        compact = _case(signature_vectors, "event-ingest-compact-body")
        spaced = _case(signature_vectors, "event-ingest-spaced-body-is-a-different-digest")

        assert compact["digest"] != spaced["digest"]
        assert compact["signature"] != spaced["signature"]

        import json

        event = json.loads(compact["body"])
        assert serialize_body(event) == compact["body"]
        assert json.dumps(event) == spaced["body"]
        assert digest_for_body(serialize_body(event)) == compact["digest"]

    def test_a_non_ascii_body_is_digested_over_its_utf8_bytes(self, signature_vectors):
        case = _case(signature_vectors, "unicode-body-digest-over-utf8-bytes")
        assert "Ş" in case["body"]
        assert digest_for_body(case["body"]) == case["digest"]
        assert digest_for_body(case["body"].encode("utf-8")) == case["digest"]

    def test_no_body_and_an_empty_body_produce_no_digest(self):
        assert digest_for_body(None) is None
        assert digest_for_body("") is None
        assert digest_for_body(b"") is None


class TestEd25519Signer:
    def test_every_vector_reproduces_its_signature(self, signature_vectors):
        signer = Ed25519Signer(signature_vectors["privateKeyPem"])
        for case in signature_vectors["cases"]:
            assert signer.sign(case["canonical"]) == case["signature"], case["name"]

    def test_a_signature_is_64_bytes_of_base64(self, signature_vectors):
        signer = Ed25519Signer(signature_vectors["privateKeyPem"])
        assert len(base64.b64decode(signer.sign("anything"))) == 64

    @pytest.mark.parametrize(
        "field",
        ["privateKeyPem", "pkcs8DerBase64", "seedBase64", "seedHex", "seedAndPublicHex"],
    )
    def test_every_accepted_key_shape_yields_the_same_signature(self, signature_vectors, field):
        """A merchant may hold the key as a PEM, as DER, or as a bare seed.

        All five shapes must load to the SAME key: a shape that quietly loaded
        a different key would sign valid-looking requests that fail
        verification.
        """
        canonical = signature_vectors["cases"][0]["canonical"]
        expected = signature_vectors["cases"][0]["signature"]
        assert Ed25519Signer(signature_vectors[field]).sign(canonical) == expected

    def test_a_hex_seed_is_not_misread_as_base64(self, signature_vectors):
        """A 64-character hex seed is also valid base64.

        Decoding it as base64 yields 48 unrelated bytes; without the hex-first
        rule this key shape loads a different key and every signature fails.
        """
        seed_hex = signature_vectors["seedHex"]
        assert len(seed_hex) == 64
        assert len(base64.b64decode(seed_hex)) == 48  # the wrong reading
        assert Ed25519Signer(seed_hex).public_key_pem() == signature_vectors["publicKeyPem"]

    def test_the_public_key_is_derived_from_the_private_key(self, signature_vectors):
        signer = Ed25519Signer(signature_vectors["privateKeyPem"])
        assert signer.public_key_pem().strip() == signature_vectors["publicKeyPem"].strip()

    def test_the_private_key_does_not_appear_in_repr(self, signature_vectors):
        signer = Ed25519Signer(signature_vectors["privateKeyPem"])
        text = repr(signer)
        assert "BEGIN PRIVATE KEY" not in text
        assert signature_vectors["seedHex"] not in text

    @pytest.mark.parametrize("value", ["", "   ", None, 42])
    def test_an_empty_or_non_string_key_is_refused(self, value):
        with pytest.raises(SignatureError):
            Ed25519Signer(value)

    def test_a_truncated_key_is_refused_rather_than_padded(self):
        with pytest.raises(SignatureError, match="Unsupported Ed25519 private key"):
            Ed25519Signer(base64.b64encode(b"\x01" * 20).decode())

    def test_an_rsa_pem_is_refused_with_a_clear_message(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_pem = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            .decode()
        )
        with pytest.raises(SignatureError, match="not an Ed25519 key"):
            Ed25519Signer(rsa_pem)

    def test_a_generated_pair_round_trips_through_verification(self):
        private_pem, public_pem = generate_key_pair()
        canonical = build_canonical_request("POST", "/api/v1/auth/token", "d", "n")
        signature = Ed25519Signer(private_pem).sign(canonical)

        assert verify_signature(public_pem, signature, canonical) is True
        # A single changed byte in the signed string must fail verification —
        # otherwise the canonical string would not actually be binding.
        assert verify_signature(public_pem, signature, canonical + " ") is False

    def test_a_signature_from_another_key_does_not_verify(self, signature_vectors):
        other_private, _ = generate_key_pair()
        canonical = signature_vectors["cases"][0]["canonical"]
        signature = Ed25519Signer(other_private).sign(canonical)
        assert verify_signature(signature_vectors["publicKeyPem"], signature, canonical) is False


class TestSerializeBody:
    def test_separators_are_compact(self):
        assert serialize_body({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_non_ascii_is_not_escaped(self):
        assert serialize_body({"name": "Şükrü"}) == '{"name":"Şükrü"}'

    def test_none_serializes_to_none_not_to_the_string_null(self):
        # "null" would be sent as a body and digested, so a bodyless request
        # must produce no string at all.
        assert serialize_body(None) is None

    def test_an_array_body_is_supported(self):
        assert serialize_body([{"eventId": "evt-1"}]) == '[{"eventId":"evt-1"}]'

    def test_nan_is_refused_rather_than_sent_as_invalid_json(self):
        with pytest.raises(ValueError):
            serialize_body({"amount": float("nan")})
