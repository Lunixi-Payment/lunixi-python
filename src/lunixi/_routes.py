"""Shared pieces of the table-driven clients.

Each table-driven product (wallet, bank-connect, sanction, insurance,
subscriptions, KYC, identity, marketplace) keeps ONE route table in its
``values`` module — the same table as the Node SDK and the shared catalog
(``contracts/products``) — and a caller that checks a call against it before
anything is sent. This module holds what the callers share: the frozen table,
request-field key handling (``snake_case`` keyword arguments become the
camelCase wire names), path filling, cursor paging, and :func:`send_route`,
the caller of the subscriptions, KYC, identity and marketplace tables.
"""

from __future__ import annotations

import datetime as _dt
import re
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterator, Mapping, Optional

from .errors import ConfigurationError
from .http.envelope import Page, data_of, page_info_of
from .http.transport import encode_path_segment
from .validation import validate_wire_money

__all__ = [
    "freeze_routes",
    "camel",
    "wire_fields",
    "merge_request",
    "path_segment",
    "fill_path",
    "compact",
    "present",
    "cursor_page",
    "items_page",
    "iso_time",
    "epoch_seconds",
    "currency_text",
    "page_limit",
    "cursor_text",
    "text",
    "paginate",
    "data_of",
    "send_route",
    "idempotency_key_of",
    "check_value",
    "optional_text",
    "plain_mapping",
    "merge_root",
    "route_page",
]

_CURRENCY = re.compile(r"[A-Z]{3}")


def freeze_routes(table: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Mapping[str, Any]]:
    """A read-only copy of a route table: field lists become tuples."""

    def freeze(route: Mapping[str, Any]) -> Mapping[str, Any]:
        items = route.items()
        return MappingProxyType({key: tuple(v) if isinstance(v, list) else v for key, v in items})

    return MappingProxyType({name: freeze(route) for name, route in table.items()})


def camel(name: str) -> str:
    """``kyc_level_cache`` → ``kycLevelCache``; a camelCase name is returned as it is."""
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def wire_fields(value: Any, label: str) -> Dict[str, Any]:
    """A request mapping with its keys as wire names; the same field given twice is refused."""
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be a mapping.")
    out: Dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigurationError(f"{label} keys must be strings.")
        wire = camel(key) if "_" in key else key
        if wire in out:
            raise ConfigurationError(f"{label} field {wire} is given twice.")
        out[wire] = item
    return out


def merge_request(
    request: Optional[Mapping[str, Any]], fields: Mapping[str, Any]
) -> Dict[str, Any]:
    """``request`` mapping plus keyword fields; a field in both is refused."""
    if request is not None and not isinstance(request, Mapping):
        raise ConfigurationError("request must be a mapping.")
    merged: Dict[str, Any] = dict(request or {})
    overlap = sorted(set(merged) & set(fields))
    if overlap:
        raise ConfigurationError(
            "Field(s) given both in the request mapping and as keyword arguments: "
            + ", ".join(overlap)
            + "."
        )
    merged.update(fields)
    return merged


def path_segment(value: Any, name: str) -> str:
    """One path identifier, trimmed and percent-encoded; blank is refused."""
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{name} is required.")
    return encode_path_segment(value.strip())


def fill_path(template: str, params: Mapping[str, Any]) -> str:
    """Fills the ``:name`` segments of a route path template."""
    segments = []
    for segment in template.split("/"):
        if segment.startswith(":"):
            name = segment[1:]
            segments.append(path_segment(params.get(name), name))
        else:
            segments.append(segment)
    return "/".join(segments)


def compact(value: Mapping[str, Any]) -> Dict[str, Any]:
    """The mapping without ``None`` values."""
    return {key: item for key, item in value.items() if item is not None}


def present(value: Any) -> bool:
    """Not ``None``, not ``""`` and not an empty list."""
    if value is None or value == "":
        return False
    return not (isinstance(value, (list, tuple)) and len(value) == 0)


