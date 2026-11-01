"""Strict declared physical POS monetary fields; counters and metadata stay untouched."""
from typing import Any, Mapping
from ..validation import amount_minor

_FIELDS = frozenset(['amountFromMinor', 'amountMinor', 'amountToMinor', 'approvedAmountMinor', 'baseMinor', 'capturedMinor', 'lineTotalMinor', 'netBaseMinor', 'netMinor', 'netTaxMinor', 'refundBaseMinor', 'refundMinor', 'refundTaxMinor', 'refundedAmountMinor', 'refundedMinor', 'reservedAmountMinor', 'reservedMinor', 'reversalReservedMinor', 'reversedMinor', 'saleBaseMinor', 'saleMinor', 'saleTaxMinor', 'unitAmountMinor', 'unitPriceMinor', 'voidBaseMinor', 'voidMinor', 'voidTaxMinor'])
_CONTAINERS = frozenset(['data', 'payment', 'payments', 'items', 'refundItems', 'taxes', 'rows', 'transaction', 'transactions', 'root', 'children', 'itemSummary', 'amountTotals', 'reported', 'system', 'difference', 'totals', 'lines'])
_NULLABLE = frozenset(['approvedAmountMinor', 'unitAmountMinor'])


def validate_response_money(value: Any, difference: bool = False) -> None:
    if isinstance(value, (list, tuple)):
        for entry in value:
            validate_response_money(entry, difference)
    elif isinstance(value, Mapping):
        for key, entry in value.items():
            if key in _FIELDS:
                if entry is None and key in _NULLABLE:
                    continue
                amount_minor(entry, positive=False, signed=difference or key.startswith("net"))
            elif key in _CONTAINERS:
                validate_response_money(entry, difference or key == "difference")
