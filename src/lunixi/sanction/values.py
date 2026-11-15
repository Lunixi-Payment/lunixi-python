"""Sanctions screening — the merchant API surface, ``/api/v1/sanction/*``.

:data:`SANCTION_ROUTES` is the single description of every route the client
calls: the HTTP method, the path template, the body fields the gateway
forwards to the sanction service and the query parameters it reads. It is the
same table as the Node SDK's ``SANCTION_ROUTES`` and the shared catalog
(``contracts/products/sanction.json``). The gateway does not validate the body
itself: a field the service does not know is dropped there SILENTLY, so the
client refuses it before sending.

Only routes an API key can reach are listed; they need the
``sanction:view_results`` permission. The screening report PDF (panel session
only), deny-list writes, analyst decisions and list-source syncs are not
merchant API-key routes.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .._routes import freeze_routes

__all__ = [
    "SanctionRiskDomain",
    "SanctionScreenMode",
    "SanctionWalletScreenMode",
    "SanctionSubjectType",
    "SanctionCoverageStatus",
    "SanctionHitType",
    "SanctionEvents",
    "SANCTION_ROUTES",
    "SANCTION_NESTED_FIELDS",
    "SANCTION_VALUE_SETS",
    "is_clear_screening",
]


class SanctionRiskDomain:
    """Risk domains a screening can be narrowed to (``riskDomains``). Omitted: every domain."""

    SANCTIONS = "sanctions"
    PEP = "pep"
    RCA = "rca"
    WANTED = "wanted"
    REGULATORY = "regulatory"
    DEBARMENT = "debarment"
    OWNERSHIP = "ownership"
    VESSEL = "vessel"
    SECURITIES = "securities"
    ALL = (SANCTIONS, PEP, RCA, WANTED, REGULATORY, DEBARMENT, OWNERSHIP, VESSEL, SECURITIES)


class SanctionScreenMode:
    """Name-screening presets. Sent with ``riskDomains``, their intersection is screened."""

    SANCTIONS_ONLY = "sanctions_only"
    SANCTIONS_PEP = "sanctions_pep"
    FULL_RISK = "full_risk"
    ALL = (SANCTIONS_ONLY, SANCTIONS_PEP, FULL_RISK)


class SanctionWalletScreenMode:
    """Wallet-screening depth; the wider modes add exposure and crypto-intelligence hits."""

    WALLET_SANCTIONS = "wallet_sanctions"
    WALLET_RISK = "wallet_risk"
    WALLET_FULL_AML = "wallet_full_aml"
    ALL = (WALLET_SANCTIONS, WALLET_RISK, WALLET_FULL_AML)


class SanctionSubjectType:
    PERSON = "person"
    ORGANIZATION = "organization"
    ALL = (PERSON, ORGANIZATION)


class SanctionCoverageStatus:
    """How much of the requested scope a screening covered.

    ``COMPLETE``: every requested risk domain was screened. ``PARTIAL``: some
    requested domain has no list (``uncoveredRiskDomains``,
    ``uncoveredSources``); no match is clear only for what was screened.
    ``DEGRADED``: the candidate search was limited; run the screening again.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    ALL = (COMPLETE, PARTIAL, DEGRADED)


class SanctionHitType:
    EXACT = "exact"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    ALL = (EXACT, PROBABLE, POSSIBLE)


class SanctionEvents:
    """Sanction webhook event types, verified with :class:`~lunixi.webhook.verifier.WebhookVerifier`."""

    MATCH_DETECTED = "screening.match.detected"
    FALSE_POSITIVE_CLEARED = "screening.false_positive.cleared"
    MONITORING_ALERT_CREATED = "ongoing_monitoring.alert.created"
    MONITORING_CLEAR = "ongoing_monitoring.clear"
    ALL = (MATCH_DETECTED, FALSE_POSITIVE_CLEARED, MONITORING_ALERT_CREATED, MONITORING_CLEAR)


