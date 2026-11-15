"""KYC / KYB / evidence sessions — ``/api/v1/kyc/*``, ``client.kyc()``.

Bearer-only (no per-request signature). Your server creates the session
(``externalCustomerId`` = your own user id, echoed on every webhook); the
browser SDK then runs the capture with the publishable key. The ``kyc.*``
webhook is the authority for the verification result.

Session calls return the envelope's ``data`` (``{session, capturePolicy, …}``;
no personal data comes back, only status, decision, risk and the achieved
assurance). Lists return a :class:`~lunixi.http.envelope.Page`.

Every call is checked against :data:`~lunixi.kyc.values.KYC_ROUTES` before
anything is sent: an unknown field or filter, a missing required field or a
value outside its set raises :class:`~lunixi.errors.ConfigurationError`,
naming the field, never its value (document images included). Body fields may
be given as a mapping or as keyword arguments, in camelCase or snake_case.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from .._routes import (
    check_value,
    compact,
    data_of,
    idempotency_key_of,
    merge_request,
    optional_text,
    paginate,
    plain_mapping,
    route_page,
    send_route,
    text,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from .values import KYC_ROUTES, KYC_SESSION_TTL_MAX_MINUTES, KycSessionType

__all__ = ["KycClient"]

Request = Optional[Mapping[str, Any]]

#: ``listSessions`` filters; ``pageSize`` / ``pageToken`` are read as ``limit`` / ``cursor``.
_LIST_SESSION_FILTERS = ("limit", "cursor", "pageSize", "pageToken")


def _call(api: ApiClient, name: str, **options: Any) -> Any:
    return send_route(api, KYC_ROUTES, name, **options)


class KycClient:
    """KYC, KYB and evidence sessions, and your KYC policy and webhook outbox."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def create_session(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """``subjectId``, ``sessionType``, optional ``externalCustomerId``, ``customerMode``,
        ``person`` | ``company`` | ``customer``, ``jurisdiction``, ``requiredDocumentTypes``,
        ``primaryDocumentType``, ``evidencePurpose``, ``ttlMinutes``, ``metadata``.

        ``person`` / ``company`` are sent as ``customer`` with ``customerType``
        ``PERSON`` / ``COMPANY``; ``metadata`` is sent as ``evidenceContextJson``.
        An ``Idempotency-Key`` (``idempotency_key=`` or the request's
        ``idempotencyKey``) goes in the header and the body.
        """
        body, key = _session_body("createSession", merge_request(request, fields), idempotency_key)
        return data_of(_call(self._api, "createSession", body=body, idempotency_key=key))

    def get_session(self, session_id: str) -> Any:
        return data_of(_call(self._api, "getSession", params={"sessionId": session_id}))

    def list_sessions(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor`` (``pageSize`` / ``pageToken`` are read as the same).

        Anything else is refused: the merchant list has no status or customer
        filter, and dropping one would return every session.
        """
        given = compact(wire_fields(filters, "listSessions filters"))
        unknown = [key for key in given if key not in _LIST_SESSION_FILTERS]
        if unknown:
            raise ConfigurationError(
                f"listSessions does not accept the filter(s) {', '.join(unknown)}; "
                "it takes limit, cursor."
            )
        limit = given.get("limit", given.get("pageSize"))
        cursor = given.get("cursor", given.get("pageToken"))
        query = compact({"limit": limit, "cursor": cursor})
        return route_page(_call(self._api, "listSessions", query=query))

    def iterate_sessions(self, **filters: Any) -> Iterator[Any]:
        """Every session, following the cursor."""
        given = compact(wire_fields(filters, "listSessions filters"))
        if "pageToken" in given and "cursor" not in given:
            given["cursor"] = given.pop("pageToken")
        return paginate(lambda page: self.list_sessions(**page), given)

    def set_jurisdiction(self, session_id: str, jurisdiction: str) -> Any:
        """Applicant jurisdiction (ISO country) on a server-created session."""
        body = {"jurisdiction": text(jurisdiction, "jurisdiction")}
        params = {"sessionId": session_id}
        return data_of(_call(self._api, "setJurisdiction", params=params, body=body))

    def set_primary_document(self, session_id: str, document_type: str) -> Any:
        """``PASSPORT``, ``NATIONAL_ID``, ``DRIVERS_LICENSE`` or ``RESIDENCE_PERMIT``."""
        body = {"documentType": text(document_type, "documentType")}
        params = {"sessionId": session_id}
        return data_of(_call(self._api, "setPrimaryDocument", params=params, body=body))

    def upload_document(self, session_id: str, document: Request = None, **fields: Any) -> Any:
        """Server-side document upload (most flows use the browser SDK).

        ``documentType``, ``fileBase64``, ``mimeType``, optional ``side``,
        ``jurisdiction``, ``metadataJson``, ``idempotencyKey``. The image never
        appears in an error message.
        """
        body = merge_request(
            plain_mapping(document, "uploadDocument document") if document is not None else None,
            fields,
        )
        params = {"sessionId": session_id}
        return data_of(_call(self._api, "uploadDocument", params=params, body=body))

    def timeline(self, session_id: str) -> Any:
        """Session event timeline (audit)."""
        return data_of(_call(self._api, "timeline", params={"sessionId": session_id}))

    def submit(self, session_id: str) -> Any:
        return data_of(_call(self._api, "submit", params={"sessionId": session_id}))

    def manual_review(
        self,
        session_id: str,
        *,
        reason_code: Optional[str] = None,
        reason_detail: Optional[str] = None,
    ) -> Any:
        body = compact(
            {
                "reasonCode": optional_text(reason_code, "reasonCode"),
                "reasonDetail": optional_text(reason_detail, "reasonDetail"),
            }
        )
        params = {"sessionId": session_id}
        return data_of(_call(self._api, "manualReview", params=params, body=body))

    def evidence_request(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """An ``EVIDENCE`` session (proof-of-X), optionally linked to a payment or order;
        same body as :meth:`create_session`."""
        merged = merge_request(request, fields)
        body, key = _session_body("evidenceRequest", merged, idempotency_key)
        return data_of(_call(self._api, "evidenceRequest", body=body, idempotency_key=key))

    def merchant_policy(self) -> Any:
        """Your KYC policy (required assurance, providers…)."""
        return data_of(_call(self._api, "merchantPolicy"))

    def update_merchant_policy(self, policy: Request = None, **fields: Any) -> Any:
        if policy is None and not fields:
            raise ConfigurationError("updateMerchantPolicy needs a policy.")
        body = merge_request(
            plain_mapping(policy, "updateMerchantPolicy policy") if policy is not None else None,
            fields,
        )
        return data_of(_call(self._api, "updateMerchantPolicy", body=body))

    def rotate_webhook_secret(self) -> Any:
        """Rotates the KYC webhook signing secret."""
        return data_of(_call(self._api, "rotateWebhookSecret"))

    def webhook_outbox(self, **filters: Any) -> Page:
        """KYC webhook deliveries; filters ``limit``, ``status``."""
        return route_page(_call(self._api, "webhookOutbox", query=filters))

    def retry_webhook_event(self, event_id: str) -> Any:
        return data_of(_call(self._api, "retryWebhookEvent", params={"eventId": event_id}))

    def erasure_requests(self, **filters: Any) -> Page:
        """Data erasure requests; filters ``limit``, ``status``."""
        return route_page(_call(self._api, "erasureRequests", query=filters))


def _session_body(
    name: str, request: Mapping[str, Any], idempotency_key: Optional[str]
) -> Tuple[Dict[str, Any], Optional[str]]:
    """The wire body of a session request and its ``Idempotency-Key``."""
    body = compact(wire_fields(request, f"{name} request"))
    person = body.pop("person", None)
    company = body.pop("company", None)
    metadata = body.pop("metadata", None)
    key = idempotency_key_of(name, body, idempotency_key)
    if key is not None:
        body["idempotencyKey"] = key
    if "sessionType" in body:
        body["sessionType"] = check_value(
            "sessionType", KycSessionType.ALL, str(body["sessionType"]).upper()
        )
    identities = [value for value in (person, company, body.get("customer")) if value is not None]
    if len(identities) > 1:
        raise ConfigurationError(f"{name} takes one of person, company or customer.")
    if person is not None:
        body["customer"] = {"customerType": "PERSON", **plain_mapping(person, "person")}
    if company is not None:
        body["customer"] = {"customerType": "COMPANY", **plain_mapping(company, "company")}
    if metadata is not None:
        if "evidenceContextJson" in body:
            raise ConfigurationError(f"{name} takes metadata or evidenceContextJson, not both.")
        body["evidenceContextJson"] = json.dumps(
            plain_mapping(metadata, "metadata"), separators=(",", ":"), ensure_ascii=False
        )
    ttl = body.get("ttlMinutes")
    if ttl is not None and (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or not 1 <= ttl <= KYC_SESSION_TTL_MAX_MINUTES
    ):
        raise ConfigurationError(
            f"ttlMinutes must be an integer from 1 to {KYC_SESSION_TTL_MAX_MINUTES}."
        )
    types = body.get("requiredDocumentTypes")
    if types is not None and (
        not isinstance(types, (list, tuple)) or any(not isinstance(kind, str) for kind in types)
    ):
        raise ConfigurationError("requiredDocumentTypes must be a list of document types.")
    return body, key
