"""Validation and field mapping for the decision request.

Two jobs:

1. **Naming.** This SDK speaks ``snake_case``, as Python does; the wire is
   ``camelCase``. The mapping is a single explicit table, so a renamed wire
   field is a one-line change and the Python name a caller writes never has to
   change with it. A caller copying a field name straight out of the API
   reference still works: the camelCase spelling is accepted as an alias.

2. **Failing locally.** The gateway rejects a request carrying any field
   outside its own list, so an unknown field is a 400 from the server with no
   hint about which key was wrong. Checking the key set here turns that into a local error that names
   the offending key — the difference between a readable error and a round
   trip spent guessing.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from ..errors import ConfigurationError
from .taxonomy import (
    AUTH_MODE_VALUES,
    CHANNEL_VALUES,
    INTEGRATION_MODE_STANDALONE,
    OPERATION_KIND_VALUES,
    PRODUCT_CONTEXT_VALUES,
    STAGE_VALUES,
    SUB_MERCHANT_REF_PATTERN,
    SUBJECT_ID_MAX_LENGTH,
    SURFACE_VALUES,
    TRANSACTION_REF_MAX_LENGTH,
)

__all__ = ["to_evaluate_body", "FIELD_MAP", "ALLOWED_FIELDS"]

#: Python field name → wire field name, in the order the API reference lists
#: them.
#:
#: Deliberately ABSENT:
#:
#: * ``tenant_id`` — stamped from the access token. The gateway accepts the key
#:   for backwards compatibility but IGNORES its value, so publishing it here
#:   would imply a caller can choose their own tenant. They cannot.
#: * engine-internal fields (pre-resolved rule groups and the like) — not part
#:   of the customer surface, and a value sent there is not a request, it is a
#:   guess at the engine's internals.
FIELD_MAP: Dict[str, str] = {
    "integration_mode": "integrationMode",
    "product_context": "productContext",
    "transaction_ref": "transactionRef",
    "channel": "channel",
    "surface": "surface",
    "stage": "stage",
    "operation_kind": "operationKind",
    "auth_mode_requested": "authModeRequested",
    "auth_mode_applied": "authModeApplied",
    "sub_merchant_ref": "subMerchantRef",
    "subject_type": "subjectType",
    "subject_id": "subjectId",
    "payment_rail": "paymentRail",
    "transfer_direction": "transferDirection",
    "merchant_group_ids": "merchantGroupIds",
    "payment_id": "paymentId",
    "payment": "payment",
    "bank_transfer": "bankTransfer",
    "crypto_transfer": "cryptoTransfer",
    "wallet_operation": "walletOperation",
    "bill_payment": "billPayment",
    "loan_application": "loanApplication",
    "payout": "payout",
    "customer": "customer",
    "device": "device",
    "session": "session",
    "merchant": "merchant",
    "mobile_app": "mobileApp",
    "telemetry": "telemetry",
    "metadata": "metadata",
    "identity_snapshot": "identitySnapshot",
    "identity_assertion": "identityAssertion",
}

#: Python field names, for an error message that lists what is accepted.
ALLOWED_FIELDS: Tuple[str, ...] = tuple(FIELD_MAP)

#: camelCase → Python name, so a wire spelling is accepted as an alias.
_WIRE_ALIASES: Dict[str, str] = {
    wire: python for python, wire in FIELD_MAP.items() if wire != python
}

#: Closed dictionaries checked locally. A value outside one is a guaranteed
#: 400, so it is cheaper and clearer to say so before sending.
_ENUM_FIELDS: Dict[str, Tuple[str, ...]] = {
    "channel": CHANNEL_VALUES,
    "surface": SURFACE_VALUES,
    "stage": STAGE_VALUES,
    "operation_kind": OPERATION_KIND_VALUES,
    "auth_mode_requested": AUTH_MODE_VALUES,
    "auth_mode_applied": AUTH_MODE_VALUES,
    "product_context": PRODUCT_CONTEXT_VALUES,
    "integration_mode": (INTEGRATION_MODE_STANDALONE,),
}

_CONTROL_CHARACTERS = frozenset(chr(code) for code in list(range(0x20)) + [0x7F])


def to_evaluate_body(request: Mapping[str, Any]) -> Dict[str, Any]:
    """Validates a decision request and returns the body to send.

    Args:
        request: Fields keyed by Python name (camelCase accepted as an alias).
            ``None`` values are dropped — absent and null mean the same thing
            to the engine, and sending an explicit null just makes the request
            larger.

    Returns:
        A plain dict keyed by wire field name.

    Raises:
        ConfigurationError: for an unknown field, a value outside a closed
            dictionary, or a bounded string that is too long or carries
            control characters.
    """
    if not isinstance(request, Mapping):
        raise ConfigurationError("A fraud decision request must be a mapping.")

    normalized: Dict[str, Any] = {}
    unknown = []
    for key, value in request.items():
        python_name = key if key in FIELD_MAP else _WIRE_ALIASES.get(key)
        if python_name is None:
            unknown.append(str(key))
            continue
        normalized[python_name] = value

    if unknown:
        raise ConfigurationError(
            "Unknown fraud request field(s): {}. The gateway rejects unknown "
            "fields with 400. Accepted fields: {}.".format(
                ", ".join(sorted(unknown)), ", ".join(ALLOWED_FIELDS)
            )
        )

    for field, allowed in _ENUM_FIELDS.items():
        _assert_in_dictionary(normalized.get(field), field, allowed)

    _assert_bounded_string(
        normalized.get("transaction_ref"), "transaction_ref", TRANSACTION_REF_MAX_LENGTH
    )
    _assert_bounded_string(normalized.get("subject_id"), "subject_id", SUBJECT_ID_MAX_LENGTH)
    _assert_sub_merchant_ref(normalized.get("sub_merchant_ref"))

    body: Dict[str, Any] = {}
    for python_name, wire_name in FIELD_MAP.items():
        value = normalized.get(python_name)
        if value is not None:
            body[wire_name] = value
    return body


def _assert_in_dictionary(value: Any, field: str, allowed: Tuple[str, ...]) -> None:
    if value is None:
        return
    if value not in allowed:
        raise ConfigurationError(
            "Fraud request field '{}' must be one of: {}. Received {!r}.".format(
                field, ", ".join(allowed), value
            )
        )


def _assert_bounded_string(value: Any, field: str, max_length: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"Fraud request field '{field}' must be a non-empty string.")
    if len(value) > max_length:
        raise ConfigurationError(
            f"Fraud request field '{field}' may hold at most {max_length} characters "
            f"(received {len(value)})."
        )
    if any(character in _CONTROL_CHARACTERS for character in value):
        raise ConfigurationError(
            f"Fraud request field '{field}' must not contain control characters."
        )


def _assert_sub_merchant_ref(value: Optional[Any]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not SUB_MERCHANT_REF_PATTERN.match(value):
        raise ConfigurationError(
            "Fraud request field 'sub_merchant_ref' must hold letters, digits and "
            ". _ : @ - only (1-180 characters)."
        )
