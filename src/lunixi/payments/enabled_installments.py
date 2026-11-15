"""The ``enabledInstallments`` rule shared by intents, installment options and payment links."""

from __future__ import annotations

from typing import Any

from ..errors import ConfigurationError

__all__ = [
    "ENABLED_INSTALLMENTS_MIN",
    "ENABLED_INSTALLMENTS_MAX",
    "validate_enabled_installments",
]

ENABLED_INSTALLMENTS_MIN = 1
ENABLED_INSTALLMENTS_MAX = 36


def validate_enabled_installments(
    counts: Any, field_name: str = "enabled_installments"
) -> list[int]:
    """Checks an installment-count list and returns it in ascending order.

    A non-empty list of distinct integers from 1 to 36 that contains 1. ``None``
    (leaving the field out) means no restriction, so an empty list is refused.
    A duplicate is an error; it is not removed.
    """
    if not isinstance(counts, (list, tuple)) or len(counts) == 0:
        raise ConfigurationError(
            f"{field_name} must be a non-empty list of installment counts; "
            "use None for no restriction or [1] for a single payment only."
        )
    seen: set[int] = set()
    for count in counts:
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not ENABLED_INSTALLMENTS_MIN <= count <= ENABLED_INSTALLMENTS_MAX
        ):
            raise ConfigurationError(
                f"{field_name} values must be integers from "
                f"{ENABLED_INSTALLMENTS_MIN} to {ENABLED_INSTALLMENTS_MAX}; got {count!r}."
            )
        if count in seen:
            raise ConfigurationError(f"{field_name} has {count} more than once.")
        seen.add(count)
    if ENABLED_INSTALLMENTS_MIN not in seen:
        raise ConfigurationError(f"{field_name} must contain 1 (single payment).")
    return sorted(seen)
