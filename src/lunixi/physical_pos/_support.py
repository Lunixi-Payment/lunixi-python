"""Shared request checks and error translation for the physical POS clients.

Shape and canonical money are checked here — known fields, JSON types, the Idempotency-Key
format. Value rules (operation set, ranges, item totals, target uniqueness)
stay on the gateway, which answers with a typed ``physical_pos.*`` code.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple, TypeVar

from ..api_client import _backoff
from ..errors import (
    ApiError,
    ConfigurationError,
    LunixiError,
    PhysicalPosCardDataRejectedError,
    PhysicalPosOutcomeUnknownError,
    PhysicalPosRateLimitError,
    PhysicalPosVoidAfterSettlementError,
    RateLimitError,
)
from ..http.envelope import data_of
from ..http.transport import encode_path_segment
from ..validation import SAFE_INTEGER, amount_minor
from .card_data import (
    PAN_SCAN_ITEM_TEXT,
    PAN_SCAN_STRICT,
    contains_pan_like_value,
    find_card_data_field,
)
from .money import validate_response_money
from .values import (
    IDEMPOTENCY_KEY_PATTERN,
    PHYSICAL_POS_FILTERS,
    PHYSICAL_POS_FREE_TEXT_FILTERS,
    PHYSICAL_POS_NOT_STARTED_CODES,
)

BASE = "/api/v1/physical-pos"
ROW_VERSION_MAX = 2_147_483_647
_KEY = re.compile(IDEMPOTENCY_KEY_PATTERN)

T = TypeVar("T")

#: Field rules: a kind name (``str``, ``int``, ``bool``, ``row_version``,
#: ``str_list``), a nested schema, or ``("list", schema)``.
#: wire name → (kind, required, nullable). ``nullable`` sends an explicit
#: ``None`` as JSON null (PATCH "clear"); otherwise ``None`` drops the field.
Schema = Dict[str, Tuple[Any, bool, bool]]


def new_idempotency_key() -> str:
    """A new random UUID v4 for one operation."""
    return str(uuid.uuid4())


def checked_idempotency_key(value: Any) -> str:
    """A given key, checked as it is: never trimmed; empty or blank keys are refused."""
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ConfigurationError(
            "Idempotency-Key must be 8–200 printable ASCII characters without spaces "
            "(it is sent exactly as given, never trimmed). Use a new UUID per operation "
            "and reuse it only to retry that operation."
        )
    return value


def idempotency_key(value: Optional[str]) -> str:
    """The caller's key (checked) or, only for ``None``, a new random UUID v4."""
    if value is None:
        return new_idempotency_key()
    return checked_idempotency_key(value)


def required_idempotency_key(value: Any) -> str:
    """The key of a payment start or reversal: required, never generated here."""
    if value is None:
        raise ConfigurationError(
            "A stable idempotency_key is required to start or reverse a payment. Create it with "
            "PhysicalPosClient.new_idempotency_key(), store it with your order, then call. When the "
            "outcome is unknown, call again with the SAME key; a new key can charge twice."
        )
    return checked_idempotency_key(value)


def path_id(value: Any, name: str) -> str:
    """One path identifier, percent-encoded."""
    if (
        not isinstance(value, str)
        or value.strip() == ""
        or value != value.strip()
        or len(value) > 200
        or any(ord(c) < 33 or ord(c) == 127 for c in value)
        or value in (".", "..")
    ):
        raise ConfigurationError(f"{name} must be a non-empty identifier.")
    return encode_path_segment(value)


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def reject_card_data(value: Any, root: str) -> None:
    field = find_card_data_field(value, root)
    if field is not None:
        raise PhysicalPosCardDataRejectedError(
            "Physical POS requests must not contain card data; the card is read on the device. "
            f"Remove the field at {field}.",
            field=field,
        )


