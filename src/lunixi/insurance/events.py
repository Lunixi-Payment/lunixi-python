"""The ``data`` of the insurance webhooks, read from a verified event.

.. code-block:: python

    event = client.webhooks(secret).verify(raw_body, request.headers)
    if event.type in InsuranceEvents.ORDER_EVENTS:
        order = InsuranceWebhookData.from_event(event)
    elif event.type in InsuranceEvents.LEAD_EVENTS:
        lead = InsuranceLeadWebhookData.from_event(event)

No other key is delivered and the payloads carry no personal data. Decide on
the order from the webhook; deduplicate on ``event_id`` (the envelope id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from .._events import event_data, int_field, text_field
from .values import InsuranceEvents

__all__ = [
    "InsuranceWebhookPolicy",
    "InsuranceWebhookData",
    "InsuranceWebhookLead",
    "InsuranceLeadWebhookData",
]


@dataclass(frozen=True)
class InsuranceWebhookPolicy:
    """One policy of an order event."""

    policy_id: Optional[str]
    basket_item_id: Optional[str]
    policy_number: Optional[str]
    policy_status: Optional[str]
    document_status: Optional[str]
    #: The policy document address while the policy is in force, otherwise an empty string.
    #: Downloading it is a signed API call (``get_policy_document``).
    document_url: Optional[str]

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "InsuranceWebhookPolicy":
        return cls(
            policy_id=text_field(data, "policyId"),
            basket_item_id=text_field(data, "basketItemId"),
            policy_number=text_field(data, "policyNumber"),
            policy_status=text_field(data, "policyStatus"),
            document_status=text_field(data, "documentStatus"),
            document_url=text_field(data, "documentUrl"),
        )


@dataclass(frozen=True)
class InsuranceWebhookData:
    """The ``data`` of every order ``insurance.*`` event (:attr:`InsuranceEvents.ORDER_EVENTS`)."""

    event_id: Optional[str]
    event_type: Optional[str]
    merchant_id: Optional[str]
    insurance_order_id: Optional[str]
    payment_intent_id: Optional[str]
    merchant_order_id: Optional[str]
    insurance_type: Optional[str]
    premium_collected_by: Optional[str]
    #: ``{code, name, logoUrl, connectionId}``.
    provider: Optional[Mapping[str, Any]]
    status: Optional[str]
    collection_status: Optional[str]
    policy_status: Optional[str]
    refund_status: Optional[str]
    document_status: Optional[str]
    #: Minor units.
    premium_amount: Optional[str]
    currency: Optional[str]
    policies: Tuple[InsuranceWebhookPolicy, ...]
    #: Only on ``insurance.policy.failed`` and ``insurance.refund.required``.
    error_code: Optional[str]
    created_at: Optional[str]
    raw: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "InsuranceWebhookData":
        data = event_data(event, InsuranceEvents.ORDER_EVENTS, "InsuranceWebhookData.from_event")
        provider = data.get("provider")
        policies = data.get("policies")
        return cls(
            event_id=text_field(data, "eventId"),
            event_type=text_field(data, "eventType"),
            merchant_id=text_field(data, "merchantId"),
            insurance_order_id=text_field(data, "insuranceOrderId"),
            payment_intent_id=text_field(data, "paymentIntentId"),
            merchant_order_id=text_field(data, "merchantOrderId"),
            insurance_type=text_field(data, "insuranceType"),
            premium_collected_by=text_field(data, "premiumCollectedBy"),
            provider=dict(provider) if isinstance(provider, Mapping) else None,
            status=text_field(data, "status"),
            collection_status=text_field(data, "collectionStatus"),
            policy_status=text_field(data, "policyStatus"),
            refund_status=text_field(data, "refundStatus"),
            document_status=text_field(data, "documentStatus"),
            premium_amount=text_field(data, "premiumAmount"),
            currency=text_field(data, "currency"),
            policies=tuple(
                InsuranceWebhookPolicy.from_data(policy)
                for policy in (policies if isinstance(policies, list) else [])
                if isinstance(policy, Mapping)
            ),
            error_code=text_field(data, "errorCode"),
            created_at=text_field(data, "createdAt"),
            raw=data,
        )


@dataclass(frozen=True)
class InsuranceWebhookLead:
    """The lead of an ``insurance.lead.*`` event: no personal data, no note, no provider reference."""

    lead_id: Optional[str]
    insurance_type: Optional[str]
    schema_version: Optional[int]
    status: Optional[str]
    submitted_at: Optional[str]
    created_at: Optional[str]


@dataclass(frozen=True)
class InsuranceLeadWebhookData:
    """The ``data`` of an ``insurance.lead.*`` event (:attr:`InsuranceEvents.LEAD_EVENTS`)."""

    event_id: Optional[str]
    event_type: Optional[str]
    merchant_id: Optional[str]
    lead: Optional[InsuranceWebhookLead]
    created_at: Optional[str]
    raw: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "InsuranceLeadWebhookData":
        reader = "InsuranceLeadWebhookData.from_event"
        data = event_data(event, InsuranceEvents.LEAD_EVENTS, reader)
        lead = data.get("lead")
        return cls(
            event_id=text_field(data, "eventId"),
            event_type=text_field(data, "eventType"),
            merchant_id=text_field(data, "merchantId"),
            lead=InsuranceWebhookLead(
                lead_id=text_field(lead, "leadId"),
                insurance_type=text_field(lead, "insuranceType"),
                schema_version=int_field(lead, "schemaVersion"),
                status=text_field(lead, "status"),
                submitted_at=text_field(lead, "submittedAt"),
                created_at=text_field(lead, "createdAt"),
            )
            if isinstance(lead, Mapping)
            else None,
            created_at=text_field(data, "createdAt"),
            raw=data,
        )
