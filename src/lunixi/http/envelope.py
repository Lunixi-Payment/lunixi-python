"""The single reading point for the gateway response envelope.

Every successful response is wrapped::

    {
      "status": "success",          # "success" | "failure" | "partial"
      "code": "SUCCESS",
      "message": "...",
      "data": <payload>,
      "pageInfo": {...},            # list endpoints only — SIBLING of `data`
      "statusCode": 200,
      "timestamp": "2026-10-11T...",
      "requestId": "..."
    }

🔴 THERE IS NO ``success`` FIELD ON THE WIRE. The outcome lives in ``status``
as the string ``"success"``. A client written against ``response["success"]``
reads ``None`` on every single response — never an error, just a value that is
always falsy — so it either treats every call as failed or, worse, ignores the
check entirely. :func:`is_success` is the only correct reading and the reason
this module exists.

🔴 ``pageInfo`` IS A SIBLING OF ``data``, not nested inside it. List endpoints
return ``data`` as a bare array, so paging metadata cannot live inside it
without changing the shape of ``data`` for every existing client. Some
endpoints additionally keep a transitional copy at ``data.pageInfo``; the
canonical position is the top level and that is read first.
"""

from __future__ import annotations

from typing import Any, Dict, Generic, List, Mapping, Optional, TypeVar

__all__ = ["is_success", "data_of", "page_info_of", "items_of", "Page"]

T = TypeVar("T")

#: Collection keys that carry the rows of a list payload, in priority order.
_COLLECTION_KEYS = ("items", "operations", "rows", "results")


def is_success(response: Mapping[str, Any]) -> bool:
    """True when the envelope reports success.

    Reads ``status == "success"``. Never reads a ``success`` key: the gateway
    does not send one.

    A response with no ``status`` at all is treated as a success, because a
    failure always carries one — this keeps plain, unwrapped payloads usable.
    """
    status = response.get("status")
    if status is None:
        return True
    return status == "success"


def data_of(response: Any) -> Any:
    """Unwraps the payload.

    Returns ``response["data"]`` when the envelope is present, otherwise the
    response itself, so a plain payload passes through untouched.

    ``data`` is returned even when it is ``None``: for an endpoint that answers
    with no payload, ``None`` is the answer, and falling back to the envelope
    would hand the caller ``status``/``timestamp`` as if they were data.
    """
    if isinstance(response, Mapping) and "data" in response:
        return response["data"]
    return response


def page_info_of(response: Mapping[str, Any]) -> Dict[str, Any]:
    """Returns the paging metadata, from the envelope level first.

    Falls back to ``data.pageInfo`` for the endpoints that still publish the
    transitional copy there, then to an empty dict (an unpaged endpoint).
    """
    page_info = response.get("pageInfo") if isinstance(response, Mapping) else None
    if isinstance(page_info, Mapping):
        return dict(page_info)

    payload = data_of(response)
    if isinstance(payload, Mapping) and isinstance(payload.get("pageInfo"), Mapping):
        return dict(payload["pageInfo"])

    return {}


def items_of(response: Mapping[str, Any]) -> List[Any]:
    """Extracts the rows of a list response.

    Handles both shapes in circulation: a bare array in ``data``, and an object
    carrying a collection key. An unrecognised shape yields an empty list — an
    empty list is a valid answer, so raising here would turn "no rows" into a
    crash.
    """
    payload = data_of(response)
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, Mapping):
        for key in _COLLECTION_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
    return []


class Page(Generic[T]):
    """One page of a cursor-paginated list.

    Attributes:
        items: The rows of this page.
        has_more: Whether a further page exists.
        next_cursor: Opaque cursor for the next page, or ``None`` on the last
            page. ⚠️ Treat it as opaque: do not decode, build or edit it. A
            malformed cursor is rejected with ``400 INVALID_CURSOR``; it does
            not silently restart from the first page.
        total_count: Total rows matching the filter, and ``None`` unless the
            server actually counted them. Cursor paging leaves this unset by
            default because a filtered ``COUNT(*)`` is expensive. Use
            :attr:`next_cursor` to advance; ask for a total only when you
            genuinely need one.
    """

    __slots__ = ("items", "has_more", "next_cursor", "total_count", "raw")

    def __init__(self, response: Mapping[str, Any]) -> None:
        page_info = page_info_of(response)
        next_cursor = page_info.get("nextCursor") or page_info.get("endCursor")
        total_count = page_info.get("totalCount")

        self.items: List[T] = items_of(response)
        self.has_more: bool = bool(page_info.get("hasMore"))
        self.next_cursor: Optional[str] = (
            next_cursor if isinstance(next_cursor, str) and next_cursor != "" else None
        )
        self.total_count: Optional[int] = (
            total_count if isinstance(total_count, int) and not isinstance(total_count, bool) else None
        )
        self.raw: Mapping[str, Any] = response

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"Page(items={len(self.items)}, has_more={self.has_more}, "
            f"next_cursor={'set' if self.next_cursor else None})"
        )
