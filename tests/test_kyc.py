"""KYC: bearer-only session calls, the session body rules, list filters and paging.

Names in the fixtures are fictional.
"""

from __future__ import annotations

import pytest

from lunixi.errors import ConfigurationError
from lunixi.kyc import (
    KYC_ROUTES,
    KycAssuranceDomain,
    KycAssuranceLevel,
    KycClient,
    KycEvents,
    KycSessionStatus,
    KycSessionType,
    is_kyc_session_terminal,
    kyc_assurance_meets,
)

from .support.recording_transport import envelope, json_response
from .support.wire import assert_unsigned, body_of, path_of, query_of


def ok(data):
    return json_response(envelope(data))


def test_every_route_is_bearer_only_under_the_kyc_prefix(client_factory):
    _, client = client_factory()
    assert isinstance(client.kyc(), KycClient)
    for name, route in KYC_ROUTES.items():
        assert route["stepUp"] is False, name
        assert route["path"].startswith("/api/v1/kyc/"), name
        assert "/sdk/init" not in route["path"], name


def test_values_and_helpers():
    assert KycEvents.MONITORING_ALERT_CREATED == "ongoing_monitoring.alert.created"
    assert KycEvents.KYB_RELATED_KYC_COMPLETED == "kyb.related_kyc.completed"
    assert len(KycEvents.ALL) == 25
    assert KycAssuranceDomain.BIOMETRIC == "possession_biometric_binding"
    assert len(KycSessionStatus.ALL) == 17
    assert is_kyc_session_terminal("manual_review") is True
    assert is_kyc_session_terminal("PROCESSING") is False
    assert kyc_assurance_meets(KycAssuranceLevel.HIGH, KycAssuranceLevel.SUBSTANTIAL) is True
    assert kyc_assurance_meets(KycAssuranceLevel.NOT_PERFORMED, KycAssuranceLevel.LOW) is False


def test_create_session_maps_person_and_metadata_and_sends_the_key(client_factory):
    session = {"session": {"sessionId": "sess_1", "status": "CREATED"}}
    transport, client = client_factory(ok(session))
    result = client.kyc().create_session(
        subject_id="42",
        session_type="kyc",
        external_customer_id="42",
        jurisdiction="TR",
        person={"firstName": "Ada"},
        metadata={"orderId": "o-1"},
        idempotency_key="idem-kyc-1",
    )
    assert result == session
    request = transport.last
    assert (request.method, path_of(request)) == ("POST", "/api/v1/kyc/sessions")
    assert_unsigned(request)
    assert request.header("Idempotency-Key") == "idem-kyc-1"
    assert body_of(request) == {
        "subjectId": "42",
        "sessionType": "KYC",
        "externalCustomerId": "42",
        "jurisdiction": "TR",
        "customer": {"customerType": "PERSON", "firstName": "Ada"},
        "evidenceContextJson": '{"orderId":"o-1"}',
        "idempotencyKey": "idem-kyc-1",
    }


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"subjectId": "42", "sessionType": "AML"}, "sessionType must be one of"),
        (
            {"subjectId": "42", "sessionType": KycSessionType.KYB, "person": {}, "company": {}},
            "one of person, company or customer",
        ),
        ({"subjectId": "42", "sessionType": "KYC", "ttlMinutes": 2000}, "ttlMinutes"),
        ({"subjectId": "42", "sessionType": "KYC", "status": "APPROVED"}, "not accept status"),
        ({"subjectId": "42", "sessionType": "KYC", "requiredDocumentTypes": "ID"}, "list"),
        ({"sessionType": "KYC"}, "requires subjectId"),
    ],
)
def test_create_session_is_refused_before_sending(client_factory, fields, message):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError, match=message):
        client.kyc().create_session(fields)
    assert transport.requests == []


