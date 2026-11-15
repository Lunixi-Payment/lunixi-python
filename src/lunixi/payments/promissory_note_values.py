"""Senetle Ödeme (promissory-note payment, ``paymentMethod: PROMISSORY_NOTE``).

* ``POST /api/v1/payments/direct/payment`` — the ``promissoryNote`` block
* ``GET  /api/v1/payments/{paymentId}/promissory-notes`` — notes and their status
* ``POST /api/v1/payments/{paymentId}/promissory-notes/cancel`` — cancel notes
* ``GET  /api/v1/payments/{paymentId}/promissory-notes/document`` — printable PDF

The plan is a schedule (``[{"amount", "dueDate"}]``) or a note count
(``noteCount``), never both. The SDK checks what it can without the provider
connection: canonical minor-unit amounts that add up to the payment amount,
``YYYY-MM-DD`` calendar dates in ascending order and at most 24 rows. That a due
date lies in the future and that the note count fits your provider connection
is checked by the gateway (400 ``payment.method.block_invalid``).
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Mapping, Optional

from ..errors import ConfigurationError
from ..validation import amount_minor

__all__ = [
    "PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS",
    "PromissoryNoteStatus",
    "PromissoryNoteDocumentType",
    "PromissoryNoteCancelResult",
    "PromissoryNoteCancelErrorCode",
    "PromissoryNoteDocumentLocale",
    "PromissoryNoteEvents",
    "require_promissory_note_schedule",
    "assert_schedule_matches_amount",
    "require_note_count",
    "assert_promissory_note_plan",
    "require_serial_numbers",
    "require_document_locale",
]

#: Most rows of a schedule (and most notes of a payment).
PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS = 24


class PromissoryNoteStatus:
    """Status of one note (``notes[].status``)."""

    ISSUED = "ISSUED"
    PAID = "PAID"
    PROTESTED = "PROTESTED"
    CANCELLED = "CANCELLED"


class PromissoryNoteDocumentType:
    """Document type of the issued notes, from your provider connection settings."""

    PROMISSORY_NOTE = "PROMISSORY_NOTE"
    PAYMENT_ORDER = "PAYMENT_ORDER"


class PromissoryNoteCancelResult:
    """Per-note result of ``cancel_promissory_notes()`` (``cancelResults[].result``)."""

    CANCELLED = "CANCELLED"
    #: The note was already cancelled.
    ALREADY_CLOSED = "ALREADY_CLOSED"
    #: The note was collected or protested; it cannot be cancelled.
    NOT_CANCELLABLE = "NOT_CANCELLABLE"
    #: The note was not cancelled; ``errorCode`` tells whether to try again.
    FAILED = "FAILED"


class PromissoryNoteCancelErrorCode:
    """``cancelResults[].errorCode``: a Lunixi code (``None`` for a cancelled or closed note)."""

    NOT_CANCELLABLE = "payment.promissory_note.not_cancellable"
    #: Temporary: cancel again later.
    PROVIDER_UNAVAILABLE = "payment.promissory_note.provider_unavailable"
    #: Permanent: the cancellation was refused.
    CANCEL_REJECTED = "payment.promissory_note.cancel_rejected"


class PromissoryNoteDocumentLocale:
    """Language of the printable notes."""

    TR = "tr-TR"
    EN = "en-GB"


class PromissoryNoteEvents:
    """Webhook event types of a note (payload ``promissoryNote``)."""

    PAID = "payment.promissory_note.paid"
    PROTESTED = "payment.promissory_note.protested"
    CANCELLED = "payment.promissory_note.cancelled"


_DUE_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_NOTE_COUNT = re.compile(r"[1-9][0-9]?")
_SERIAL_NUMBER = re.compile(r"[A-Za-z0-9-]{4,64}")


def _is_calendar_date(value: str) -> bool:
    match = _DUE_DATE.fullmatch(value)
    if match is None:
        return False
    try:
        datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


def require_promissory_note_schedule(
    value: Any, path: str = "promissoryNote.schedule"
) -> List[Dict[str, str]]:
    """Checks a schedule (1–24 ``{"amount", "dueDate"}`` rows, due-date order); returns a copy."""
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        raise ConfigurationError(f"{path} must be a non-empty list of {{amount, dueDate}} rows.")
    if len(value) > PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS:
        raise ConfigurationError(
            f"{path} can have at most {PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS} rows; got {len(value)}."
        )
    rows: List[Dict[str, str]] = []
    previous: Optional[str] = None
    for index, row in enumerate(value):
        row_path = f"{path}[{index}]"
        if not isinstance(row, Mapping):
            raise ConfigurationError(f"{row_path} must be an object {{amount, dueDate}}.")
        unknown = [key for key in row if key not in ("amount", "dueDate")]
        if unknown:
            raise ConfigurationError(
                f"{row_path} has unknown field(s): {', '.join(map(str, unknown))}. "
                "A row is {amount, dueDate}."
            )
        amount_minor(row.get("amount"))
        due_date = row.get("dueDate")
        if not isinstance(due_date, str) or not _is_calendar_date(due_date):
            raise ConfigurationError(
                f"{row_path}.dueDate must be a calendar date in YYYY-MM-DD form; got {due_date!r}."
            )
        if previous is not None and due_date < previous:
            raise ConfigurationError(
                f"{row_path}.dueDate must not be earlier than the previous row ({previous}); "
                "list the notes in due-date order."
            )
        previous = due_date
        rows.append({"amount": row["amount"], "dueDate": due_date})
    return rows


def assert_schedule_matches_amount(
    schedule: List[Dict[str, str]], amount: str, path: str = "promissoryNote.schedule"
) -> None:
    total = sum(int(row["amount"]) for row in schedule)
    if total != int(amount_minor(amount)):
        raise ConfigurationError(f"{path} adds up to {total}; it must equal amount ({amount}).")


def require_note_count(value: Any, path: str = "promissoryNote.noteCount") -> str:
    """A note count of 1–24 (integer or digit string), returned as the string that is sent."""
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if (
        not isinstance(text, str)
        or _NOTE_COUNT.fullmatch(text) is None
        or int(text) > PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS
    ):
        raise ConfigurationError(
            f"{path} must be a number of notes from 1 to {PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS}; "
            f"got {value!r}."
        )
    return text


def assert_promissory_note_plan(
    block: Any, amount: Optional[str], path: str = "promissoryNote"
) -> None:
    """Exactly one of ``schedule`` or ``noteCount``; a schedule adds up to ``amount``."""
    if not isinstance(block, Mapping):
        raise ConfigurationError(f"{path} must be an object.")
    has_schedule = block.get("schedule") is not None
    has_note_count = block.get("noteCount") is not None
    if has_schedule and has_note_count:
        raise ConfigurationError(f"{path}: send either schedule or noteCount, not both.")
    if not has_schedule and not has_note_count:
        raise ConfigurationError(
            f"{path} needs the plan: a schedule ([{{amount, dueDate}}]) or a noteCount."
        )
    if has_note_count:
        require_note_count(block["noteCount"], f"{path}.noteCount")
        return
    schedule = require_promissory_note_schedule(block["schedule"], f"{path}.schedule")
    if amount is not None:
        assert_schedule_matches_amount(schedule, amount, f"{path}.schedule")


def require_serial_numbers(values: Any) -> List[str]:
    """1–24 note serial numbers (letters, digits and ``-``, 4–64 characters)."""
    if (
        not isinstance(values, (list, tuple))
        or len(values) == 0
        or len(values) > PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS
    ):
        raise ConfigurationError(
            f"serial_numbers must be a list of 1 to {PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS} note "
            "serial numbers (from payments().get_promissory_notes()); leave it out to cancel "
            "every open note."
        )
    for value in values:
        if not isinstance(value, str) or _SERIAL_NUMBER.fullmatch(value) is None:
            raise ConfigurationError(
                f"serial_numbers contains an invalid serial number {value!r} "
                "(letters, digits and -, 4 to 64 characters)."
            )
    return list(values)


def require_document_locale(value: Any) -> str:
    allowed = (PromissoryNoteDocumentLocale.TR, PromissoryNoteDocumentLocale.EN)
    if value not in allowed:
        raise ConfigurationError(f"locale must be one of {', '.join(allowed)}; got {value!r}.")
    return value
