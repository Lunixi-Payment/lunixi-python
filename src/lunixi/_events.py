"""Reading the ``data`` of a verified webhook into a typed record.

The readers of the bank-connect and insurance events take the
:class:`~lunixi.webhook.verifier.WebhookEvent` that
:meth:`~lunixi.webhook.verifier.WebhookVerifier.verify` returned — never an
unverified body — and check its type before reading.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from .errors import ConfigurationError
from .webhook.verifier import WebhookEvent

__all__ = ["event_data", "text_field", "int_field"]


def event_data(event: Any, types: Tuple[str, ...], reader: str) -> Mapping[str, Any]:
    """The ``data`` of a verified event whose type is one of ``types``."""
    if not isinstance(event, WebhookEvent):
        raise ConfigurationError(
            f"{reader} reads a WebhookEvent returned by WebhookVerifier.verify()."
        )
    if event.type not in types:
        raise ConfigurationError(f"{reader} does not read {event.type!r} events.")
    data = event.data
    if not isinstance(data, Mapping):
        raise ConfigurationError(f"The {event.type} event carries no data object.")
    return data


def text_field(data: Mapping[str, Any], key: str) -> Optional[str]:
    """A string value, or ``None`` when absent, ``null`` or not a string."""
    value = data.get(key)
    return value if isinstance(value, str) else None


def int_field(data: Mapping[str, Any], key: str) -> Optional[int]:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None
