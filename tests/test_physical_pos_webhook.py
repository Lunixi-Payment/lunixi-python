"""Physical POS webhooks: catalogue, verification inside the reader (O-3), payload resolution.

Contract source: nest-payment-gateway libs/proto/src/physical-pos-webhook.interface.ts
and apps/webhook-service/src/deliveries/policies/physical-pos-webhook.policy.ts.
Ids, secrets and values below are synthetic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from lunixi.errors import ConfigurationError, WebhookVerificationError
from lunixi.physical_pos import (
    PHYSICAL_POS_EVENT_PATTERN,
    PHYSICAL_POS_EVENT_TYPES,
    PhysicalPosClient,
    PhysicalPosEvents,
    parse_webhook_event,
)
from lunixi.webhook.verifier import WebhookVerifier

SECRET = "whsec_synthetic_physical_pos_0001"
EVENT_ID = "evt_pos_0001"

PAYLOAD = {
    "paymentId": "0192f3a1-0000-7000-8000-000000000001",
    "rootPaymentId": "0192f3a1-0000-7000-8000-000000000001",
    "operation": "SALE",
    "paymentStatus": "APPROVED",
    "statusReason": "DEVICE_RESULT_APPROVED",
    "amountMinor": "4500",
    "approvedAmountMinor": "4500",
    "currency": "TRY",
    "installmentCount": None,
    "deviceId": "5f0c2b1e-1111-4222-8333-444455556666",
    "merchantReference": "ORD-2026-000123",
    "tender": {"cardMasked": "454360******1234", "cardBrand": "VISA", "entryMode": "CONTACTLESS"},
    "historySeq": 4,
    "resolvedBy": None,
}


def envelope(**overrides):
    body = {
        "id": EVENT_ID,
        "type": PhysicalPosEvents.PAYMENT_APPROVED,
        "sourceService": "physical-pos-service",
        "organizationId": "org_synthetic",
        "productCode": "PHYSICAL_POS",
        "environment": "LIVE",
        "eventVersion": 1,
        "schemaVersion": "v1",
        "createdAt": "2026-10-30T09:00:05.000Z",
        "data": PAYLOAD,
    }
    body.update(overrides)
    return body


def signed(body):
    raw = json.dumps(body, separators=(",", ":")).encode()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    signature = hmac.new(SECRET.encode(), f"{EVENT_ID}.{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    headers = {
        "x-lunixi-event-id": EVENT_ID,
        "x-lunixi-event-type": body.get("type", ""),
        "x-lunixi-signature-timestamp": timestamp,
        "x-lunixi-signature": f"v2={signature}",
    }
    return raw, headers


def test_catalogue():
    assert PHYSICAL_POS_EVENT_PATTERN == "physical_pos.*"
    assert len(PHYSICAL_POS_EVENT_TYPES) == 13
    assert len(set(PHYSICAL_POS_EVENT_TYPES)) == 13
    assert PhysicalPosEvents.PAYMENT_DEVICE_SALE == "physical_pos.payment.device_sale"
    assert PhysicalPosEvents.PAYMENT_DEVICE_SALE in PHYSICAL_POS_EVENT_TYPES
    assert all(t.startswith("physical_pos.") for t in PHYSICAL_POS_EVENT_TYPES)
    assert "physical_pos.payment.created" not in PHYSICAL_POS_EVENT_TYPES
    assert "physical_pos.payment.in_progress" not in PHYSICAL_POS_EVENT_TYPES
    assert PhysicalPosEvents.PAYMENT_PARTIALLY_APPROVED == "physical_pos.payment.partially_approved"
    assert PhysicalPosEvents.FISCAL_DOCUMENT_ACTION_REQUIRED == "physical_pos.fiscal_document.action_required"


def test_a_signed_event_is_verified_and_read():
    raw, headers = signed(envelope())
    event = parse_webhook_event(raw, headers, SECRET)
    assert event.id == EVENT_ID
    assert event.type == PhysicalPosEvents.PAYMENT_APPROVED
    assert event.category == "payment"
    assert event.environment == "LIVE"
    assert event.created_at == "2026-10-30T09:00:05.000Z"
    assert event.history_seq == 4
    assert event.data["amountMinor"] == "4500"
    assert "authCode" not in event.data


def test_a_device_sale_and_its_refund_are_read():
    sale = dict(
        PAYLOAD,
        original=None,
        statusReason=None,
        merchantReference=None,
        historySeq=1,
        origin="DEVICE_DIRECT",
        deviceOccurredAt="2026-11-01T18:42:10.123Z",
    )
    raw, headers = signed(envelope(type=PhysicalPosEvents.PAYMENT_DEVICE_SALE, data=sale))
    event = parse_webhook_event(raw, headers, SECRET)
    assert event.is_device_sale is True
    assert event.category == "payment"
    assert event.original is None
    assert event.history_seq == 1
    assert event.data["origin"] == "DEVICE_DIRECT"
    assert event.data["deviceOccurredAt"] == "2026-11-01T18:42:10.123Z"

    refund = dict(
        PAYLOAD,
        paymentId="0192f3a1-0000-7000-8000-000000000002",
        operation="REFUND",
        historySeq=3,
        original={"paymentId": PAYLOAD["paymentId"], "origin": "DEVICE_DIRECT"},
    )
    raw, headers = signed(envelope(data=refund))
    child = parse_webhook_event(raw, headers, SECRET)
    assert child.is_device_sale is False
    assert child.original == {"paymentId": PAYLOAD["paymentId"], "origin": "DEVICE_DIRECT"}


def test_a_configured_verifier_is_accepted():
    raw, headers = signed(envelope())
    event = PhysicalPosClient.parse_webhook_event(raw.decode(), headers, WebhookVerifier(SECRET))
    assert event.id == EVENT_ID


def test_a_tampered_body_is_refused():
    raw, headers = signed(envelope())
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(raw.replace(b"4500", b"9900"), headers, SECRET)


def test_a_wrong_secret_is_refused():
    raw, headers = signed(envelope())
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(raw, headers, "whsec_synthetic_other_secret")


@pytest.mark.parametrize("drop", ["x-lunixi-signature", "x-lunixi-signature-timestamp", "x-lunixi-event-id"])
def test_a_forged_envelope_without_signature_headers_is_refused(drop):
    raw, headers = signed(envelope())
    del headers[drop]
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(raw, headers, SECRET)


@pytest.mark.parametrize(
    "forged",
    [
        envelope(),
        json.dumps(envelope()),
    ],
)
def test_a_decoded_or_unsigned_envelope_is_never_read(forged):
    # The old "decoded envelope" path is gone: without signature headers nothing verifies.
    with pytest.raises((WebhookVerificationError, TypeError)):
        parse_webhook_event(forged)  # type: ignore[call-arg]
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(forged if isinstance(forged, str) else json.dumps(forged), {}, SECRET)


def test_a_verifier_result_object_is_not_accepted_as_input():
    raw, headers = signed(envelope())
    verified = WebhookVerifier(SECRET).verify(raw, headers)
    with pytest.raises((WebhookVerificationError, TypeError, ConfigurationError)):
        parse_webhook_event(verified)  # type: ignore[call-arg]


def test_a_missing_secret_is_a_configuration_error():
    raw, headers = signed(envelope())
    with pytest.raises(ConfigurationError):
        parse_webhook_event(raw, headers, None)  # type: ignore[arg-type]


def test_payload_json_object_is_resolved():
    body = envelope(payloadJson=PAYLOAD)
    del body["data"]
    raw, headers = signed(body)
    event = PhysicalPosClient.parse_webhook_event(raw, headers, SECRET)
    assert event.data["paymentId"] == PAYLOAD["paymentId"]


def test_payload_json_string_is_decoded():
    body = envelope(payloadJson=json.dumps(PAYLOAD))
    del body["data"]
    raw, headers = signed(body)
    event = parse_webhook_event(raw, headers, SECRET)
    assert event.data["paymentStatus"] == "APPROVED"
    assert event.history_seq == 4


def test_a_deeply_nested_payload_json_is_a_verification_error():
    deep = "[" * 100000 + "]" * 100000
    body = envelope(payloadJson=deep)
    del body["data"]
    raw, headers = signed(body)
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(raw, headers, SECRET)


def test_fiscal_and_future_types_get_a_category():
    raw, headers = signed(
        envelope(type=PhysicalPosEvents.FISCAL_DOCUMENT_ISSUED, data={"documentId": "d1", "historySeq": 2})
    )
    fiscal = parse_webhook_event(raw, headers, SECRET)
    assert fiscal.category == "fiscal_document"
    raw, headers = signed(envelope(type="physical_pos.device.offline", data={"deviceId": "x"}))
    later = parse_webhook_event(raw, headers, SECRET)
    assert later.category == "other"
    assert later.history_seq is None


@pytest.mark.parametrize(
    "body",
    [
        envelope(type="bank_connect.account.updated"),
        envelope(data={}),
        envelope(data=None),
        {**{k: v for k, v in envelope().items() if k != "data"}, "payloadJson": "{not json"},
    ],
)
def test_foreign_or_empty_events_are_refused(body):
    raw, headers = signed(body)
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(raw, headers, SECRET)
