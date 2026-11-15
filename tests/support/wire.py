"""Assertions on recorded requests shared by the table-driven product tests."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

from lunixi.auth.canonical_request import build_canonical_request
from lunixi.auth.ed25519_signer import verify_signature

SIGNATURE_HEADERS = ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature")


def assert_signed(request: Any, public_key: str) -> None:
    """The request carries a per-request signature that verifies over its canonical string."""
    for header in SIGNATURE_HEADERS:
        assert request.header(header), header
    canonical = build_canonical_request(
        request.method,
        request.path,
        request.header("X-Date"),
        request.header("X-Nonce"),
        request.header("Digest"),
    )
    assert verify_signature(public_key, request.header("X-Signature"), canonical) is True


def assert_unsigned(request: Any) -> None:
    """Bearer only: no signature header."""
    assert request.header("Authorization")
    for header in SIGNATURE_HEADERS:
        assert request.header(header) is None, header


def query_of(request: Any) -> Dict[str, List[str]]:
    return parse_qs(urlsplit(request.url).query)


def path_of(request: Any) -> str:
    return urlsplit(request.url).path


def body_of(request: Any) -> Any:
    return None if request.body is None else json.loads(request.body)
