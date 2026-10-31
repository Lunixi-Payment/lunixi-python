"""HTTP transport: the one place a request leaves the process.

The transport is an injectable seam. The default implementation uses the
standard library, so installing this package pulls in no HTTP dependency; an
application that already standardises on ``requests`` or ``httpx`` — for
connection pooling, proxies or tracing — supplies its own
:class:`HttpTransport` and the rest of the SDK is unchanged.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional
from urllib.parse import quote, urlencode

import rfc8785

from ..errors import ConfigurationError
from ..validation import SAFE_INTEGER, gateway_path

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

    def emit(value: Any, depth: int = 0) -> str:
        if depth > 32:
            raise ConfigurationError("JSON nesting exceeds the supported depth.")
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                raise ConfigurationError("JSON object keys must be strings.")
            numeric = sorted(
                (
                    k
                    for k in value
                    if len(k) <= 10
                    and k.isascii()
                    and k.isdigit()
                    and str(int(k)) == k
                    and int(k) < 4294967295
                ),
                key=int,
            )
            keys = numeric + [k for k in value if k not in numeric]
            return (
                "{"
                + ",".join(
                    rfc8785.dumps(k).decode() + ":" + emit(value[k], depth + 1) for k in keys
                )
                + "}"
            )
        if isinstance(value, (list, tuple)):
            return "[" + ",".join(emit(v, depth + 1) for v in value) + "]"
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > SAFE_INTEGER:
            raise ConfigurationError("JSON integers must be JavaScript-safe.")
        try:
            return rfc8785.dumps(value).decode("utf-8")
        except (rfc8785.CanonicalizationError, TypeError, ValueError):
            raise ConfigurationError("Unsupported or non-finite JSON value.") from None

    result = emit(body)
    if len(result.encode("utf-8")) > 1024 * 1024:
        raise ConfigurationError("JSON request exceeds the 1 MiB limit.")
    return result


def build_path(path: str, query: Optional[Mapping[str, Any]] = None) -> str:
    """Appends a query string, dropping empty values.

    The result is both signed and sent, so it is built once here. ``None`` and
    ``""`` are dropped rather than sent as empty parameters, which some filters
    would read as "match the empty string" instead of "no filter".
    """
    gateway_path(path)
    if not query:
        return path
    pairs = []
    for key, value in query.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item is not None and item != "":
                pairs.append(
                    (str(key), "true" if item is True else "false" if item is False else str(item))
                )
    suffix = urlencode(pairs)
    return gateway_path(path + ("&" if "?" in path else "?") + suffix) if suffix else path


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
        except (ValueError, OverflowError):
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

    def __init__(
        self,
        *,
        max_response_bytes: int = 8 * 1024 * 1024,
        ssl_context: Optional[ssl.SSLContext] = None,
    ) -> None:
        if ssl_context is not None and (
            ssl_context.verify_mode != ssl.CERT_REQUIRED or not ssl_context.check_hostname
        ):
            raise ConfigurationError(
                "TLS certificate and hostname verification must remain enabled."
            )
        self.max_response_bytes = max_response_bytes
        self._ssl_context = ssl_context

    def _read(self, response: Any) -> bytes:
        value = response.read(self.max_response_bytes + 1)
        if len(value) > self.max_response_bytes:
            raise TransportError("Gateway response exceeds the configured limit.")
        return value

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

        opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=self._ssl_context)
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=self._read(response),
                )
        except urllib.error.HTTPError as error:
            # An error status is an answer, not a transport failure.
            return HttpResponse(
                status_code=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=self._read(error),
            )
        except Exception:  # URLError, socket.timeout, ssl errors
            raise TransportError("Gateway transport failed.") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None
