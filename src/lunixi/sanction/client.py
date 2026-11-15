"""Sanctions screening — ``/api/v1/sanction/*``, ``client.sanction()``.

Calls carry the access token minted from your API key (no per-request
signature). The key needs the ``SANCTION_SERVICE`` product and the
``sanction:view_results`` permission (403 otherwise).

Screening returns matches, not verdicts: the decision is yours. Read a result
with :func:`~lunixi.sanction.values.is_clear_screening`: an empty match list
is clear only when ``coverageStatus`` is ``COMPLETE``. When the screening
cannot run (no list publication can be pinned) the gateway answers 503 and the
call raises :class:`~lunixi.errors.ServiceUnavailableError`; a 2xx answer
whose ``status`` is not ``"success"`` raises :class:`~lunixi.errors.ApiError`.
It never comes back as an empty result.

Responses are the envelope's ``data``. The envelope's ``requestId`` is the
HTTP request's id; the screening's own id is ``screeningRequestId`` (name
screening). List calls return a :class:`~lunixi.http.envelope.Page`.

Every call is checked against :data:`~lunixi.sanction.values.SANCTION_ROUTES`
before anything is sent: an unknown field, a missing required field, an empty
``anyOf`` group, a nested row with an unknown or missing field, a value
outside its set or an unknown filter raises
:class:`~lunixi.errors.ConfigurationError`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .._routes import (
    compact,
    cursor_page,
    data_of,
    fill_path,
    merge_request,
    paginate,
    present,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ApiError, ConfigurationError
from ..http.envelope import Page, page_info_of
from .values import SANCTION_NESTED_FIELDS, SANCTION_ROUTES, SANCTION_VALUE_SETS

__all__ = ["SanctionClient"]

Request = Optional[Mapping[str, Any]]


class SanctionClient:
    """Screening, ongoing monitoring, entity intelligence and your deny list."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    # ── Screening ────────────────────────────────────────────────────────────

    def screen_name(self, request: Request = None, **fields: Any) -> Any:
        """Person or organization: ``name``, optional ``subjectType``, ``country``,
        ``dateOfBirth``, ``identifiers`` (``[{type, value}]``), ``riskDomains``, ``mode``,
        ``threshold``, ``customerReference``."""
        return self._screen("screenName", request, fields)

    def screen_wallet(self, request: Request = None, **fields: Any) -> Any:
        """Crypto wallet address (exact match against the listed addresses)."""
        return self._screen("screenWallet", request, fields)

    def screen_account(self, request: Request = None, **fields: Any) -> Any:
        """Bank account / IBAN against your own deny list and account risk data (no list publication)."""
        return self._screen("screenAccount", request, fields)

    def screen_transaction(self, request: Request = None, **fields: Any) -> Any:
        """Every party and account of a transaction, against one list publication.

        At least one of ``parties`` (``name`` required) and ``accounts``
        (``accountType``, ``value``).
        """
        return self._screen("screenTransaction", request, fields)

    def screen_public_procurement_ban(self, request: Request = None, **fields: Any) -> Any:
        """Public procurement debarment lists, by name and TCKN/VKN (at least one of the three).

        The Turkish public procurement list is not published, so
        ``coverageStatus`` is ``PARTIAL`` and ``uncoveredSources`` names it: no
        match is not a clean result for it.
        """
        return self._screen("screenPublicProcurementBan", request, fields)

    def screen_adverse_media(self, request: Request = None, **fields: Any) -> Any:
        """Adverse media. Runs only when your adverse-media policy is enabled."""
        return self._screen("screenAdverseMedia", request, fields)

    def evaluate_behavioral_alert(self, request: Request = None, **fields: Any) -> Any:
        """Behavioural risk signal evaluation."""
        return self._screen("evaluateBehavioralAlert", request, fields)

    def list_screening_history(self, **filters: Any) -> Page:
        """Earlier screenings (audit trail), newest first. Filters: ``limit``, ``cursor``."""
        return _to_page(self._invoke("listScreeningHistory", {"query": filters}))

    def iterate_screening_history(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_screening_history(**page), filters)

    # ── Ongoing monitoring ───────────────────────────────────────────────────

    def register_monitoring(self, request: Request = None, **fields: Any) -> Any:
        """Registers a subject for ongoing monitoring; returns ``{monitoredEntityId}``.

        ``externalCustomerId`` is required. ``profile`` (a mapping: name,
        dateOfBirth, country, identifiers…) is sent as ``profileJson``; pass
        one of the two.
        """
        body = wire_fields(merge_request(request, fields), "registerMonitoring body")
        profile = body.pop("profile", None)
        if profile is not None:
            if body.get("profileJson") is not None:
                raise ConfigurationError(
                    "registerMonitoring takes profile or profileJson, not both."
                )
            body["profileJson"] = json.dumps(profile, separators=(",", ":"), ensure_ascii=False)
        return data_of(self._invoke("registerMonitoring", None, body))

    def list_monitoring_alerts(self, **filters: Any) -> Page:
        """New-match alerts raised by monitoring; ``status`` narrows (e.g. ``open``).

        Filters: ``status``, ``limit``, ``cursor``, ``includeTotal``.
        """
        return _to_page(self._invoke("listMonitoringAlerts", {"query": filters}))

    def iterate_monitoring_alerts(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_monitoring_alerts(**page), filters)

    def list_monitored_entities(self, **filters: Any) -> Page:
        """Monitored subjects; ``activeOnly`` defaults to ``True`` on the gateway.

        Filters: ``activeOnly``, ``limit``, ``cursor``, ``includeTotal``.
        """
        return _to_page(self._invoke("listMonitoredEntities", {"query": filters}))

    def iterate_monitored_entities(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_monitored_entities(**page), filters)

    def list_monitoring_matches(self, **filters: Any) -> Page:
        """Matches raised by monitoring. Filters: ``status``, ``limit``, ``cursor``."""
        return _to_page(self._invoke("listMonitoringMatches", {"query": filters}))

    def iterate_monitoring_matches(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_monitoring_matches(**page), filters)

    def get_dataset_freshness(self) -> Any:
        """Freshness of the source lists: ``{manifest}``; a failed manifest raises."""
        return _screening_data(self._invoke("getDatasetFreshness"))

    # ── Entity intelligence ──────────────────────────────────────────────────

    def search_entities(self, **filters: Any) -> Any:
        """Entity search by name: ``q``, optional ``limit``."""
        return data_of(self._invoke("searchEntities", {"query": filters}))

    def get_entity_profile(
        self, entity_id: str, *, screening_request_id: Optional[str] = None
    ) -> Any:
        """Entity risk profile; ``screening_request_id`` reads it on that screening's publication."""
        params = {
            "entityId": entity_id,
            "query": compact({"screeningRequestId": screening_request_id}),
        }
        return data_of(self._invoke("getEntityProfile", params))

    def get_entity_graph(self, entity_id: str, *, depth: Optional[int] = None) -> Any:
        """Relationship graph, ``depth`` 1–3."""
        params = {"entityId": entity_id, "query": compact({"depth": depth})}
        return data_of(self._invoke("getEntityGraph", params))

    def get_indirect_exposure(
        self,
        entity_id: str,
        *,
        max_depth: Optional[int] = None,
        entity_ids: Optional[Any] = None,
    ) -> Any:
        """Indirect exposure paths; ``entity_ids`` are the records of a merged match."""
        query = compact({"maxDepth": max_depth, "entityIds": _id_list(entity_ids)})
        return data_of(self._invoke("getIndirectExposure", {"entityId": entity_id, "query": query}))

    def get_ownership_aggregation(
        self,
        entity_id: str,
        *,
        depth: Optional[int] = None,
        entity_ids: Optional[Any] = None,
    ) -> Any:
        """Ownership aggregation (50% rule); ``entity_ids`` are the records of a merged match."""
        query = compact({"depth": depth, "entityIds": _id_list(entity_ids)})
        params = {"entityId": entity_id, "query": query}
        return data_of(self._invoke("getOwnershipAggregation", params))

    # ── Deny list ────────────────────────────────────────────────────────────

    def list_blacklist_entries(self, **filters: Any) -> Page:
        """Your own deny-list entries (read only with an API key). Filters: ``limit``, ``cursor``."""
        return _to_page(self._invoke("listBlacklistEntries", {"query": filters}))

    def iterate_blacklist_entries(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_blacklist_entries(**page), filters)

    # ── the caller ───────────────────────────────────────────────────────────

    def _screen(self, route_name: str, request: Request, fields: Mapping[str, Any]) -> Any:
        return _screening_data(self._invoke(route_name, None, merge_request(request, fields)))

    def _invoke(
        self,
        route_name: str,
        params: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Sends one route of :data:`SANCTION_ROUTES` after checking the call against it."""
        route = SANCTION_ROUTES[route_name]
        params = params or {}
        path = fill_path(route["path"], params)
        query = _pick_query(route_name, route, params["query"]) if "query" in params else {}
        payload = None
        if route["method"] != "GET":
            payload = _check_body(route_name, route, body if body is not None else {})
        return self._api.request(route["method"], path, payload, query=query or None)


def _check_body(route_name: str, route: Mapping[str, Any], body: Any) -> Dict[str, Any]:
    plain = _fields(route_name, body, route.get("required", ()), route.get("optional", ()))
    any_of = route.get("anyOf")
    if any_of and not any(present(plain.get(key)) for key in any_of):
        raise ConfigurationError(f"{route_name} requires at least one of {', '.join(any_of)}.")
    for key, value in list(plain.items()):
        nested = SANCTION_NESTED_FIELDS.get(f"{route_name}.{key}")
        if nested is not None:
            plain[key] = _rows(f"{route_name}.{key}", nested, value)
        allowed = SANCTION_VALUE_SETS.get(f"{route_name}.{key}")
        if allowed is not None:
            _check_values(f"{route_name}.{key}", allowed, value)
    return plain


def _fields(label: str, value: Any, required: Any, optional: Any) -> Dict[str, Any]:
    plain = compact(wire_fields(value, label))
    allowed = (*required, *optional)
    unknown = [key for key in plain if key not in allowed]
    if unknown:
        raise ConfigurationError(f"{label} does not accept {', '.join(unknown)}.")
    missing = [key for key in required if not present(plain.get(key))]
    if missing:
        raise ConfigurationError(f"{label} requires {', '.join(missing)}.")
    return plain


def _rows(label: str, spec: Mapping[str, Any], rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, (list, tuple)):
        raise ConfigurationError(f"{label} must be a list.")
    return [
        _fields(f"{label}[{index}]", row, spec["required"], spec["optional"])
        for index, row in enumerate(rows)
    ]


def _check_values(label: str, allowed: Any, value: Any) -> None:
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    outside = [entry for entry in values if entry not in allowed]
    if outside:
        raise ConfigurationError(
            f"{label} must be one of {', '.join(allowed)}; got "
            + ", ".join(repr(entry) for entry in outside)
            + "."
        )


def _pick_query(route_name: str, route: Mapping[str, Any], filters: Any) -> Dict[str, Any]:
    allowed = route.get("query", ())
    given = compact(wire_fields(filters, f"{route_name} filters"))
    unknown = [key for key in given if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"{route_name} does not accept the filter(s) {', '.join(unknown)}."
        )
    return {key: given[key] for key in allowed if key in given}


def _id_list(entity_ids: Any) -> Optional[str]:
    """Member ids of a merged match, sent comma-separated."""
    if entity_ids is None:
        return None
    values = entity_ids if isinstance(entity_ids, (list, tuple)) else [entity_ids]
    ids = [str(entity_id).strip() for entity_id in values if str(entity_id).strip()]
    return ",".join(ids) if ids else None


def _screening_data(response: Any) -> Any:
    """A 2xx answer that is not ``status: "success"`` is refused rather than read.

    A screening that did not run must never look like an empty result.
    """
    status = response.get("status") if isinstance(response, Mapping) else None
    if isinstance(status, str) and status != "success":
        code = response.get("code")
        status_code = response.get("statusCode")
        request_id = response.get("requestId")
        raise ApiError(
            "The screening did not complete.",
            status_code=status_code if isinstance(status_code, int) else 0,
            code=code if isinstance(code, str) and code != "" else None,
            request_id=request_id if isinstance(request_id, str) else None,
        )
    return data_of(response)


def _to_page(response: Any) -> Page:
    """Sanction lists answer ``{items, nextCursor}`` (history, alerts, entities) or
    ``{items}`` with the envelope's ``pageInfo`` beside ``data`` (matches, deny list)."""
    payload = data_of(response)
    payload = payload if payload is not None else {}
    page_info = page_info_of(response) if isinstance(response, Mapping) else {}
    if isinstance(payload, list):
        items: Any = payload
        data_cursor = None
        data_total = None
    elif isinstance(payload, Mapping):
        items = payload.get("items")
        data_cursor = payload.get("nextCursor")
        data_total = payload.get("totalCount")
    else:
        items, data_cursor, data_total = [], None, None
    cursor = data_cursor if data_cursor is not None else page_info.get("nextCursor")
    total = data_total if data_total is not None else page_info.get("totalCount")
    has_more = page_info.get("hasMore")
    return cursor_page(
        response, items, cursor, has_more if isinstance(has_more, bool) else None, total
    )
