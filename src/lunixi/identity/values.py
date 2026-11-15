"""Identity (device and account-linking signals) — ``/api/v1/identity/*``.

:data:`IDENTITY_ROUTES` describes every route the client calls; it is the same
table as the Node SDK's ``IDENTITY_ROUTES`` and the shared catalog
(``contracts/products/identity.json``). The surface is bearer-only; the browser
fingerprint SDK uses the publishable key (``/identity/sdk/init``), which is not
here.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from .._routes import freeze_routes

__all__ = [
    "IDENTITY_ANALYZE_FIELDS",
    "IDENTITY_ROUTES",
    "is_identity_device_shared",
    "identity_link_reasons",
]

_LIVE = "/api/v1/identity/live-sessions"

#: Body of ``analyze`` / ``analyze_sync``; the nested objects are forwarded as given.
IDENTITY_ANALYZE_FIELDS = (
    "subjectType",
    "subjectId",
    "productContext",
    "integrationMode",
    "customer",
    "device",
    "session",
    "source",
    "account",
    "metadata",
    "paymentId",
)


def _route(method: str, path: str, **extra: Any) -> Mapping[str, Any]:
    return {"method": method, "path": path, "stepUp": False, "idempotencyKey": "none", **extra}


#: Every route the identity client calls (Node ``IDENTITY_ROUTES``).
IDENTITY_ROUTES = freeze_routes(
    {
        "analyzeSync": _route(
            "POST", f"{_LIVE}/analyze-sync", optional=list(IDENTITY_ANALYZE_FIELDS)
        ),
        "analyze": _route("POST", f"{_LIVE}/analyze", optional=list(IDENTITY_ANALYZE_FIELDS)),
        "accountLinks": _route("GET", f"{_LIVE}/:traceId/account-links"),
        "getSession": _route("GET", f"{_LIVE}/:traceId"),
        "relatedSessions": _route("GET", f"{_LIVE}/:traceId/related-sessions", query=["limit"]),
        "timeline": _route("GET", f"{_LIVE}/:traceId/timeline"),
        "topSources": _route("GET", f"{_LIVE}/top-sources", query=["days", "limit"]),
        "listSessions": _route(
            "GET", _LIVE, query=["fingerprintId", "deviceId", "paymentId", "limit"]
        ),
    }
)


def is_identity_device_shared(account_links: Any, threshold: int = 2) -> bool:
    """True when the device of an ``account_links()`` answer is shared by at least
    ``threshold`` accounts, counting the current one (``linkedAccounts`` excludes it).

    With the default 2, a second account on the device trips it.
    """
    linked = account_links.get("linkedAccounts") if isinstance(account_links, Mapping) else None
    count = len(linked) if isinstance(linked, list) else 0
    return count + 1 >= max(2, threshold)


def identity_link_reasons(account_links: Any) -> List[str]:
    """The distinct ``linkReasons`` of an ``account_links()`` answer's sessions, in order
    (``same_device_cluster``, ``same_fingerprint`` …)."""
    sessions = account_links.get("sessions") if isinstance(account_links, Mapping) else None
    reasons: List[str] = []
    for session in sessions if isinstance(sessions, list) else []:
        values = session.get("linkReasons") if isinstance(session, Mapping) else None
        for reason in values if isinstance(values, list) else []:
            if str(reason) not in reasons:
                reasons.append(str(reason))
    return reasons
