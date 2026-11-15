"""KYC / KYB / evidence — ``/api/v1/kyc/*``.

:data:`KYC_ROUTES` describes every route the client calls (method, path, the
``Idempotency-Key`` rule, body and query fields); it is the same table as the
Node SDK's ``KYC_ROUTES`` and the shared catalog (``contracts/products/kyc.json``).
The surface is bearer-only. The browser bootstraps its own SDK token with the
publishable key (``/kyc/sdk/init``); that route is not reachable from a server
key and is not here.
"""

from __future__ import annotations

from typing import Any, Mapping

from .._routes import freeze_routes

__all__ = [
    "KycSessionType",
    "KycSessionStatus",
    "KYC_SESSION_TERMINAL_STATES",
    "KycEvidencePurpose",
    "KycAssuranceLevel",
    "KycAssuranceDomain",
    "KycEvents",
    "KYC_EVENT_TYPES",
    "KYC_SESSION_TTL_MAX_MINUTES",
    "KYC_ROUTES",
    "is_kyc_session_terminal",
    "kyc_assurance_rank",
    "kyc_assurance_meets",
]


class KycSessionType:
    """Session types. ``EVIDENCE`` is proof-of-X (address, funds, card ownership…)."""

    #: A person's identity.
    KYC = "KYC"
    #: A company and its beneficial owners.
    KYB = "KYB"
    EVIDENCE = "EVIDENCE"
    ALL = (KYC, KYB, EVIDENCE)


class KycSessionStatus:
    """Session status."""

    CREATED = "CREATED"
    INITIATED = "INITIATED"
    DOCUMENT_SUBMITTED = "DOCUMENT_SUBMITTED"
    PROCESSING = "PROCESSING"
    AWAITING_PROVIDER_CALLBACK = "AWAITING_PROVIDER_CALLBACK"
    AWAITING_ADDITIONAL_DOCUMENT = "AWAITING_ADDITIONAL_DOCUMENT"
    AWAITING_USER_ACTION = "AWAITING_USER_ACTION"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_ADDITIONAL_INFO = "PENDING_ADDITIONAL_INFO"
    RESCREEN_REQUIRED = "RESCREEN_REQUIRED"
    REOPENED = "REOPENED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"
    CANCELLED = "CANCELLED"
    ALL = (
        CREATED,
        INITIATED,
        DOCUMENT_SUBMITTED,
        PROCESSING,
        AWAITING_PROVIDER_CALLBACK,
        AWAITING_ADDITIONAL_DOCUMENT,
        AWAITING_USER_ACTION,
        UNDER_REVIEW,
        PENDING_ADDITIONAL_INFO,
        RESCREEN_REQUIRED,
        REOPENED,
        APPROVED,
        REJECTED,
        MANUAL_REVIEW,
        EXPIRED,
        ABANDONED,
        CANCELLED,
    )


KYC_SESSION_TERMINAL_STATES = (
    KycSessionStatus.APPROVED,
    KycSessionStatus.REJECTED,
    KycSessionStatus.MANUAL_REVIEW,
    KycSessionStatus.EXPIRED,
    KycSessionStatus.ABANDONED,
    KycSessionStatus.CANCELLED,
)


class KycEvidencePurpose:
    """``evidencePurpose`` of an ``EVIDENCE`` session."""

    IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    BUSINESS_VERIFICATION = "BUSINESS_VERIFICATION"
    PROOF_OF_FUNDS = "PROOF_OF_FUNDS"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"
    SOURCE_OF_FUNDS = "SOURCE_OF_FUNDS"
    SOURCE_OF_WEALTH = "SOURCE_OF_WEALTH"
    TRANSACTION_EVIDENCE = "TRANSACTION_EVIDENCE"
    CARD_OWNERSHIP = "CARD_OWNERSHIP"
    PAYMENT_METHOD_OWNERSHIP = "PAYMENT_METHOD_OWNERSHIP"
    PAYOUT_EVIDENCE = "PAYOUT_EVIDENCE"
    MERCHANT_ONBOARDING = "MERCHANT_ONBOARDING"
    ALL = (
        IDENTITY_VERIFICATION,
        BUSINESS_VERIFICATION,
        PROOF_OF_FUNDS,
        PROOF_OF_ADDRESS,
        SOURCE_OF_FUNDS,
        SOURCE_OF_WEALTH,
        TRANSACTION_EVIDENCE,
        CARD_OWNERSHIP,
        PAYMENT_METHOD_OWNERSHIP,
        PAYOUT_EVIDENCE,
        MERCHANT_ONBOARDING,
    )