def cursor_page(
    response: Any,
    items: Any,
    next_cursor: Any,
    has_more: Optional[bool] = None,
    total_count: Any = None,
) -> Page:
    """A :class:`~lunixi.http.envelope.Page` whose rows and cursor come from the product's own list shape.

    ``has_more`` ``None`` means "a next cursor exists". ``raw`` stays the
    whole envelope.
    """
    page: Page = Page(response if isinstance(response, Mapping) else {})
    cursor = next_cursor if isinstance(next_cursor, str) and next_cursor != "" else None
    page.items = list(items) if isinstance(items, (list, tuple)) else []
    page.next_cursor = cursor
    page.has_more = bool(has_more) if has_more is not None else cursor is not None
    counted = isinstance(total_count, int) and not isinstance(total_count, bool)
    page.total_count = total_count if counted else None
    return page


def items_page(response: Any) -> Page:
    """A list whose rows are ``data.items`` and whose paging is the envelope's ``pageInfo``.

    ``has_more`` is true only with a next cursor (bank-connect and insurance lists).
    """
    payload = data_of(response)
    items = payload.get("items") if isinstance(payload, Mapping) else None
    page_info = page_info_of(response) if isinstance(response, Mapping) else {}
    cursor = page_info.get("nextCursor")
    cursor = cursor if isinstance(cursor, str) and cursor != "" else None
    return cursor_page(
        response, items, cursor, page_info.get("hasMore") is True and cursor is not None
    )


def iso_time(value: Any, field: str) -> str:
    """An aware :class:`datetime.datetime` (sent as UTC ISO-8601 with ``Z``) or an ISO-8601 string."""
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConfigurationError(f"'{field}' must be a timezone-aware datetime.")
        moment = value.astimezone(_dt.timezone.utc)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    raise ConfigurationError(
        f"'{field}' must be an aware datetime or an ISO-8601 string with a time zone."
    )


def epoch_seconds(value: Any) -> Optional[float]:
    """The instant of an aware datetime or a parseable ISO-8601 string with a zone, else ``None``."""
    if isinstance(value, _dt.datetime):
        moment: Optional[_dt.datetime] = value
    elif isinstance(value, str) and value.strip() != "":
        stamp = value.strip()
        if stamp.endswith(("Z", "z")):
            stamp = stamp[:-1] + "+00:00"
        try:
            moment = _dt.datetime.fromisoformat(stamp)
        except ValueError:
            return None
    else:
        return None
    if moment is None or moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.timestamp()


def currency_text(value: Any, field: str) -> str:
    """An ISO 4217 code, trimmed and upper-cased."""
    currency = value.strip().upper() if isinstance(value, str) else ""
    if not _CURRENCY.fullmatch(currency):
        raise ConfigurationError(f"'{field}' must be an ISO 4217 code such as TRY.")
    return currency


