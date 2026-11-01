"""Physical POS: card payments on in-store devices, their records and management.

* :class:`PhysicalPosClient` — payments (start, read, list, cancel, reverse),
  transactions, reports and end-of-day results.
* :class:`PhysicalPosManagementClient` — overview, catalog, stores, registers,
  logical terminals and devices.
* :func:`parse_webhook_event` — verifies (raw body, headers, secret) and reads a ``physical_pos.*`` webhook.
"""

from .card_data import contains_pan_like_value, find_card_data_field, is_card_data_key
from .client import PhysicalPosClient
from .management import PhysicalPosManagementClient
from .results import PhysicalPosPaymentWriteResult, PhysicalPosWriteResult
from .values import (
    IDEMPOTENCY_KEY_PATTERN,
    PAYMENT_FIELDS,
    PAYMENT_TARGET_FIELDS,
    PHYSICAL_POS_EVENT_PATTERN,
    PHYSICAL_POS_EVENT_TYPES,
    PHYSICAL_POS_FILTERS,
    PHYSICAL_POS_FREE_TEXT_FILTERS,
    PHYSICAL_POS_NOT_STARTED_CODES,
    REFUND_ITEM_FIELDS,
    REVERSAL_FIELDS,
    SALE_ITEM_FIELDS,
    PhysicalPosEvents,
    PhysicalPosPaymentOperation,
    PhysicalPosPaymentStatus,
    PhysicalPosReversalStatus,
)
from .webhook import PhysicalPosWebhookEvent, parse_webhook_event

__all__ = [
    "PhysicalPosClient",
    "PhysicalPosManagementClient",
    "PhysicalPosPaymentWriteResult",
    "PhysicalPosWriteResult",
    "PhysicalPosWebhookEvent",
    "parse_webhook_event",
    "is_card_data_key",
    "find_card_data_field",
    "contains_pan_like_value",
    "PhysicalPosEvents",
    "PHYSICAL_POS_EVENT_PATTERN",
    "PHYSICAL_POS_EVENT_TYPES",
    "PhysicalPosPaymentOperation",
    "PhysicalPosPaymentStatus",
    "PhysicalPosReversalStatus",
    "IDEMPOTENCY_KEY_PATTERN",
    "PAYMENT_FIELDS",
    "PAYMENT_TARGET_FIELDS",
    "SALE_ITEM_FIELDS",
    "REVERSAL_FIELDS",
    "REFUND_ITEM_FIELDS",
    "PHYSICAL_POS_FILTERS",
    "PHYSICAL_POS_FREE_TEXT_FILTERS",
    "PHYSICAL_POS_NOT_STARTED_CODES",
]
