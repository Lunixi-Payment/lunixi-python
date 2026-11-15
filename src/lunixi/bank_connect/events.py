"""The ``data`` of the bank-connect webhooks, read from a verified event.

.. code-block:: python

    event = client.webhooks(secret).verify(raw_body, request.headers)
    if event.type == BankConnectEvents.TRANSACTION_RECEIVED:
        received = BankAccountTransactionReceived.from_event(event)
    elif event.type in BankTransferEvents.ALL:
        transfer = BankTransferWebhookData.from_event(event)

Values the bank did not send are ``None``; amounts are minor-unit strings.
Deduplicate on the event id: it is the same on every redelivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .._events import event_data, text_field
from .values import BankConnectEvents, BankTransferEvents

__all__ = ["BankAccountTransactionReceived", "BankTransferWebhookData"]


@dataclass(frozen=True)
class BankAccountTransactionReceived:
    """``bank_account.transaction.received``: a new transaction on a connected account."""

    transaction_id: Optional[str]
    account_id: Optional[str]
    connection_id: Optional[str]
    bank_eft_code: Optional[str]
    bank_name: Optional[str]
    direction: Optional[str]
    amount_minor: Optional[str]
    currency: Optional[str]
    booked_at: Optional[str]
    value_at: Optional[str]
    received_at: Optional[str]
    canonical_type: Optional[str]
    description: Optional[str]
    counterparty_name_masked: Optional[str]
    counterparty_iban_masked: Optional[str]
    receipt_no: Optional[str]
    raw: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "BankAccountTransactionReceived":
        reader = "BankAccountTransactionReceived.from_event"
        data = event_data(event, BankConnectEvents.ALL, reader)
        return cls(
            transaction_id=text_field(data, "transactionId"),
            account_id=text_field(data, "accountId"),
            connection_id=text_field(data, "connectionId"),
            bank_eft_code=text_field(data, "bankEftCode"),
            bank_name=text_field(data, "bankName"),
            direction=text_field(data, "direction"),
            amount_minor=text_field(data, "amountMinor"),
            currency=text_field(data, "currency"),
            booked_at=text_field(data, "bookedAt"),
            value_at=text_field(data, "valueAt"),
            received_at=text_field(data, "receivedAt"),
            canonical_type=text_field(data, "canonicalType"),
            description=text_field(data, "description"),
            counterparty_name_masked=text_field(data, "counterpartyNameMasked"),
            counterparty_iban_masked=text_field(data, "counterpartyIbanMasked"),
            receipt_no=text_field(data, "receiptNo"),
            raw=data,
        )


@dataclass(frozen=True)
class BankTransferWebhookData:
    """``bank_transfer.created|completed|failed|returned``: an outgoing transfer changed."""

    transfer_id: Optional[str]
    connection_id: Optional[str]
    account_id: Optional[str]
    bank_eft_code: Optional[str]
    bank_name: Optional[str]
    status: Optional[str]
    rail: Optional[str]
    amount_minor: Optional[str]
    currency: Optional[str]
    receiver_iban_masked: Optional[str]
    receiver_name_masked: Optional[str]
    payment_purpose: Optional[str]
    description: Optional[str]
    failure_code: Optional[str]
    idempotency_key: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]
    failed_at: Optional[str]
    returned_at: Optional[str]
    raw: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "BankTransferWebhookData":
        data = event_data(event, BankTransferEvents.ALL, "BankTransferWebhookData.from_event")
        return cls(
            transfer_id=text_field(data, "transferId"),
            connection_id=text_field(data, "connectionId"),
            account_id=text_field(data, "accountId"),
            bank_eft_code=text_field(data, "bankEftCode"),
            bank_name=text_field(data, "bankName"),
            status=text_field(data, "status"),
            rail=text_field(data, "rail"),
            amount_minor=text_field(data, "amountMinor"),
            currency=text_field(data, "currency"),
            receiver_iban_masked=text_field(data, "receiverIbanMasked"),
            receiver_name_masked=text_field(data, "receiverNameMasked"),
            payment_purpose=text_field(data, "paymentPurpose"),
            description=text_field(data, "description"),
            failure_code=text_field(data, "failureCode"),
            idempotency_key=text_field(data, "idempotencyKey"),
            created_at=text_field(data, "createdAt"),
            completed_at=text_field(data, "completedAt"),
            failed_at=text_field(data, "failedAt"),
            returned_at=text_field(data, "returnedAt"),
            raw=data,
        )
