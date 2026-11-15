"""Identity signals — ``/api/v1/identity/*``, ``client.identity()``.

Bearer-only. The browser fingerprint SDK produces a ``traceId``; your server
reads the linked accounts of that trace and flags or blocks when the device is
shared ("one person, many accounts",
:func:`~lunixi.identity.values.is_identity_device_shared`).

This is a signal surface: it carries risk flags, reason codes, similarity
probabilities and the identity snapshot, not an allow / review / block verdict
(that is the fraud decision). Calls return the envelope's ``data``;
:meth:`IdentityClient.list_sessions` returns a :class:`~lunixi.http.envelope.Page`.
Bodies and filters are checked against
:data:`~lunixi.identity.values.IDENTITY_ROUTES` before sending.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .._routes import (
    compact,
    data_of,
    merge_request,
    plain_mapping,
    route_page,
    send_route,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from .values import IDENTITY_ROUTES

__all__ = ["IdentityClient"]

Request = Optional[Mapping[str, Any]]

_NESTED = ("customer", "device", "session", "source", "account", "metadata")


def _call(api: ApiClient, name: str, **options: Any) -> Any:
    return send_route(api, IDENTITY_ROUTES, name, **options)


class IdentityClient:
    """Device and account-linking signals of a browser trace."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def analyze_sync(self, request: Request = None, **fields: Any) -> Any:
        """Synchronous analysis: optional ``subjectType``, ``subjectId``, ``productContext``,
        ``integrationMode``, ``customer``, ``device``, ``session``, ``source``, ``account``,
        ``metadata``, ``paymentId``.

        Returns ``{traceId, analysisStatus, riskFlags, reasonCodes, identitySnapshot, …}``.
        """
        return data_of(_call(self._api, "analyzeSync", body=_analyze_body(request, fields)))

    def analyze(self, request: Request = None, **fields: Any) -> Any:
        """Queues the analysis and returns the ``traceId`` at once."""
        return data_of(_call(self._api, "analyze", body=_analyze_body(request, fields)))

    def account_links(self, trace_id: str) -> Any:
        """Other accounts seen on this device / fingerprint / IP (account keys hashed)."""
        return data_of(_call(self._api, "accountLinks", params={"traceId": trace_id}))

    def get_session(self, trace_id: str) -> Any:
        return data_of(_call(self._api, "getSession", params={"traceId": trace_id}))

    def related_sessions(self, trace_id: str, limit: Optional[int] = None) -> Any:
        """Recent sessions of the same device-identity cluster."""
        params = {"traceId": trace_id}
        query = compact({"limit": limit})
        return data_of(_call(self._api, "relatedSessions", params=params, query=query))

    def timeline(self, trace_id: str) -> Any:
        """Session summary and recorded lifecycle events."""
        return data_of(_call(self._api, "timeline", params={"traceId": trace_id}))

    def top_sources(self, **filters: Any) -> Any:
        """Source domains ranked by repeated risky activity; filters ``days``, ``limit``."""
        return data_of(_call(self._api, "topSources", query=filters))

    def list_sessions(self, **filters: Any) -> Page:
        """Filters: ``fingerprintId``, ``deviceId``, ``paymentId``, ``limit``."""
        return route_page(_call(self._api, "listSessions", query=filters))


def _analyze_body(request: Request, fields: Mapping[str, Any]) -> Dict[str, Any]:
    merged = merge_request(
        plain_mapping(request, "analyze request") if request is not None else None, fields
    )
    body = compact(wire_fields(merged, "analyze request"))
    for field in _NESTED:
        if body.get(field) is not None:
            plain_mapping(body[field], field)
    if ("subjectType" in body) != ("subjectId" in body):
        raise ConfigurationError("subjectType and subjectId go together.")
    return body
