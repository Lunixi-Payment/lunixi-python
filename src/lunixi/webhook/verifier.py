"""Inbound webhook verification — fail-closed.

The ``X-Lunixi-Signature`` header is a comma-separated list of
``scheme=value`` items. There is one signature scheme, v2; the list form exists
only for the secret-rotation grace window, during which the gateway sends two
items (``v2=<new>,v2=<old>``) so an endpoint keeps working while you swap
secrets.

v2 = hex HMAC-SHA256 over ``f"{event_id}.{timestamp}.{raw_body}"``, where:

* ``event_id`` is the ``X-Lunixi-Event-Id`` header,
* ``timestamp`` is the EXACT string of ``X-Lunixi-Signature-Timestamp``,
* ``raw_body`` is the exact raw request body bytes.

🔴 SIGN THE RAW BODY, NEVER A RE-SERIALIZED ONE. Parsing JSON and dumping it
again reorders keys, changes spacing and rewrites escapes; the HMAC then
differs and every webhook is rejected. Capture the raw body in your framework
BEFORE any JSON middleware touches it.

🔴 FAIL-CLOSED: any discrepancy raises
:class:`~lunixi.errors.WebhookVerificationError`. Never act on a payload that
did not verify.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ..errors import ConfigurationError, WebhookVerificationError

__all__ = ["WebhookVerifier", "WebhookEvent"]

HEADER_SIGNATURE = "X-Lunixi-Signature"
HEADER_TIMESTAMP = "X-Lunixi-Signature-Timestamp"
HEADER_EVENT_ID = "X-Lunixi-Event-Id"
HEADER_EVENT_TYPE = "X-Lunixi-Event-Type"

_SCHEME_V2 = "v2"
_DEFAULT_TOLERANCE_SECONDS = 300

# ISO-8601 with an optional fractional part and either `Z` or a ±hh:mm offset.
# `datetime.fromisoformat` on the supported Python versions does not accept the
# trailing `Z` the gateway sends, so the value is normalized before parsing.
_TRAILING_Z = re.compile(r"Z$", re.IGNORECASE)


class WebhookEvent:
    """A verified webhook.

    Attributes:
        id: Event id, from the envelope and falling back to the header.
        type: Event type, for example ``fraud.flow.async_completed``. See
            :class:`~lunixi.fraud.fraud_events.FraudEvents`.
        timestamp: The signature timestamp, as an aware UTC datetime.
        data: The envelope's ``data`` object.
        raw: The whole decoded envelope.
    """

    __slots__ = ("id", "type", "timestamp", "data", "raw", "raw_body_hash")

    def __init__(
        self,
        *,
        id: Optional[str],  # noqa: A002 - matches the envelope field name
        type: Optional[str],  # noqa: A002 - matches the envelope field name
        timestamp: Optional[datetime],
        data: Mapping[str, Any],
        raw: Mapping[str, Any],
        raw_body_hash: Optional[str] = None,
    ) -> None:
        self.id = id
        self.type = type
        self.timestamp = timestamp
        self.data = data
        self.raw = raw
        self.raw_body_hash = raw_body_hash

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return f"WebhookEvent(id={self.id!r}, type={self.type!r})"


class WebhookVerifier:
    """Verifies inbound webhooks against your endpoint secret.

    Args:
        secret: The signing secret for this endpoint, from the console.
        tolerance_seconds: Replay window in seconds, 300 by default. Pass
            ``None`` to skip the freshness check — only do that when you
            replay captured webhooks in a test, never on a live endpoint,
            since an attacker may re-send a captured request forever.
    """

    def __init__(
        self,
        secret: "str | list[str]",
        *,
        tolerance_seconds: Optional[int] = _DEFAULT_TOLERANCE_SECONDS,
        allow_legacy_header_fields: bool = False,
    ) -> None:
        secrets = secret if isinstance(secret, list) else [secret]
        if not 1 <= len(secrets) <= 5 or any(
            not isinstance(v, str) or not v.strip() or len(v) > 1024 for v in secrets
        ):
            raise ConfigurationError(
                "A webhook secret is required; provide at most five rotating secrets."
            )
        if tolerance_seconds is not None and (
            isinstance(tolerance_seconds, bool)
            or not isinstance(tolerance_seconds, int)
            or not 1 <= tolerance_seconds <= 3600
        ):
            raise ConfigurationError(
                "Webhook tolerance must be 1–3600 seconds or explicit offline None."
            )
        self._secrets = tuple(secrets)
        self._tolerance_seconds = tolerance_seconds
        self._allow_legacy_header_fields = allow_legacy_header_fields

    def verify(self, raw_body: "str | bytes", headers: Mapping[str, Any]) -> WebhookEvent:
        """Verifies one webhook and returns it.

        Args:
            raw_body: The exact raw request body.
            headers: The request headers; matched case-insensitively.

        Raises:
            WebhookVerificationError: when a header is missing, the timestamp
                is outside the tolerance window, the header carries no v2
                item, no v2 item matches, or the body is not JSON.
        """
        body = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8")
        if len(body) > 1024 * 1024:
            raise WebhookVerificationError("Webhook body exceeds the 1 MiB limit.")
        timestamp = _header(headers, HEADER_TIMESTAMP)
        signature = _header(headers, HEADER_SIGNATURE)
        event_id = _header(headers, HEADER_EVENT_ID)
        event_type = _header(headers, HEADER_EVENT_TYPE)

        if not timestamp or not signature or not event_id:
            raise WebhookVerificationError(
                "The webhook signature, timestamp or event id header is missing."
            )

        parsed_timestamp = _parse_timestamp(timestamp)
        if parsed_timestamp is None:
            raise WebhookVerificationError("The webhook timestamp is not a valid date.")
        if self._tolerance_seconds is not None:
            age = abs((datetime.now(timezone.utc) - parsed_timestamp).total_seconds())
            if age > self._tolerance_seconds:
                raise WebhookVerificationError(
                    "The webhook timestamp is outside the tolerance window."
                )

        candidates = [
            value for scheme, value in _parse_signature_header(signature) if scheme == _SCHEME_V2
        ]
        if not candidates:
            raise WebhookVerificationError("The webhook signature carries no v2 item.")

        # HMAC over the EXACT raw body bytes — no parse, no re-serialization.
        matched = False
        for secret in self._secrets:
            expected = hmac.new(
                secret.encode("utf-8"),
                event_id.encode("utf-8") + b"." + timestamp.encode("utf-8") + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            for candidate in candidates:
                if re.fullmatch("[0-9a-fA-F]{64}", candidate):
                    matched = hmac.compare_digest(expected, candidate.lower()) or matched
        if not matched:
            raise WebhookVerificationError("Webhook signature verification failed.")

        try:
            envelope = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError) as error:
            raise WebhookVerificationError(
                "The webhook signature verified but the body is not valid JSON."
            ) from error
        if not isinstance(envelope, dict):
            raise WebhookVerificationError(
                "The webhook signature verified but the body is not a JSON object."
            )

        signed_id = _non_empty(envelope.get("id"))
        signed_type = _non_empty(envelope.get("type"))
        if (signed_id is not None and signed_id != event_id) or (
            signed_type is not None and event_type is not None and signed_type != event_type
        ):
            raise WebhookVerificationError(
                "Signed webhook identity does not match delivery headers."
            )
        strict = signed_id is not None and signed_type is not None
        if not strict and not self._allow_legacy_header_fields:
            raise WebhookVerificationError("Signed event id/type are required in the raw envelope.")
        data = envelope.get("data")
        if (
            (data is not None and not isinstance(data, dict))
            or len(event_id) > 200
            or len(signed_type or event_type or "") > 200
        ):
            raise WebhookVerificationError("Webhook data and identity are invalid.")
        return WebhookEvent(
            id=signed_id or event_id,
            type=signed_type or event_type,
            timestamp=parsed_timestamp,
            data=data if isinstance(data, dict) else {},
            raw=envelope,
            raw_body_hash=hashlib.sha256(body).hexdigest() if strict else None,
        )


def _parse_signature_header(value: str) -> List[Tuple[str, str]]:
    """Splits ``v2=abc,v2=def`` into ``[("v2", "abc"), ("v2", "def")]``.

    An unknown scheme is carried through and ignored by the caller, so a new
    scheme can be introduced without breaking an endpoint running this version.
    """
    items: List[Tuple[str, str]] = []
    for part in str(value).split(","):
        part = part.strip()
        if part == "":
            continue
        index = part.find("=")
        if index <= 0:
            items.append(("", part))
        else:
            items.append((part[:index].strip(), part[index + 1 :].strip()))
    return items


def _parse_timestamp(value: str) -> Optional[datetime]:
    normalized = _TRAILING_Z.sub("+00:00", value.strip())
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # No offset means UTC: the gateway always sends one, so a bare value
        # is an unusual sender rather than local time.
        return None
    return parsed


def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            if isinstance(value, (list, tuple)):
                return str(value[0]) if len(value) == 1 else None
            return str(value)
    return None


def _non_empty(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value != "" else None