_PAGE_QUERY = ["limit", "cursor"]

#: Every route the sanction client calls (Node ``SANCTION_ROUTES``). ``screening``:
#: the answer must be ``status: "success"`` to be read; ``anyOf``: at least one
#: of these body fields must be present (a list: non-empty).
SANCTION_ROUTES = freeze_routes(
    {
        # Screening
        "screenName": {
            "method": "POST",
            "path": "/api/v1/sanction/screening/name",
            "screening": True,
            "required": ["name"],
            "optional": [
                "subjectType",
                "country",
                "dateOfBirth",
                "identifiers",
                "riskDomains",
                "mode",
                "threshold",
                "customerReference",
            ],
        },
        "screenWallet": {
            "method": "POST",
            "path": "/api/v1/sanction/screening/wallet",
            "screening": True,
            "required": ["walletAddress"],
            "optional": ["chain", "mode", "customerReference"],
        },
        "screenAccount": {
            "method": "POST",
            "path": "/api/v1/sanction/screening/account",
            "screening": True,
            "required": ["accountValue", "accountScheme"],
            "optional": ["providerCode", "productChannel", "customerReference"],
        },
        "screenTransaction": {
            "method": "POST",
            "path": "/api/v1/sanction/screening/transaction",
            "screening": True,
            "required": [],
            "optional": [
                "transactionType",
                "direction",
                "amount",
                "currency",
                "channel",
                "occurredAt",
                "parties",
                "accounts",
                "metadataJson",
            ],
            # Neither: the sanction service holds the transaction as not screenable.
            "anyOf": ["parties", "accounts"],
        },
        "screenPublicProcurementBan": {
            "method": "POST",
            "path": "/api/v1/sanction/intelligence/public-procurement-ban",
            "screening": True,
            "required": [],
            "optional": [
                "entityName",
                "tckn",
                "vkn",
                "entityType",
                "onlyActive",
                "limit",
                "customerReference",
                "productChannel",
            ],
            "anyOf": ["entityName", "tckn", "vkn"],
        },
        "screenAdverseMedia": {
            "method": "POST",
            "path": "/api/v1/sanction/intelligence/adverse-media",
            "screening": True,
            "required": [],
            "optional": [
                "entityName",
                "entityType",
                "tckn",
                "vkn",
                "countryCode",
                "limit",
                "onlyActive",
                "customerReference",
                "productChannel",
            ],
        },
        "evaluateBehavioralAlert": {
            "method": "POST",
            "path": "/api/v1/sanction/intelligence/behavioral-alert",
            "screening": True,
            "required": [],
            "optional": [
                "subjectReference",
                "customerReference",
                "productChannel",
                "velocityScore",
                "unusualPattern",
                "countryRiskLevel",
                "metadataJson",
            ],
        },
        "listScreeningHistory": {
            "method": "GET",
            "path": "/api/v1/sanction/screening/history",
            "screening": False,
            "query": [*_PAGE_QUERY],
        },
        # Ongoing monitoring
        "registerMonitoring": {
            "method": "POST",
            "path": "/api/v1/sanction/monitoring/register",
            "screening": False,
            "required": ["externalCustomerId"],
            "optional": ["subjectType", "profileJson", "frequency", "riskDomainScope"],
        },
        "listMonitoringAlerts": {
            "method": "GET",
            "path": "/api/v1/sanction/monitoring/alerts",
            "screening": False,
            "query": ["status", *_PAGE_QUERY, "includeTotal"],
        },
        "listMonitoredEntities": {
            "method": "GET",
            "path": "/api/v1/sanction/monitoring/entities",
            "screening": False,
            "query": ["activeOnly", *_PAGE_QUERY, "includeTotal"],
        },
        "listMonitoringMatches": {
            "method": "GET",
            "path": "/api/v1/sanction/monitoring/matches",
            "screening": False,
            "query": ["status", *_PAGE_QUERY],
        },
        "getDatasetFreshness": {
            "method": "GET",
            "path": "/api/v1/sanction/monitoring/dataset-freshness",
            "screening": False,
        },
        # Entity intelligence
        "searchEntities": {
            "method": "GET",
            "path": "/api/v1/sanction/intelligence/entity-search",
            "screening": False,
            "query": ["q", "limit"],
        },
        "getEntityProfile": {
            "method": "GET",
            "path": "/api/v1/sanction/intelligence/entity-profiles/:entityId",
            "screening": False,
            "query": ["screeningRequestId"],
        },
        "getEntityGraph": {
            "method": "GET",
            "path": "/api/v1/sanction/intelligence/entity-graph/:entityId",
            "screening": False,
            "query": ["depth"],
        },
        "getIndirectExposure": {
            "method": "GET",
            "path": "/api/v1/sanction/intelligence/indirect-exposure/:entityId",
            "screening": False,
            "query": ["maxDepth", "entityIds"],
        },
        "getOwnershipAggregation": {
            "method": "GET",
            "path": "/api/v1/sanction/intelligence/ownership-aggregation/:entityId",
            "screening": False,
            "query": ["depth", "entityIds"],
        },
        # Your own deny list (read; adding an entry is not an API-key route)
        "listBlacklistEntries": {
            "method": "GET",
            "path": "/api/v1/sanction/blacklist",
            "screening": False,
            "query": [*_PAGE_QUERY],
        },
    }
)

