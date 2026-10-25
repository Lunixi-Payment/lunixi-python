"""Test-only transport that records requests and replays queued responses.

NOT part of the package and never shipped: it lives under ``tests/`` because
the suite must verify what the SDK PUTS ON THE WIRE — the canonical string, the
digest, the headers, the serialized body — and that is only observable from the
transport seam. No test in this suite reaches the network.

A recorded request keeps the body as the EXACT string the SDK serialized, so a
test can re-derive the digest and the signature from it rather than from a dict
it re-serializes itself. Re-serializing in the test would hide the one defect
these tests exist to catch: a body serialized with whitespace, whose digest the
gateway rejects.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from lunixi.http.transport import HttpResponse, TransportError


class RecordedRequest:
    """One request the SDK handed to the transport."""

    __slots__ = ("method", "url", "headers", "body", "timeout")

    def __init__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[str],
        timeout: float,
    ) -> None:
        self.method = method
        self.url = url
        self.headers = dict(headers)
        self.body = body
        self.timeout = timeout

    def header(self, name: str) -> Optional[str]:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None

    @property
    def path(self) -> str:
        """The path and query, which is what gets signed."""
        for marker in ("://",):
            if marker in self.url:
                rest = self.url.split(marker, 1)[1]
                index = rest.find("/")
                return rest[index:] if index >= 0 else "/"
        return self.url

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return f"RecordedRequest({self.method} {self.path})"


class RecordingTransport:
    """Replays queued responses and records every request.

    Args:
        responses: Queued answers, consumed in order. Each is an
            :class:`~lunixi.http.transport.HttpResponse`, or a
            :class:`~lunixi.http.transport.TransportError` to simulate a
            request that never got an answer.
        default: Returned once the queue is empty. Without it an extra call
            raises, so a test that sends more requests than it queued fails
            loudly instead of silently reusing the last answer.
    """

    def __init__(
        self,
        responses: Optional[List[Any]] = None,
        default: Optional[HttpResponse] = None,
    ) -> None:
        self.queued: List[Any] = list(responses or [])
        self.default = default
        self.requests: List[RecordedRequest] = []

    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[str],
        timeout: float,
    ) -> HttpResponse:
        self.requests.append(RecordedRequest(method, url, headers, body, timeout))

        if self.queued:
            answer = self.queued.pop(0)
        elif self.default is not None:
            answer = self.default
        else:
            raise AssertionError(
                f"RecordingTransport ran out of queued responses at request "
                f"#{len(self.requests)}: {method} {url}"
            )

        if isinstance(answer, BaseException):
            raise answer
        return answer

    @property
    def last(self) -> RecordedRequest:
        return self.requests[-1]

    def requests_to(self, path_fragment: str) -> List[RecordedRequest]:
        return [request for request in self.requests if path_fragment in request.url]


def json_response(
    payload: Any,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
) -> HttpResponse:
    """Builds a JSON :class:`HttpResponse` for the queue."""
    import json

    body = json.dumps(payload).encode("utf-8")
    merged = {"content-type": "application/json"}
    merged.update(headers or {})
    return HttpResponse(status_code=status_code, headers=merged, body=body)


def envelope(data: Any, **extra: Any) -> Dict[str, Any]:
    """Wraps a payload the way the gateway does.

    🔴 Note what is NOT here: a ``success`` field. The gateway does not send
    one, so neither does this helper — a double that invented one would let a
    client reading ``response["success"]`` pass its tests and fail in
    production.
    """
    body: Dict[str, Any] = {
        "status": "success",
        "code": "SUCCESS",
        "message": "OK",
        "data": data,
        "statusCode": 200,
        "timestamp": "2026-10-11T08:30:00.000Z",
        "requestId": "req_0123456789abcdef",
    }
    body.update(extra)
    return body


def error_envelope(code: str, message: str, status_code: int = 400) -> Dict[str, Any]:
    """Wraps an error the way the gateway does."""
    return {
        "status": "error",
        "code": code,
        "message": message,
        "data": None,
        "statusCode": status_code,
        "timestamp": "2026-10-11T08:30:00.000Z",
        "requestId": "req_0123456789abcdef",
    }


def transport_failure(message: str = "connection reset") -> TransportError:
    """A transport failure to queue."""
    return TransportError(message)
