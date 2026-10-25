"""The canonical string that is Ed25519-signed, and the body digest.

Both are byte-for-byte contracts with the gateway. Any drift here makes every
signed request fail with ``INVALID_SIGNATURE`` or ``INVALID_DIGEST``, and the
failure gives no hint about which byte differed — which is why this module is
tiny, free of options, and locked by vector tests.

Canonical string::

    <METHOD>\\n
    <URL>\\n
    X-Date:<value>\\n
    X-Nonce:<value>
    [\\nDigest:<value>]      # appended ONLY when a body digest is present

The URL is the path exactly as sent, INCLUDING the ``/api/v1`` prefix and any
query string. Signing a different string than the one sent on the wire is the
most common cause of a rejected signature.
"""

from __future__ import annotations

import base64
import hashlib

__all__ = [
    "HEADER_KEY_ID",
    "HEADER_DATE",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_DIGEST",
    "DIGEST_PREFIX",
    "build_canonical_request",
    "digest_for_body",
]

HEADER_KEY_ID = "X-Key-Id"
HEADER_DATE = "X-Date"
HEADER_NONCE = "X-Nonce"
HEADER_SIGNATURE = "X-Signature"
HEADER_DIGEST = "Digest"

#: Body digest prefix the gateway expects: ``SHA-256=<base64(sha256(body))>``.
DIGEST_PREFIX = "SHA-256="


def build_canonical_request(
    method: str,
    url: str,
    date: str,
    nonce: str,
    digest: "str | None" = None,
) -> str:
    """Builds the canonical string for one request.

    Args:
        method: HTTP method in any case; upper-cased here.
        url: The path as sent, with the ``/api/v1`` prefix and query string.
        date: ``X-Date`` header value (ISO-8601, UTC).
        nonce: ``X-Nonce`` header value, unique per request.
        digest: ``Digest`` header value when a body is sent, else ``None``.
            The ``Digest`` line is omitted entirely for a bodyless request,
            exactly as the gateway omits it.
    """
    lines = [
        method.upper(),
        url,
        f"{HEADER_DATE}:{date}",
        f"{HEADER_NONCE}:{nonce}",
    ]
    if digest:
        lines.append(f"{HEADER_DIGEST}:{digest}")
    return "\n".join(lines)


def digest_for_body(raw_body: "str | bytes | None") -> "str | None":
    """Returns the ``Digest`` header value for a serialized body.

    🔴 The argument must be the EXACT bytes that go on the wire.

    The gateway re-serializes the body it parsed and hashes that, with a
    serializer that emits no whitespace between tokens. A body serialized with
    spaces — which is what :func:`json.dumps` produces by default — hashes to a
    different value and is refused with ``INVALID_DIGEST``. This is why every
    body in this package is serialized through
    :func:`lunixi.http.transport.serialize_body`, never with a bare
    ``json.dumps``.
    """
    if raw_body is None:
        return None
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    if not body:
        return None
    return DIGEST_PREFIX + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
