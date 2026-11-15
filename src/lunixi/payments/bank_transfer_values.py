"""Para Transferi (``BANK_TRANSFER``: havale / EFT / FAST).

The buyer sends the money from their own bank to your bank account. The money
never passes through Lunixi: the incoming transaction is read from your
connected bank account and matched to the payment by the payment code in the
transfer description (or by the exact amount when there is no code).

* ``POST /api/v1/payments/direct/payment`` — ``bankTransfer: {"bankCode"}``, no provider code
* ``GET  /api/v1/payments/bank-transfer/exceptions`` — late, short and excess transfers
* ``POST /api/v1/payments/bank-transfer/exceptions/{id}/accept``
* ``POST /api/v1/payments/bank-transfer/exceptions/{id}/refunded``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from ..errors import ApiError, ConfigurationError
from .payment_method_values import PaymentActionType

__all__ = [
    "BANK_TRANSFER_OTHER_BANKS_CODE",
    "BANK_TRANSFER_EXCEPTION_LIMIT_MAX",
    "BANK_TRANSFER_EXCEPTION_ENVIRONMENTS",
    "PaymentBankTransferExceptionKind",
    "PaymentBankTransferExceptionStatus",
    "PaymentBankTransferEvents",
    "BankTransferInstruction",
    "bank_transfer_exceptions_query",
    "bank_transfer_exception_path",
]

#: The "Other banks" option of the ``bankCode`` field: the buyer pays by EFT/FAST
#: from a bank that is not listed.
BANK_TRANSFER_OTHER_BANKS_CODE = "9999"

#: Largest ``limit`` of ``list_bank_transfer_exceptions()``.
BANK_TRANSFER_EXCEPTION_LIMIT_MAX = 200

#: ``environment`` filter values of ``list_bank_transfer_exceptions()``.
BANK_TRANSFER_EXCEPTION_ENVIRONMENTS = ("TEST", "LIVE")


class PaymentBankTransferExceptionKind:
    """Kind of a bank transfer exception."""

    #: Arrived after the deadline (within 7 days).
    LATE = "LATE"
    #: The deadline passed with less than expected; the payment waits for your decision.
    UNDERPAID = "UNDERPAID"
    #: More than expected arrived; refund the excess.
    OVERPAID = "OVERPAID"


class PaymentBankTransferExceptionStatus:
    """Status of a bank transfer exception."""

    PENDING_DECISION = "PENDING_DECISION"
    ACCEPTED = "ACCEPTED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"

    ALL = (PENDING_DECISION, ACCEPTED, REFUND_PENDING, REFUNDED)


class PaymentBankTransferEvents:
    """Bank transfer webhook events of a payment (``payment.*`` envelope).

    The payload adds ``bankTransfer: {expectedMinor, receivedMinor,
    remainingMinor, excessMinor, currency, late, transfers[]}``; events that
    open an exception also carry ``exceptionId``, ``kind`` and ``amountMinor``.
    They do not change the payment's status: the outcome is still
    ``payment.captured`` / ``payment.failed``. Not to be confused with the
    ``bank_transfer.*`` events of Bank Connect.
    """

    PARTIALLY_RECEIVED = "payment.bank_transfer.partially_received"
    UNDERPAID = "payment.bank_transfer.underpaid"
    OVERPAID = "payment.bank_transfer.overpaid"
    LATE_ARRIVAL = "payment.bank_transfer.late_arrival"


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def bank_transfer_exceptions_query(
    environment: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, str]:
    """Query of ``GET /payments/bank-transfer/exceptions``; ``None`` filters are not sent."""
    query: Dict[str, str] = {}
    if environment is not None:
        if environment not in BANK_TRANSFER_EXCEPTION_ENVIRONMENTS:
            raise ConfigurationError(
                f"environment must be one of {', '.join(BANK_TRANSFER_EXCEPTION_ENVIRONMENTS)}; "
                f"got {environment!r}."
            )
        query["environment"] = environment
    if status is not None:
        if status not in PaymentBankTransferExceptionStatus.ALL:
            raise ConfigurationError(
                f"status must be one of {', '.join(PaymentBankTransferExceptionStatus.ALL)}; "
                f"got {status!r}."
            )
        query["status"] = status
    if limit is not None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= BANK_TRANSFER_EXCEPTION_LIMIT_MAX
        ):
            raise ConfigurationError(
                f"limit must be an integer between 1 and {BANK_TRANSFER_EXCEPTION_LIMIT_MAX}; "
                f"got {limit!r}."
            )
        query["limit"] = str(limit)
    return query


def bank_transfer_exception_path(base: str, exception_id: Any, decision: str) -> str:
    if not isinstance(exception_id, str) or _UUID.fullmatch(exception_id) is None:
        raise ConfigurationError(
            "exception_id must be the UUID of a bank transfer exception (items[].id)."
        )
    return f"{base}/bank-transfer/exceptions/{exception_id}/{decision}"


@dataclass(frozen=True)
class BankTransferInstruction:
    """The transfer instruction of a ``BANK_TRANSFER`` payment (``data.action.bankTransfer``).

    Show it to the buyer: the money goes to your own bank account.
    """

    #: 4-digit code of the bank the money is sent to.
    bank_code: str
    bank_name: str
    #: Account holder name; the buyer enters it as the recipient name.
    holder_name: str
    #: IBAN without spaces.
    iban: str
    #: Amount to send, canonical minor units.
    amount_minor: str
    currency: str
    #: Code the buyer writes in the transfer description; it matches the transfer to the payment.
    payment_code: str
    expires_at: str
    #: ``True`` when the buyer chose "Other banks" (``9999``): the instruction is for EFT/FAST.
    other_bank: bool

    @classmethod
    def from_response(cls, response: Any) -> Optional[BankTransferInstruction]:
        """Reads the instruction from a payment response envelope (or its ``data``).

        Returns ``None`` when the response has no action, the action is not
        ``DISPLAY``, or it carries no ``bankTransfer`` instruction. Raises
        :class:`~lunixi.errors.ApiError` for an instruction that cannot be shown.
        """
        if not isinstance(response, Mapping):
            return None
        data = response.get("data", response)
        action = data.get("action") if isinstance(data, Mapping) else None
        if not isinstance(action, Mapping) or action.get("type") != PaymentActionType.DISPLAY:
            return None
        instruction = action.get("bankTransfer")
        if not isinstance(instruction, Mapping):
            return None

        def text(key: str, required: bool) -> str:
            value = instruction.get(key)
            if isinstance(value, str) and value != "":
                return value
            if value is None and not required:
                return ""
            raise ApiError("The gateway returned an unreadable bank transfer instruction.")

        other_bank = instruction.get("otherBank", False)
        if not isinstance(other_bank, bool):
            raise ApiError("The gateway returned an unreadable bank transfer instruction.")
        return cls(
            bank_code=text("bankCode", True),
            bank_name=text("bankName", False),
            holder_name=text("holderName", True),
            iban=text("iban", True),
            amount_minor=text("amountMinor", True),
            currency=text("currency", True),
            payment_code=text("paymentCode", False),
            expires_at=text("expiresAt", False),
            other_bank=other_bank,
        )
