"""Sanctions screening: bearer-only calls, table checks, the clean-read rule and list paging."""

from __future__ import annotations

import json

import pytest

from lunixi import is_clear_screening
from lunixi.errors import ApiError, ConfigurationError, ServiceUnavailableError
from lunixi.sanction import (
    SanctionCoverageStatus,
    SanctionRiskDomain,
    SanctionScreenMode,
    SanctionSubjectType,
)

from .support.recording_transport import envelope, error_envelope, json_response
from .support.wire import assert_unsigned, body_of, path_of, query_of


def ok(data):
    return json_response(envelope(data))


CLEAR = {"screeningRequestId": "scr-1", "matches": [], "coverageStatus": "COMPLETE"}


def test_screen_name_is_bearer_only_and_checked(client_factory):
    transport, client = client_factory(ok(CLEAR))
    result = client.sanction().screen_name(
        name="Test Person",
        subject_type=SanctionSubjectType.PERSON,
        identifiers=[{"type": "TCKN", "value": "10000000146"}],
        risk_domains=[SanctionRiskDomain.SANCTIONS, SanctionRiskDomain.PEP],
        mode=SanctionScreenMode.SANCTIONS_PEP,
        customer_reference="cust-1",
    )
    request = transport.last
    assert (request.method, path_of(request)) == ("POST", "/api/v1/sanction/screening/name")
    assert body_of(request) == {
        "name": "Test Person",
        "subjectType": "person",
        "identifiers": [{"type": "TCKN", "value": "10000000146"}],
        "riskDomains": ["sanctions", "pep"],
        "mode": "sanctions_pep",
        "customerReference": "cust-1",
    }
    assert_unsigned(request)
    assert request.header("Idempotency-Key") is None
    assert result == CLEAR
    assert is_clear_screening(result) is True


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"subjectType": "person"}, "requires name"),
        ({"name": "X", "dob": "1990-01-01"}, "does not accept dob"),
        ({"name": "X", "mode": "everything"}, "screenName.mode must be one of"),
        ({"name": "X", "riskDomains": ["sanctions", "crypto"]}, "'crypto'"),
        ({"name": "X", "identifiers": [{"type": "TCKN"}]}, r"identifiers\[0\] requires value"),
        (
            {"name": "X", "identifiers": [{"type": "T", "value": "1", "country": "TR"}]},
            "does not accept country",
        ),
        ({"name": "X", "identifiers": {"type": "T"}}, "must be a list"),
    ],
)
def test_screen_name_is_refused_before_sending(client_factory, fields, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.sanction().screen_name(fields)
    assert transport.requests == []


def test_any_of_groups(client_factory):
    transport, client = client_factory(ok({"matches": [], "coverageStatus": "COMPLETE"}))
    with pytest.raises(ConfigurationError, match="at least one of parties, accounts"):
        client.sanction().screen_transaction(amount="1000", currency="TRY", parties=[])
    with pytest.raises(ConfigurationError, match="at least one of entityName, tckn, vkn"):
        client.sanction().screen_public_procurement_ban(only_active=True)
    with pytest.raises(ConfigurationError, match=r"parties\[0\] requires name"):
        client.sanction().screen_transaction(parties=[{"role": "SENDER"}])
    assert transport.requests == []
    client.sanction().screen_transaction(accounts=[{"accountType": "IBAN", "value": "TR00"}])
    assert path_of(transport.last) == "/api/v1/sanction/screening/transaction"


def test_a_screening_that_did_not_run_is_never_read_as_empty(client_factory):
    failure = {**envelope(None), "status": "failure", "code": "sanction.screen_name.failed"}
    transport, client = client_factory(
        json_response(failure),
        json_response(error_envelope("sanction.screen_name.failed", "x", 503), 503),
    )
    with pytest.raises(ApiError) as raised:
        client.sanction().screen_name(name="Test Person")
    assert raised.value.code == "sanction.screen_name.failed"
    with pytest.raises(ServiceUnavailableError):
        client.sanction().screen_name(name="Test Person")
    # A POST without an Idempotency-Key is sent once: no retry of the 503.
    assert len(transport.requests_to("/sanction/screening/name")) == 2


@pytest.mark.parametrize(
    "result, clear",
    [
        ({"matches": [], "coverageStatus": "COMPLETE"}, True),
        ({"matches": [], "coverageStatus": "PARTIAL"}, False),
        ({"matches": [], "coverageStatus": "DEGRADED"}, False),
        ({"matches": [], "coverageStatus": None}, False),
        ({"matches": [{"entityId": "e-1"}], "coverageStatus": "COMPLETE"}, False),
        ({"hits": [], "publicationHits": [{"listedAddress": "0x"}]}, False),
        ({"hits": [], "isSanctioned": True}, False),
        ({"hits": [], "isBlacklisted": True}, False),
        ({"hits": [], "matched": True}, False),
        ({"caseRequired": True, "coverageStatus": "COMPLETE"}, False),
        ({"decision": "REVIEW", "coverageStatus": "COMPLETE"}, False),
        ({"decision": "allow", "coverageStatus": "COMPLETE"}, True),
        ({"hits": []}, True),
        (None, False),
        ([], False),
    ],
)
def test_clean_read_rule(result, clear):
    assert is_clear_screening(result) is clear
    assert SanctionCoverageStatus.COMPLETE == "COMPLETE"


def test_history_reads_the_cursor_inside_data(client_factory):
    transport, client = client_factory(
        ok({"items": [{"id": "h-1"}], "nextCursor": "c2", "runsToday": 4}),
        ok({"items": [{"id": "h-2"}], "nextCursor": None}),
    )
    rows = list(client.sanction().iterate_screening_history(limit=1))
    assert [row["id"] for row in rows] == ["h-1", "h-2"]
    assert query_of(transport.last) == {"limit": ["1"], "cursor": ["c2"]}
    assert_unsigned(transport.last)


def test_matches_read_the_envelope_page_info(client_factory):
    transport, client = client_factory(
        json_response(
            envelope({"items": [{"id": "m-1"}]}, pageInfo={"hasMore": True, "nextCursor": "n2"})
        )
    )
    page = client.sanction().list_monitoring_matches(status="open")
    assert (page.items, page.has_more, page.next_cursor) == ([{"id": "m-1"}], True, "n2")
    assert path_of(transport.last) == "/api/v1/sanction/monitoring/matches"
    assert query_of(transport.last) == {"status": ["open"]}


def test_list_filters_are_checked(client_factory):
    transport, client = client_factory(ok({"items": []}))
    client.sanction().list_monitored_entities(active_only=False, include_total=True)
    assert query_of(transport.last) == {"activeOnly": ["false"], "includeTotal": ["true"]}
    with pytest.raises(ConfigurationError, match="does not accept the filter"):
        client.sanction().list_blacklist_entries(status="open")


def test_register_monitoring_sends_profile_as_json(client_factory):
    transport, client = client_factory(ok({"monitoredEntityId": "me-1"}))
    profile = {"name": "Test Person", "country": "TR"}
    client.sanction().register_monitoring(
        external_customer_id="cust-1",
        subject_type="person",
        risk_domain_scope=["sanctions"],
        profile=profile,
    )
    body = body_of(transport.last)
    assert json.loads(body["profileJson"]) == profile
    assert set(body) == {"externalCustomerId", "subjectType", "riskDomainScope", "profileJson"}
    with pytest.raises(ConfigurationError, match="not both"):
        client.sanction().register_monitoring(
            external_customer_id="cust-1", profile=profile, profile_json="{}"
        )
    with pytest.raises(ConfigurationError, match="riskDomainScope"):
        client.sanction().register_monitoring(
            external_customer_id="cust-1", risk_domain_scope=["crypto"]
        )


def test_entity_intelligence_paths_and_queries(client_factory):
    transport, client = client_factory(ok({"paths": []}), ok({"profile": {}}))
    client.sanction().get_indirect_exposure("ent-1", max_depth=2, entity_ids=["ent-1", "ent-2"])
    assert path_of(transport.last) == "/api/v1/sanction/intelligence/indirect-exposure/ent-1"
    assert query_of(transport.last) == {"maxDepth": ["2"], "entityIds": ["ent-1,ent-2"]}
    client.sanction().get_entity_profile("ent-1", screening_request_id="scr-1")
    assert query_of(transport.last) == {"screeningRequestId": ["scr-1"]}
    with pytest.raises(ConfigurationError, match="entityId is required"):
        client.sanction().get_entity_graph("")