#: Fields of the nested lists, checked element by element (the service drops anything else).
SANCTION_NESTED_FIELDS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "screenName.identifiers": MappingProxyType(
            {"required": ("type", "value"), "optional": ()},
        ),
        "screenTransaction.parties": MappingProxyType(
            {
                "required": ("name",),
                "optional": (
                    "role",
                    "subjectType",
                    "countryCode",
                    "customerId",
                    "dateOfBirth",
                    "nationalId",
                ),
            }
        ),
        "screenTransaction.accounts": MappingProxyType(
            {"required": ("accountType", "value"), "optional": ("role", "providerCode", "chain")}
        ),
    }
)

#: Value sets checked before sending; the sanction service refuses anything else with 400.
SANCTION_VALUE_SETS = MappingProxyType(
    {
        "screenName.riskDomains": SanctionRiskDomain.ALL,
        "screenName.mode": SanctionScreenMode.ALL,
        "screenName.subjectType": SanctionSubjectType.ALL,
        "screenWallet.mode": SanctionWalletScreenMode.ALL,
        "registerMonitoring.subjectType": SanctionSubjectType.ALL,
        "registerMonitoring.riskDomainScope": SanctionRiskDomain.ALL,
    }
)

_BLOCKING_DECISIONS = ("block", "blocked", "reject", "rejected", "review", "hit", "escalate")


def is_clear_screening(result: Any) -> bool:
    """Whether a screening answer can be read as "nothing found".

    True only when the answer has no match or hit of any kind and, when it
    reports coverage, its ``coverageStatus`` is ``COMPLETE``. A ``PARTIAL`` or
    ``DEGRADED`` screening, a replay without coverage (``None``), a wallet held
    by a listed party, a matched procurement ban, a transaction that needs a
    case or a blocking decision is never clear. A failed screening (HTTP 503,
    ``status: "failure"``) never reaches this function: the client raises.

    Account and adverse-media screening do not report coverage; for them the
    hits and flags decide.
    """
    if not isinstance(result, Mapping):
        return False
    for key in ("matches", "hits", "publicationHits"):
        value = result.get(key)
        if isinstance(value, list) and len(value) > 0:
            return False
    for flag in ("isSanctioned", "isBlacklisted", "matched", "caseRequired"):
        if result.get(flag) is True:
            return False
    decision = result.get("decision")
    if isinstance(decision, str) and decision.lower() in _BLOCKING_DECISIONS:
        return False
    if "coverageStatus" in result:
        return result["coverageStatus"] == SanctionCoverageStatus.COMPLETE
    return True