def _wire_keys(value: Any, allowed: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be a mapping.")
    out: Dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigurationError(f"{label} keys must be strings.")
        wire = key if key in allowed else camel(key)
        if wire not in allowed:
            raise ConfigurationError(
                f"Unknown {label} field: {key}. Allowed: {', '.join(allowed)}. "
                "The gateway rejects unknown fields with 400."
            )
        if wire in out:
            raise ConfigurationError(f"{label} field {wire} is given twice.")
        out[wire] = item
    return out


def _integer(value: Any, field: str, low: int = -SAFE_INTEGER, high: int = SAFE_INTEGER) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigurationError(
            f"{field} must be a JSON integer between {low} and {high} (not a string)."
        )
    return value


def _value(kind: Any, value: Any, field: str) -> Any:
    if isinstance(kind, dict):
        return shape(value, kind, field)
    if isinstance(kind, tuple) and kind[0] == "list":
        if not isinstance(value, (list, tuple)) or len(value) == 0:
            raise ConfigurationError(
                f"{field} must be a non-empty list; leave the field out instead of sending []."
            )
        return [shape(item, kind[1], f"{field}[{index}]") for index, item in enumerate(value)]
    if kind == "str":
        if not isinstance(value, str):
            raise ConfigurationError(f"{field} must be a string.")
        return value
    if kind in ("money", "money_zero"):
        return amount_minor(value, positive=kind == "money")
    if kind == "int":
        return _integer(value, field)
    if kind == "row_version":
        return _integer(value, field, 1, ROW_VERSION_MAX)
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigurationError(f"{field} must be a boolean.")
        return value
    if kind == "str_list":
        if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
            raise ConfigurationError(f"{field} must be a list of strings.")
        return list(value)
    raise AssertionError(kind)  # pragma: no cover - schema programming error


def shape(value: Any, schema: Schema, label: str) -> Dict[str, Any]:
    """Checks one request mapping against its schema; returns the wire body.

    Money is canonical string-only; present null/blank money is rejected.
    A field left out is not sent. Non-money ``None`` is sent as JSON null only for a
    nullable field (an explicit "clear"); for any other optional field it is
    dropped. An empty string is never sent: it is an error for a required
    field and dropped for an optional one.
    """
    given = _wire_keys(value, tuple(schema), label)
    body: Dict[str, Any] = {}
    for wire, (kind, required, nullable) in schema.items():
        field = wire if label in ("request",) else f"{label}.{wire}"
        if wire in given and kind in ("money", "money_zero"):
            body[wire] = _value(kind, given[wire], field)
            continue
        if kind == "str" and given.get(wire) == "":
            if required:
                raise ConfigurationError(f"{field} is required.")
            continue
        if wire not in given or given[wire] is None:
            if required:
                raise ConfigurationError(f"{field} is required.")
            if wire in given and nullable:
                body[wire] = None
            continue
        body[wire] = _value(kind, given[wire], field)
    return body


def body(value: Any, schema: Schema) -> Dict[str, Any]:
    """Card-data scan first (as the gateway guard), then the schema."""
    reject_card_data(value, "(body)")
    return shape(value, schema, "request")


def reject_pan_values(
    payload: Mapping[str, Any], strict: Iterable[str], item_text: Iterable[str] = ()
) -> None:
    """Refuses a card number written into a free-text value (field path only, never the value).

    ``strict`` / ``item_text`` name top-level fields, or ``items[].<field>``
    for every item line (``ITEM_TEXT`` keeps a 13/14 digit barcode).
    """
    checks = [(name, PAN_SCAN_STRICT) for name in strict] + [
        (name, PAN_SCAN_ITEM_TEXT) for name in item_text
    ]
    for name, mode in checks:
        if name.startswith("items[]."):
            field = name[len("items[].") :]
            for index, item in enumerate(payload.get("items") or []):
                value = item.get(field) if isinstance(item, Mapping) else None
                if isinstance(value, str) and contains_pan_like_value(value, mode):
                    _pan_rejected(f"items[{index}].{field}")
            continue
        value = payload.get(name)
        if isinstance(value, str) and contains_pan_like_value(value, mode):
            _pan_rejected(name)


def _pan_rejected(field: str) -> None:
    raise PhysicalPosCardDataRejectedError(
        "Physical POS requests must not contain card data; the card is read on the device. "
        f"The value of {field} looks like a card number.",
        field=field,
    )


def _iso_instant(value: Any, wire: str) -> str:
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConfigurationError(f"Filter {wire} must be a timezone-aware datetime.")
        moment = value.astimezone(_dt.timezone.utc)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    raise ConfigurationError(f"Filter {wire} must be an ISO-8601 string or an aware datetime.")


def _business_day(value: Any) -> str:
    """``YYYY-MM-DD`` of the date the caller gave (a datetime's own calendar day; not converted)."""
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    return value.isoformat()


def query(filters: Mapping[str, Any], route: str) -> Dict[str, Any]:
    """Checks list / report filters; snake_case or camelCase names accepted.

    ``None`` and ``""`` are dropped. ``date_from`` / ``date_to`` take a string
    or a :class:`datetime.date` (sent as that day, ``YYYY-MM-DD``; a datetime
    sends its own calendar day — it is NOT converted to Europe/Istanbul).
    ``created_from`` / ``created_to`` take a string or an aware datetime (sent
    as ISO-8601 UTC with ``Z``). ``merchant_reference`` and ``q`` are scanned
    for card numbers before sending.
    """
    reject_card_data(dict(filters), "(query)")
    allowed = PHYSICAL_POS_FILTERS[route]
    given = _wire_keys(filters, allowed, "filter")
    out: Dict[str, Any] = {}
    for wire, value in given.items():
        if wire in ("amountFromMinor", "amountToMinor"):
            out[wire] = amount_minor(value)
            continue
        if value is None or value == "":
            continue
        if wire in ("dateFrom", "dateTo") and isinstance(value, _dt.date):
            out[wire] = _business_day(value)
        elif wire in ("createdFrom", "createdTo") and isinstance(value, _dt.date):
            out[wire] = _iso_instant(value, wire)
        elif wire == "limit":
            out[wire] = _integer(value, "limit", 1, 100)
        elif wire == "includeTotal":
            if not isinstance(value, bool):
                raise ConfigurationError("include_total must be a boolean.")
            out[wire] = "true" if value else "false"
        elif wire in ("amountFromMinor", "amountToMinor"):
            out[wire] = amount_minor(value)
        else:
            if not isinstance(value, str):
                raise ConfigurationError(f"Filter {wire} must be a string.")
            out[wire] = value
    reject_pan_values(out, [wire for wire in PHYSICAL_POS_FREE_TEXT_FILTERS if wire in out])
    return out


def data(response: Any) -> Dict[str, Any]:
    validate_response_money(response)
    payload = data_of(response)
    if not isinstance(payload, Mapping):
        raise ApiError("The physical POS response carried no data object.")
    return dict(payload)


def member(response: Any, name: str) -> Dict[str, Any]:
    """``data[name]`` — the record a single-record route wraps."""
    value = data(response).get(name)
    if not isinstance(value, Mapping):
        raise ApiError(f"The physical POS response carried no {name}.")
    return dict(value)


def status_code(response: Any, fallback: int) -> int:
    value = response.get("statusCode") if isinstance(response, Mapping) else None
    if isinstance(value, int) and not isinstance(value, bool) and 200 <= value <= 299:
        return value
    return fallback


def translate(error: ApiError, key: Optional[str]) -> ApiError:
    """Typed physical POS error for a definite gateway answer; carries the key of a write."""
    common: Dict[str, Any] = {
        "status_code": error.status_code,
        "code": error.code,
        "response": error.response,
        "request_id": error.request_id,
        "details": error.details,
        "idempotency_key": key,
    }
    details = error.details or {}
    if error.code == PhysicalPosCardDataRejectedError.CODE:
        field = details.get("field")
        return PhysicalPosCardDataRejectedError(
            error.message, field=field if isinstance(field, str) else None, **common
        )
    if error.code == PhysicalPosVoidAfterSettlementError.CODE:
        allowed = details.get("allowedOperation")
        return PhysicalPosVoidAfterSettlementError(
            error.message, allowed_operation=allowed if isinstance(allowed, str) else None, **common
        )
    if error.status_code == 429:
        return PhysicalPosRateLimitError(
            error.message,
            retry_after=_retry_after(error),
            quota=getattr(error, "quota", None) if isinstance(error, RateLimitError) else None,
            **common,
        )
    error.idempotency_key = key
    return error


def _retry_after(error: Any) -> Optional[int]:
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        return retry_after
    details = getattr(error, "details", None) or {}
    seconds = details.get("retryAfterSeconds")
    return seconds if isinstance(seconds, int) and not isinstance(seconds, bool) else None


def call(send: Callable[[], T], key: Optional[str] = None) -> T:
    try:
        response = send()
        validate_response_money(response)
        return response
    except ApiError as error:
        translated = translate(error, key)
        if translated is error:
            raise
        raise translated from error


# ── Payment writes: one attempt loop that never loses an uncertain outcome ──

_AMBIGUOUS = "ambiguous"
_NOT_STARTED = "not_started"
_DEFINITE = "definite"


def _classify(error: ApiError) -> str:
    """No answer or a 5xx without a "not started" code: the payment may exist."""
    if error.status_code == 0:
        return _AMBIGUOUS
    if error.status_code >= 500:
        return _NOT_STARTED if error.code in PHYSICAL_POS_NOT_STARTED_CODES else _AMBIGUOUS
    return _DEFINITE


def _written_payment(response: Any) -> Optional[Dict[str, Any]]:
    """``data.payment`` of a 2xx answer, or ``None`` when it is missing or unusable."""
    if not isinstance(response, Mapping):
        return None
    try:
        validate_response_money(response)
    except (ConfigurationError, RecursionError):
        # Decoders can accept nesting deeper than Python validation can walk.
        # This response arrived after dispatch, so it cannot prove a payment outcome.
        return None
    payload = data_of(response)
    if not isinstance(payload, Mapping):
        return None
    payment = payload.get("payment")
    if not isinstance(payment, Mapping):
        return None
    payment_id = payment.get("paymentId")
    if not isinstance(payment_id, str) or payment_id == "":
        return None
    return dict(payment)


def payment_write(
    api: Any, path: str, payload: Dict[str, Any], key: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Sends a payment start / reversal / cancel; returns ``(envelope, payment)``.

    Runs its own attempts (the transport's retries are off for the call) with
    the same key and body on every attempt, so the history is never lost:

    * an answer with a valid ``data.payment`` is the only success;
    * no answer, an unreadable or payment-less 2xx, and a 5xx without a
      "not started" code are AMBIGUOUS — retried with the same key;
    * a 5xx with a "not started" code (nothing was written) is retried too;
    * a 4xx (429 included) stops the loop.

    When any attempt was ambiguous the call ends with
    :class:`~lunixi.errors.PhysicalPosOutcomeUnknownError`, whatever the last
    answer was: the payment may exist under this key.
    """
    attempts = 1 + api.max_retries
    ambiguous = False
    last: BaseException = ApiError("The physical POS payment request was not sent.")
    last_http: Optional[ApiError] = None
    for attempt in range(1, attempts + 1):
        try:
            response = api.request(
                "POST", path, payload, step_up=True, idempotency_key=key, max_retries=0
            )
        except ApiError as error:
            last = error
            if error.status_code != 0:
                last_http = error
            kind = _classify(error)
        except LunixiError as error:
            if not ambiguous:
                raise  # a local refusal before the first uncertain attempt
            last = error
            break  # preserve the uncertainty of an earlier request
        except Exception as error:  # noqa: BLE001 - unreadable body (RecursionError), foreign transport
            last = error
            kind = _AMBIGUOUS
        else:
            payment = _written_payment(response)
            if payment is not None:
                return response, payment
            last = ApiError("The physical POS answer carried no usable payment.")
            kind = _AMBIGUOUS
        if kind == _AMBIGUOUS:
            ambiguous = True
        if kind == _DEFINITE or attempt == attempts:
            break
        _backoff(attempt)

    if ambiguous:
        source = last_http
        raise PhysicalPosOutcomeUnknownError(
            "The payment outcome is unknown: an attempt got no definite answer. Retry the same "
            "operation with the same idempotency_key, or find the payment with "
            "list_payments(merchant_reference=...). Never retry with a new key.",
            retry_after=_retry_after(last) if isinstance(last, ApiError) else None,
            status_code=source.status_code if source is not None else 0,
            code=source.code if source is not None else None,
            request_id=source.request_id if source is not None else None,
            details=source.details if source is not None else None,
            idempotency_key=key,
        ) from last
    if not isinstance(last, ApiError):
        raise RuntimeError("A definite physical POS outcome must carry an API error.") from last
    translated = translate(last, key)
    if translated is last:
        raise last
    raise translated from last
