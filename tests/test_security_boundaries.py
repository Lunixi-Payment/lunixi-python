from __future__ import annotations

import ipaddress
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lunixi import (
    ApiError,
    Configuration,
    ConfigurationError,
    Ed25519Signer,
    LunixiClient,
    WebhookVerificationError,
)
from lunixi.http.transport import UrllibTransport
from tests.support.recording_transport import error_envelope, json_response
from tests.test_commerce import fresh_event


@pytest.mark.parametrize(
    "url",
    [
        "http://api-gateway.lunixi.com",
        "http://127.0.0.1",
        "https://user@host",
        "https://@host",
        "https://host/path",
        "https://host?",
        "https://host#",
        "https://host:99999",
        "https://host\\evil",
    ],
)
def test_unsafe_origins_are_rejected(url):
    with pytest.raises(ConfigurationError):
        Configuration(base_url=url, key_id="kid")


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/api/v1/x",
        "//evil.example/x",
        "/api/v1/../x",
        "/api/v1/%2e%2e/x",
        "/api/v1/%252e%252e/x",
        "/api/v1/x#fragment",
        "/api/panel/v1/x",
    ],
)
def test_path_escape_is_rejected_before_auth(client_factory, path):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.api().request("GET", path)
    assert transport.requests == []


def test_loopback_http_is_explicit_and_numeric():
    assert Configuration(
        base_url="http://127.0.0.1:1234", key_id="kid", allow_loopback_http=True
    ).base_url.startswith("http://127.")
    with pytest.raises(ConfigurationError):
        Configuration(base_url="http://localhost", key_id="kid", allow_loopback_http=True)


def test_bad_headers_limits_and_tls_cannot_disable_verification():
    for values in (
        {"key_id": "a\r\nInjected:true"},
        {"timeout_seconds": float("nan")},
        {"max_retries": 6},
        {"max_response_bytes": 2},
        {"user_agent": "bad\nagent"},
    ):
        kwargs = {"base_url": "https://safe.example", "key_id": "kid", **values}
        with pytest.raises(ConfigurationError):
            Configuration(**kwargs)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    with pytest.raises(ConfigurationError):
        UrllibTransport(ssl_context=context)


def test_error_text_does_not_reflect_response_secrets(client_factory):
    secret = "at_live_PRIVATE_RESPONSE_SECRET"
    transport, client = client_factory(
        json_response(error_envelope("BAD", secret), status_code=400)
    )
    with pytest.raises(ApiError) as caught:
        client.api().request("GET", "/api/v1/payments")
    assert secret not in str(caught.value) and secret not in repr(caught.value)
    assert caught.value.response is None


def test_unkeyed_401_write_is_not_replayed(client_factory):
    transport, client = client_factory(
        json_response(error_envelope("TOKEN_EXPIRED", "expired"), status_code=401)
    )
    with pytest.raises(ApiError):
        client.api().request("POST", "/api/v1/fraud/decisions/evaluate", {})
    assert len(transport.requests_to("/fraud/decisions/evaluate")) == 1


def test_seed_public_export_is_validated(signature_vectors):
    from lunixi import SignatureError

    raw = bytearray.fromhex(signature_vectors["seedAndPublicHex"])
    raw[-1] ^= 1
    with pytest.raises(SignatureError):
        Ed25519Signer(bytes(raw))


def test_signed_event_id_type_and_rotation_binding():
    from lunixi import WebhookVerifier

    raw, headers = fresh_event("pi_one", "order", secret="synthetic_previous_secret_0123456789")
    verifier = WebhookVerifier(
        ["synthetic_new_secret_0123456789", "synthetic_previous_secret_0123456789"]
    )
    assert verifier.verify(raw, headers).raw_body_hash
    for key, value in [
        ("x-lunixi-event-id", "different"),
        ("x-lunixi-event-type", "payment.failed"),
    ]:
        bad = dict(headers)
        bad[key] = value
        with pytest.raises(WebhookVerificationError):
            verifier.verify(raw, bad)


@pytest.fixture
def tls_gateway(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate = tmp_path / "cert.pem"
    private = tmp_path / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append((self.path, dict(self.headers)))
            body = b'{"access_token":"at_SYNTHETIC_TLS","expires_in":1800}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            calls.append((self.path, dict(self.headers)))
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/secret-destination")
                self.end_headers()
            else:
                body = b"x" * 2048
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    trusted = ssl.create_default_context(cafile=str(certificate))
    try:
        yield "https://127.0.0.1:" + str(server.server_port), trusted, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_https_redirect_and_response_bounds(tls_gateway, signature_vectors):
    origin, context, calls = tls_gateway
    client = LunixiClient(
        base_url=origin,
        key_id="mk_test",
        private_key=signature_vectors["privateKeyPem"],
        transport=UrllibTransport(ssl_context=context, max_response_bytes=1024),
        max_response_bytes=1024,
        max_retries=0,
    )
    with pytest.raises(ApiError):
        client.api().request("GET", "/api/v1/payments/redirect")
    assert len(calls) == 2 and all("secret-destination" not in p for p, _ in calls)
    with pytest.raises(ApiError):
        client.api().request("GET", "/api/v1/payments/large")
    assert len(calls) == 3