class KycAssuranceLevel:
    """Assurance ladder (rank-aligned with NIST 800-63 IAL / eIDAS LoA).

    A gate passes when achieved >= required (:func:`kyc_assurance_meets`).
    """

    NONE = "NONE"
    NOT_PERFORMED = "NOT_PERFORMED"
    LOW = "LOW"
    SUBSTANTIAL = "SUBSTANTIAL"
    HIGH = "HIGH"
    ALL = (NONE, NOT_PERFORMED, LOW, SUBSTANTIAL, HIGH)


class KycAssuranceDomain:
    """Domains of the achieved assurance snapshot
    (``session.decision.assuranceSnapshot.achieved``), each an assurance level."""

    IDENTITY = "identity_evidence_strength"
    DOCUMENT = "document_authenticity_level"
    BIOMETRIC = "possession_biometric_binding"
    AUTHORITATIVE = "authoritative_source_level"
    ADDRESS = "address_assurance"
    AML = "aml_freshness"
    HUMAN_REVIEW = "human_review_level"
    ALL = (IDENTITY, DOCUMENT, BIOMETRIC, AUTHORITATIVE, ADDRESS, AML, HUMAN_REVIEW)


class KycEvents:
    """Webhook event types (same signed envelope as payment events).

    ``data`` always carries ``sessionId`` and ``externalCustomerId``; terminal
    events carry the decision. A rescreen or screening hit on an approved
    session must revoke access.
    """

    SESSION_CREATED = "kyc.session.created"
    SESSION_INITIATED = "kyc.session.initiated"
    SESSION_EXPIRED = "kyc.session.expired"
    SESSION_ABANDONED = "kyc.session.abandoned"
    SESSION_CANCELLED = "kyc.session.cancelled"
    DOCUMENT_RECEIVED = "kyc.document.received"
    DOCUMENT_REJECTED = "kyc.document.rejected"
    LIVENESS_COMPLETED = "kyc.liveness.completed"
    PROCESSING_STARTED = "kyc.processing.started"
    MANUAL_REVIEW_REQUIRED = "kyc.manual_review.required"
    APPROVED = "kyc.approved"
    REJECTED = "kyc.rejected"
    RESCREEN_REQUIRED = "kyc.rescreen.required"
    KYB_SESSION_CREATED = "kyb.session.created"
    KYB_COMPANY_VERIFIED = "kyb.company.verified"
    KYB_COMPANY_NOT_FOUND = "kyb.company.not_found"
    KYB_UBO_PENDING = "kyb.ubo.pending"
    KYB_RELATED_KYC_REQUIRED = "kyb.related_kyc.required"
    KYB_RELATED_KYC_COMPLETED = "kyb.related_kyc.completed"
    KYB_MANUAL_REVIEW_REQUIRED = "kyb.manual_review.required"
    KYB_APPROVED = "kyb.approved"
    KYB_REJECTED = "kyb.rejected"
    SCREENING_MATCH_DETECTED = "screening.match.detected"
    SCREENING_FALSE_POSITIVE_CLEARED = "screening.false_positive.cleared"
    MONITORING_ALERT_CREATED = "ongoing_monitoring.alert.created"
    ALL = (
        SESSION_CREATED,
        SESSION_INITIATED,
        SESSION_EXPIRED,
        SESSION_ABANDONED,
        SESSION_CANCELLED,
        DOCUMENT_RECEIVED,
        DOCUMENT_REJECTED,
        LIVENESS_COMPLETED,
        PROCESSING_STARTED,
        MANUAL_REVIEW_REQUIRED,
        APPROVED,
        REJECTED,
        RESCREEN_REQUIRED,
        KYB_SESSION_CREATED,
        KYB_COMPANY_VERIFIED,
        KYB_COMPANY_NOT_FOUND,
        KYB_UBO_PENDING,
        KYB_RELATED_KYC_REQUIRED,
        KYB_RELATED_KYC_COMPLETED,
        KYB_MANUAL_REVIEW_REQUIRED,
        KYB_APPROVED,
        KYB_REJECTED,
        SCREENING_MATCH_DETECTED,
        SCREENING_FALSE_POSITIVE_CLEARED,
        MONITORING_ALERT_CREATED,
    )


