"""Identity signals: bearer-only routes, the analyze body and the shared-device helpers.

Names in the fixtures are fictional.
"""

from __future__ import annotations

import pytest

from lunixi.errors import ConfigurationError
from lunixi.identity import (
    IDENTITY_ROUTES,
    IdentityClient,
    identity_link_reasons,
    is_identity_device_shared,
)

from .support.recording_transport import envelope, json_response
from .support.wire import assert_unsigned, body_of, path_of


def ok(data):
    return json_response(envelope(data))


def test_routes_are_bearer_only_under_live_sessions(client_factory):
    _, client = client_factory()
    assert isinstance(client.identity(), IdentityClient)
    for name, route in IDENTITY_ROUTES.items():
        assert route["stepUp"] is False, name
        assert route["path"].startswith("/api/v1/identity/live-sessions"), name


def test_analyze_sync_sends_the_signal_body_and_returns_the_trace(client_factory):
    analysis = {
        "traceId": "tr_1",
        "analysisStatus": "completed",
        "riskFlags": ["same_device_cluster"],
        "identitySnapshot": {"decisionGrade": True},
    }
    transport, client = client_factory(ok(analysis), ok({"traceId": "tr_2"}))
    identity = client.identity()
    result = identity.analyze_sync(
        subject_type="user",
        subject_id="42",
        device={"deviceId": "fp_1", "ipAddress": "203.0.113.7"},
        account={"accountId": "42"},
    )
    assert result == analysis
    request = transport.last
    assert path_of(request) == "/api/v1/identity/live-sessions/analyze-sync"
    assert_unsigned(request)
    assert body_of(request)["device"] == {"deviceId": "fp_1", "ipAddress": "203.0.113.7"}
    assert body_of(request)["subjectType"] == "user"

    identity.analyze(payment_id="pay_1")
    assert path_of(transport.last) == "/api/v1/identity/live-sessions/analyze"
    assert body_of(transport.last) == {"paymentId": "pay_1"}


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"subjectId": "42"}, "subjectType and subjectId go together"),
        ({"verdict": "allow"}, "does not accept verdict"),
        ({"device": "fp_1"}, "device must be a mapping"),
    ],
)
def test_a_broken_analyze_body_is_refused_before_sending(client_factory, fields, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.identity().analyze_sync(fields)
    assert transport.requests == []


def test_account_links_detect_a_shared_device(client_factory):
    links = {
        "totalLinkedSessions": 3,
        "linkedAccounts": ["h_a"],
        "sessions": [
            {"linkReasons": ["same_fingerprint"]},
            {"linkReasons": ["same_fingerprint", "same_ip_asn"]},
        ],
    }
    transport, client = client_factory(ok(links))
    result = client.identity().account_links("tr_1")
    assert path_of(transport.last) == "/api/v1/identity/live-sessions/tr_1/account-links"
    assert is_identity_device_shared(result) is True
    assert is_identity_device_shared(result, 3) is False
    assert identity_link_reasons(result) == ["same_fingerprint", "same_ip_asn"]
    assert is_identity_device_shared({"linkedAccounts": []}) is False


def test_session_reads_related_sessions_timeline_top_sources_and_lists(client_factory):
    transport, client = client_factory(*(ok({"items": [{"traceId": "tr_1"}]}) for _ in range(5)))
    identity = client.identity()
    identity.get_session("tr_1")
    identity.related_sessions("tr_1", 5)
    identity.timeline("tr_1")
    identity.top_sources(days=7, limit=10)
    page = identity.list_sessions(device_id="fp_1")
    session, related, timeline, sources, sessions = transport.requests[1:]
    assert path_of(session) == "/api/v1/identity/live-sessions/tr_1"
    assert related.url.endswith("/api/v1/identity/live-sessions/tr_1/related-sessions?limit=5")
    assert path_of(timeline) == "/api/v1/identity/live-sessions/tr_1/timeline"
    assert sources.url.endswith("/api/v1/identity/live-sessions/top-sources?days=7&limit=10")
    assert sessions.url.endswith("/api/v1/identity/live-sessions?deviceId=fp_1")
    assert page.items == [{"traceId": "tr_1"}]
    with pytest.raises(ConfigurationError, match="does not accept the filter"):
        identity.list_sessions(email="ada@example.com")
    assert len(transport.requests) == 6
