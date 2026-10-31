"""Shared fixtures.

Every credential in this suite is generated here or read from
``tests/fixtures/``. No real key, secret or account identifier appears in any
test. Only the transport security fixture opens a local HTTPS listener.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict

import pytest

from integrations.common import Orders, Settings
from lunixi.auth.ed25519_signer import generate_key_pair
from lunixi.client import LunixiClient

from .support.payment_gateway import PaymentGateway
from .support.recording_transport import RecordingTransport, envelope, json_response

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"

BASE_URL = "https://gateway.test.invalid"
KEY_ID = "kid_test_0123456789"

#: A fake bearer token the token endpoint hands out in these tests.
TEST_ACCESS_TOKEN = "at_test_000000000000000000000000"


@pytest.fixture(scope="session")
def signature_vectors() -> Dict[str, Any]:
    """Ed25519 / canonical-string / digest vectors with their synthetic key."""
    return json.loads((FIXTURE_DIR / "signature-vectors.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def webhook_vectors() -> Any:
    """v2 webhook vectors, shared with the other language SDKs."""
    return json.loads((FIXTURE_DIR / "webhook-v2-vectors.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def test_key_pair() -> "tuple[str, str]":
    """A freshly generated keypair, so no test depends on a committed key."""
    return generate_key_pair()


def token_response() -> Any:
    """The queued answer for ``POST /api/v1/auth/token``."""
    return json_response(
        {
            "access_token": TEST_ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 1800,
            "session_id": "authsess_test",
        }
    )


def make_client(transport: RecordingTransport, private_key: str, **kwargs: Any) -> LunixiClient:
    """Builds a client wired to a recording transport."""
    return LunixiClient(
        base_url=BASE_URL,
        key_id=KEY_ID,
        private_key=private_key,
        transport=transport,
        **kwargs,
    )


@pytest.fixture
def client_factory(test_key_pair):
    """Returns ``(transport, client)`` with the token exchange pre-queued.

    The first queued response is always the token exchange, because every
    authenticated call triggers it on a cold cache — a test that forgets it
    would see its own expected response consumed by the token request.
    """
    private_key, _ = test_key_pair

    def build(*responses: Any, **kwargs: Any):
        transport = RecordingTransport([token_response(), *responses])
        return transport, make_client(transport, private_key, **kwargs)

    return build


__all__ = [
    "BASE_URL",
    "KEY_ID",
    "TEST_ACCESS_TOKEN",
    "FIXTURE_DIR",
    "envelope",
    "json_response",
    "make_client",
    "token_response",
]


@pytest.fixture
def payment_setup(tmp_path, signature_vectors):
    gateway = PaymentGateway()
    client = LunixiClient(
        base_url="https://api-gateway.lunixi.com",
        key_id="mk_test",
        private_key=signature_vectors["privateKeyPem"],
        transport=gateway,
        max_retries=0,
    )
    settings = Settings(
        "https://testserver",
        "merchant_test",
        "synthetic_webhook_secret_0123456789",
        "synthetic_session_secret_0123456789_separate",
        b"t" * 32,
        str(tmp_path / "orders.sqlite3"),
    )
    orders = Orders(settings, client)
    orders.install()
    return orders, gateway