KYC_EVENT_TYPES = KycEvents.ALL

#: Longest session lifetime ``ttlMinutes`` accepts (one day).
KYC_SESSION_TTL_MAX_MINUTES = 1440

_KYC = "/api/v1/kyc"
_SESSION_FIELDS = [
    "externalCustomerId",
    "customerMode",
    "customer",
    "jurisdiction",
    "requiredDocumentTypes",
    "primaryDocumentType",
    "evidencePurpose",
    "ttlMinutes",
    "idempotencyKey",
    "evidenceContextJson",
]


def _route(method: str, path: str, **extra: Any) -> Mapping[str, Any]:
    return {"method": method, "path": path, "stepUp": False, "idempotencyKey": "none", **extra}


#: Every route the KYC client calls (Node ``KYC_ROUTES``).
KYC_ROUTES = freeze_routes(
    {
        "createSession": _route(
            "POST",
            f"{_KYC}/sessions",
            idempotencyKey="optional",
            required=["subjectId", "sessionType"],
            optional=_SESSION_FIELDS,
        ),
        "getSession": _route("GET", f"{_KYC}/sessions/:sessionId"),
        # The merchant list takes only these two; an unknown filter is a 400 on the gateway.
        "listSessions": _route("GET", f"{_KYC}/sessions", query=["limit", "cursor"]),
        "setJurisdiction": _route(
            "POST", f"{_KYC}/sessions/:sessionId/jurisdiction", required=["jurisdiction"]
        ),
        "setPrimaryDocument": _route(
            "POST", f"{_KYC}/sessions/:sessionId/primary-document", required=["documentType"]
        ),
        "uploadDocument": _route(
            "POST",
            f"{_KYC}/sessions/:sessionId/documents",
            required=["documentType", "fileBase64", "mimeType"],
            optional=["side", "jurisdiction", "metadataJson", "idempotencyKey"],
        ),
        "timeline": _route("GET", f"{_KYC}/sessions/:sessionId/timeline"),
        "submit": _route("POST", f"{_KYC}/sessions/:sessionId/submit"),
        "manualReview": _route(
            "POST",
            f"{_KYC}/sessions/:sessionId/manual-review",
            optional=["reasonCode", "reasonDetail"],
            optionalBody=True,
        ),
        "evidenceRequest": _route(
            "POST",
            f"{_KYC}/evidence-requests",
            idempotencyKey="optional",
            required=["subjectId", "sessionType"],
            optional=_SESSION_FIELDS,
        ),
        "merchantPolicy": _route("GET", f"{_KYC}/admin/merchant-policy"),
        "updateMerchantPolicy": _route("POST", f"{_KYC}/admin/merchant-policy", free=True),
        "rotateWebhookSecret": _route(
            "POST", f"{_KYC}/admin/merchant-policy/webhook-secret/rotate"
        ),
        "webhookOutbox": _route("GET", f"{_KYC}/admin/webhook-outbox", query=["limit", "status"]),
        "retryWebhookEvent": _route("POST", f"{_KYC}/admin/webhook-outbox/:eventId/retry"),
        "erasureRequests": _route(
            "GET", f"{_KYC}/admin/erasure-requests", query=["limit", "status"]
        ),
    }
)


def is_kyc_session_terminal(status: Any) -> bool:
    """True for ``APPROVED``, ``REJECTED``, ``MANUAL_REVIEW``, ``EXPIRED``, ``ABANDONED``,
    ``CANCELLED`` (case-insensitive)."""
    return isinstance(status, str) and status.upper() in KYC_SESSION_TERMINAL_STATES


def kyc_assurance_rank(level: Any) -> int:
    """Rank on the assurance ladder: ``HIGH`` 3, ``SUBSTANTIAL`` 2, ``LOW`` 1, anything else 0."""
    ranks = {KycAssuranceLevel.HIGH: 3, KycAssuranceLevel.SUBSTANTIAL: 2, KycAssuranceLevel.LOW: 1}
    return ranks.get(level.upper(), 0) if isinstance(level, str) else 0


def kyc_assurance_meets(achieved: Any, required: Any) -> bool:
    """True when ``achieved`` meets or exceeds ``required``."""
    return kyc_assurance_rank(achieved) >= kyc_assurance_rank(required)