def page_limit(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ConfigurationError(f"'limit' must be an integer from 1 to {maximum}.")
    return value


def cursor_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ConfigurationError(
            "'cursor' must be the nextCursor of the previous page, passed back unchanged."
        )
    return value


def text(value: Any, field: str, maximum: Optional[int] = None) -> str:
    """A non-empty string, trimmed; ``maximum`` bounds its length."""
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{field} is required.")
    trimmed = value.strip()
    if maximum is not None and len(trimmed) > maximum:
        raise ConfigurationError(f"{field} must be at most {maximum} characters.")
    return trimmed


def paginate(
    fetch_page: Callable[[Dict[str, Any]], Page],
    filters: Mapping[str, Any],
    cursor_param: str = "cursor",
) -> Iterator[Any]:
    """Yields every row, following ``next_cursor`` until the last page.

    ``cursor_param`` is the filter the cursor goes back in (``pageToken`` for
    the subscription lists).
    """
    current: Dict[str, Any] = dict(filters)
    while True:
        page = fetch_page(dict(current))
        yield from page.items
        if not page.has_more or not page.next_cursor:
            return
        current = {key: value for key, value in current.items() if key != cursor_param}
        current[cursor_param] = page.next_cursor


# ── send_route: the caller of the subscriptions, KYC, identity and marketplace tables ──
#
# A route of those tables (Node ``route-request.js``) carries:
#
#   method, path       the HTTP method and path template (``:name`` filled from ``params``)
#   stepUp             sent with the per-request Ed25519 signature
#   idempotencyKey     "required" | "optional" | "none" (the ``Idempotency-Key`` header)
#   required/optional  the body fields; anything else is refused before sending
#   free               the body is a mapping the gateway validates (no field list)
#   optionalBody       an empty body is sent as no body
#   query              accepted query parameters; ``anyQuery`` accepts any scalar filter
#
# Every check runs before anything leaves the process and raises a
# ConfigurationError that names the field, never its value (card data and
# document images included).

_WIRE_MONEY_PATH = re.compile(r"^/api/v1/(?:subscriptions|marketplace)(?:/|$)")
_QUERY_SCALARS = (str, int, float, bool)


def send_route(
    api: Any,
    routes: Mapping[str, Mapping[str, Any]],
    name: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    query: Optional[Mapping[str, Any]] = None,
    body: Any = None,
    idempotency_key: Optional[str] = None,
) -> Any:
    """Sends one route of a table after checking the call against it; returns the envelope.

    The subscription and marketplace contracts carry money members: on those
    paths the body, the filters and the answer are checked with
    :func:`~lunixi.validation.validate_wire_money`.
    """
    route = routes[name]
    path = fill_path(route["path"], params or {})
    key = _check_idempotency_key(name, route.get("idempotencyKey", "none"), idempotency_key)
    filters = None if query is None else _pick_query(name, route, query)
    payload = _build_body(name, route, body)
    money = _WIRE_MONEY_PATH.match(route["path"]) is not None
    if money:
        validate_wire_money(payload)
        validate_wire_money(filters)
    response = api.request(
        route["method"],
        path,
        payload,
        query=filters or None,
        step_up=bool(route.get("stepUp")),
        idempotency_key=key,
    )
    if money:
        validate_wire_money(response)
    return response


def _build_body(name: str, route: Mapping[str, Any], body: Any) -> Optional[Dict[str, Any]]:
    if "required" in route or "optional" in route:
        plain = _route_fields(
            name,
            plain_mapping(body if body is not None else {}, f"{name} body"),
            route.get("required", ()),
            route.get("optional", ()),
        )
        return None if route.get("optionalBody") and not plain else plain
    if route.get("free"):
        plain = compact(
            wire_fields(plain_mapping(body if body is not None else {}, f"{name} body"), name)
        )
        return None if route.get("optionalBody") and not plain else plain
    if body is not None:
        raise ConfigurationError(f"{name} takes no body.")
    return None


def _route_fields(
    label: str, value: Mapping[str, Any], required: Any, optional: Any
) -> Dict[str, Any]:
    """Keeps the allowed fields; an unknown field or a missing required one is refused by name."""
    plain = compact(wire_fields(value, label))
    allowed = (*required, *optional)
    unknown = [key for key in plain if key not in allowed]
    if unknown:
        raise ConfigurationError(f"{label} does not accept {', '.join(unknown)}.")
    missing = [key for key in required if not present(plain.get(key))]
    if missing:
        raise ConfigurationError(f"{label} requires {', '.join(missing)}.")
    return plain


def _pick_query(name: str, route: Mapping[str, Any], filters: Any) -> Dict[str, Any]:
    given = compact(wire_fields(filters, f"{name} filters"))
    if not route.get("anyQuery"):
        allowed = route.get("query", ())
        unknown = [key for key in given if key not in allowed]
        if unknown:
            takes = f"; it takes {', '.join(allowed)}" if allowed else ""
            raise ConfigurationError(
                f"{name} does not accept the filter(s) {', '.join(unknown)}{takes}."
            )
    out: Dict[str, Any] = {}
    for key, value in given.items():
        if value == "":
            continue
        if not isinstance(value, _QUERY_SCALARS):
            raise ConfigurationError(f"{name} filter {key} must be a string, number or boolean.")
        out[key] = ("true" if value else "false") if isinstance(value, bool) else value
    return out


def _check_idempotency_key(name: str, rule: str, key: Any) -> Optional[str]:
    if key is None:
        if rule == "required":
            raise ConfigurationError(
                f"A stable Idempotency-Key is required for {name}. "
                "Reuse the same key when retrying the same operation."
            )
        return None
    if rule == "none":
        raise ConfigurationError(f"{name} does not take an Idempotency-Key.")
    if not isinstance(key, str) or key.strip() == "":
        raise ConfigurationError(f"The Idempotency-Key of {name} must be a non-empty string.")
    return key.strip()


def idempotency_key_of(name: str, request: Mapping[str, Any], key: Any) -> Optional[str]:
    """The request's own ``idempotencyKey`` or the argument; both given, they must agree."""
    own_value = request.get("idempotencyKey")
    own = own_value.strip() if isinstance(own_value, str) and own_value.strip() != "" else None
    given = key.strip() if isinstance(key, str) and key.strip() != "" else None
    if own is not None and given is not None and own != given:
        raise ConfigurationError(
            f"{name}: the request's idempotencyKey and the idempotency_key argument differ."
        )
    return given or own


def check_value(field: str, allowed: Any, value: Any) -> Any:
    """``value`` when it is one of ``allowed``; otherwise refused, naming the field and the set."""
    if value not in allowed:
        raise ConfigurationError(f"{field} must be one of {', '.join(allowed)}; got {value!r}.")
    return value


def optional_text(value: Any, field: str) -> Optional[str]:
    """``None`` for ``None`` / ``""``; a string as it is; anything else is refused."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{field} must be a string.")
    return value


def plain_mapping(value: Any, field: str) -> Dict[str, Any]:
    """A plain ``dict`` copy of a mapping, or of an object with ``to_dict()``."""
    to_dict = getattr(value, "to_dict", None)
    plain = to_dict() if callable(to_dict) and not isinstance(value, Mapping) else value
    if not isinstance(plain, Mapping):
        raise ConfigurationError(f"{field} must be a mapping.")
    return dict(plain)


def merge_root(response: Any) -> Dict[str, Any]:
    """Answers that put their fields at the envelope root and/or under ``data``: both, merged."""
    if not isinstance(response, Mapping):
        return {}
    payload = response.get("data")
    data = dict(payload) if isinstance(payload, Mapping) else {}
    root = {key: value for key, value in response.items() if key != "data"}
    return {**root, **data}


def _text_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value != "" else None


def route_page(response: Any, page_class: type = Page) -> Page:
    """A list answer as a :class:`~lunixi.http.envelope.Page` (Node ``toPage``).

    Reads every list shape in use: ``data`` as the row list, ``data.items`` /
    ``operations`` / ``rows``; the cursor in ``pageInfo`` (a ``pageInfo``
    without one is the last page), else ``nextCursor`` or ``nextPageToken`` in
    ``data`` or at the envelope root. The cursor is opaque: send it back
    unchanged. ``raw`` stays the whole envelope.
    """
    root: Mapping[str, Any] = response if isinstance(response, Mapping) else {}
    payload = data_of(response)
    container: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
    if isinstance(payload, list):
        rows: Any = payload
    else:
        lists = [container.get(key) for key in ("items", "operations", "rows")]
        rows = next((entry for entry in lists if isinstance(entry, list)), [])
    infos = (container.get("pageInfo"), root.get("pageInfo"))
    page_info = next((entry for entry in infos if isinstance(entry, Mapping)), None)
    token: Optional[str] = None
    info_cursor = (
        _text_or_none(page_info.get("nextCursor")) or _text_or_none(page_info.get("endCursor"))
        if page_info is not None
        else None
    )
    if info_cursor is not None:
        token = info_cursor
    elif not (page_info is not None and ("nextCursor" in page_info or "endCursor" in page_info)):
        candidates = (
            container.get("nextCursor"),
            container.get("nextPageToken"),
            root.get("nextPageToken"),
            root.get("nextCursor"),
        )
        token = next((value for value in map(_text_or_none, candidates) if value), None)
    totals = (
        page_info.get("totalCount") if page_info is not None else None,
        container.get("totalCount"),
        container.get("total"),
    )
    numbers = [value for value in totals if isinstance(value, int) and not isinstance(value, bool)]
    total = next(iter(numbers), None)
    has_more = page_info.get("hasMore") if page_info is not None else None
    page: Page = page_class(root)
    page.items = [row for row in rows if isinstance(row, Mapping)]
    page.next_cursor = token
    page.has_more = has_more if isinstance(has_more, bool) else token is not None
    page.total_count = total
    return page