def test_list_sessions_takes_only_limit_and_cursor(client_factory):
    rows = {"items": [{"sessionId": "s1"}, {"sessionId": "s2"}], "nextCursor": "tok2"}
    transport, client = client_factory(ok(rows))
    page = client.kyc().list_sessions(page_size=2, page_token="abc")
    assert [row["sessionId"] for row in page.items] == ["s1", "s2"]
    assert page.next_cursor == "tok2"
    assert page.has_more is True
    assert transport.last.url.endswith("/api/v1/kyc/sessions?limit=2&cursor=abc")
    with pytest.raises(ConfigurationError, match=r"does not accept the filter\(s\) status"):
        client.kyc().list_sessions(status="APPROVED")
    assert len(transport.requests) == 2


def test_a_page_info_without_a_cursor_is_the_last_page(client_factory):
    rows = {
        "items": [{"sessionId": "s1"}],
        "nextCursor": "stale",
        "pageInfo": {"hasMore": False, "nextCursor": None},
    }
    _, client = client_factory(ok(rows))
    page = client.kyc().list_sessions()
    assert page.next_cursor is None
    assert page.has_more is False


def test_iterate_sessions_follows_the_cursor(client_factory):
    transport, client = client_factory(
        ok({"items": [{"sessionId": "s1"}], "nextCursor": "c2"}),
        ok({"items": [{"sessionId": "s2"}]}),
    )
    rows = list(client.kyc().iterate_sessions(limit=1))
    assert [row["sessionId"] for row in rows] == ["s1", "s2"]
    assert query_of(transport.last) == {"limit": ["1"], "cursor": ["c2"]}


def test_session_operations_and_admin_routes(client_factory):
    transport, client = client_factory(*(ok({}) for _ in range(10)))
    kyc = client.kyc()
    kyc.set_primary_document("sess_1", "PASSPORT")
    kyc.set_jurisdiction("sess_1", "TR")
    kyc.submit("sess_1")
    kyc.manual_review("sess_1")
    kyc.manual_review("sess_1", reason_code="DOC_BLUR")
    kyc.merchant_policy()
    kyc.rotate_webhook_secret()
    kyc.webhook_outbox(status="FAILED", limit=10)
    kyc.retry_webhook_event("evt_1")
    kyc.erasure_requests(limit=5)
    (
        primary,
        jurisdiction,
        submit,
        review,
        review_reason,
        policy,
        rotate,
        outbox,
        retry,
        erasure,
    ) = transport.requests[1:]
    assert path_of(primary) == "/api/v1/kyc/sessions/sess_1/primary-document"
    assert body_of(primary) == {"documentType": "PASSPORT"}
    assert body_of(jurisdiction) == {"jurisdiction": "TR"}
    assert submit.body is None
    assert review.body is None
    assert body_of(review_reason) == {"reasonCode": "DOC_BLUR"}
    assert path_of(policy) == "/api/v1/kyc/admin/merchant-policy"
    assert path_of(rotate) == "/api/v1/kyc/admin/merchant-policy/webhook-secret/rotate"
    assert outbox.url.endswith("/admin/webhook-outbox?status=FAILED&limit=10")
    assert path_of(retry) == "/api/v1/kyc/admin/webhook-outbox/evt_1/retry"
    assert erasure.url.endswith("/admin/erasure-requests?limit=5")
    for request in transport.requests[1:]:
        assert_unsigned(request)


def test_upload_document_never_echoes_the_image(client_factory):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError) as raised:
        client.kyc().upload_document(
            "sess_1",
            document_type="PASSPORT",
            file_base64="SECRETIMAGEDATA",
            mime_type="image/jpeg",
            extra="SECRETIMAGEDATA",
        )
    assert "extra" in str(raised.value)
    assert "SECRETIMAGEDATA" not in str(raised.value)
    assert transport.requests == []


def test_evidence_request_uses_its_own_route(client_factory):
    transport, client = client_factory(ok({"session": {"sessionId": "ev_1"}}))
    client.kyc().evidence_request(
        subject_id="42",
        session_type=KycSessionType.EVIDENCE,
        evidence_purpose="PROOF_OF_ADDRESS",
        company={"legalName": "Kurgu Ltd."},
    )
    assert path_of(transport.last) == "/api/v1/kyc/evidence-requests"
    assert transport.last.header("Idempotency-Key") is None
    assert body_of(transport.last)["customer"] == {
        "customerType": "COMPANY",
        "legalName": "Kurgu Ltd.",
    }
