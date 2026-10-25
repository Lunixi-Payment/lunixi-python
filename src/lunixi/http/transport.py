"""HTTP transport: the one place a request leaves the process.

The transport is an injectable seam. The default implementation uses the
standard library, so installing this package pulls in no HTTP dependency; an
application that already standardises on ``requests`` or ``httpx`` — for
connection pooling, proxies or tracing — supplies its own
:class:`HttpTransport` and the rest of the SDK is unchanged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional
from urllib.parse import quote, urlencode

try:  # Python 3.8+
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover - unreachable on supported versions
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[assignment]

__all__ = [
    "HttpResponse",
    "HttpTransport",
    "UrllibTransport",
    "TransportError",
    "serialize_body",
    "build_path",
]


class TransportError(Exception):
    """The request never produced an HTTP response (DNS, TCP, TLS, timeout).

    Distinct from an HTTP error status: a transport failure may be safe to
    retry for an idempotent call, whereas a 4xx answer is a decision.
    """


def serialize_body(body: Any) -> Optional[str]:
    """Serializes a request body to the EXACT string that is signed and sent.

    🔴 ``separators=(",", ":")`` is a correctness requirement, not a style
    choice. The gateway validates the ``Digest`` header by re-serializing the
    body it parsed with a serializer that emits no whitespace. A body with the
    default ``", "`` / ``": "`` separators hashes differently and the request is
    refused with ``INVALID_DIGEST``.

    ``ensure_ascii=False`` keeps non-ASCII characters as UTF-8 rather than
    ``\\uXXXX`` escapes, matching the gateway's serializer; the digest is taken
    over the UTF-8 bytes of this string.
    """
    if body is None:
        return None
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def build_path(path: str, query: Optional[Mapping[str, Any]] = None) -> str:
    """Appends a query string, dropping empty values.

    The result is both signed and sent, so it is built once here. ``None`` and
    ``""`` are dropped rather than sent as empty parameters, which some filters
    would read as "match the empty string" instead of "no filter".
    """
    if not query:
        return path
    pairs = [
        (key, str(value))
        for key, value in query.items()
        if value is not None and value != ""
    ]
    if not pairs:
        return path
    return f"{path}?{urlencode(pairs)}"


def encode_path_segment(value: str) -> str:
    """Percent-encodes one path segment (a trace id, an identifier)."""
    return quote(value, safe="")


class HttpResponse:
    """One HTTP response: status, headers and raw body bytes.

    Headers are matched case-insensitively — header case is not guaranteed by
    any HTTP version and a case-sensitive lookup is a bug that only shows up
    behind a particular proxy.
    """

    __slots__ = ("status_code", "_headers", "body")

    def __init__(self, status_code: int, headers: Mapping[str, str], body: bytes) -> None:
        self.status_code = status_code
        self._headers = {str(key).lower(): str(value) for key, value in headers.items()}
        self.body = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def header(self, name: str) -> Optional[str]:
        return self._headers.get(name.lower())

    def int_header(self, name: str) -> Optional[int]:
        """Returns a header as an int, or ``None`` when absent or unparsable.

        An unparsable value yields ``None`` rather than a guess: a client that
        invented a ``Retry-After`` would retry at the wrong rate.
        """
        raw = self.header(name)
        if raw is None or raw.strip() == "":
            return None
        try:
            return int(float(raw.strip()))
        except ValueError:
            return None

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Dict[str, Any]:
        """Decodes the body as a JSON object.

        A body that is empty, or is not a JSON object, yields a dict rather
        than raising — an error path must stay readable even when a proxy
        returns an HTML page instead of the gateway's envelope.
        """
        text = self.text()
        if text.strip() == "":
            return {}
        try:
            decoded = json.loads(text)
        except ValueError:
            return {"message": text}
        if isinstance(decoded, dict):
            return decoded
        return {"data": decoded}


@runtime_checkable
class HttpTransport(Protocol):
    """The seam an application implements to supply its own HTTP stack."""

    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[str],
        timeout: float,
    ) -> HttpResponse:
        """Sends one request and returns the response.

        Must NOT raise for a non-2xx status — return it. Raise
        :class:`TransportError` only when no response was received.
        """
        ...  # pragma: no cover - protocol declaration


class UrllibTransport:
    """Default transport, built on :mod:`urllib.request` from the stdlib.

    Redirects are not followed: a redirect would drop the signed path, and the
    signature is bound to the exact path that was signed.
    """

    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[str],
        timeout: float,
    ) -> HttpResponse:
        data = body.encode("utf-8") if body is not None else None
        request = urllib.request.Request(url=url, data=data, method=method.upper())
        for key, value in headers.items():
            request.add_header(key, value)

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            # An error status is an answer, not a transport failure.
            return HttpResponse(
                status_code=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read() or b"",
            )
        except Exception as error:  # URLError, socket.timeout, ssl errors
            raise TransportError(str(error) or error.__class__.__name__) from error


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None
