"""Shared boundary validation; caller-controlled inputs cannot change an origin."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from .errors import ConfigurationError

SAFE_INTEGER = 9007199254740991
CURRENCIES = frozenset(
    (
        "TRY",
        "USD",
        "EUR",
        "GBP",
        "RUB",
        "AED",
        "SAR",
        "QAR",
        "KWD",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "CNY",
        "AZN",
    )
)


MAX_FIAT_MINOR = 9223372036854775807


def amount_minor(value: Any, *, positive: bool = True, signed: bool = False) -> str:
    pattern = r"0|-?[1-9][0-9]*" if signed else r"[1-9][0-9]*" if positive else r"0|[1-9][0-9]*"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ConfigurationError("Amount must be a canonical minor-unit string.")
    if not -MAX_FIAT_MINOR - 1 <= int(value) <= MAX_FIAT_MINOR:
        raise ConfigurationError("Amount exceeds the signed 64-bit fiat range.")
    return value


def decimal_to_minor(value: str, currency: str) -> str:
    """Convert exact decimal text with the actual supported currency exponent."""
    currency_code(currency)
    exponent = 0 if currency == "JPY" else 3 if currency == "KWD" else 2
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:[.][0-9]+)?", value):
        raise ConfigurationError("Exact nonnegative decimal text is required.")
    whole, _, fraction = value.partition(".")
    if any(c != "0" for c in fraction[exponent:]):
        raise ConfigurationError("Fractional minor units are not permitted.")
    return amount_minor(str(int(whole + fraction[:exponent].ljust(exponent, "0"))), positive=False)


def validate_money_fields(value: Any, *, response: bool = False) -> None:
    """Validate public money DTO fields without touching merchant metadata or rates."""
    if isinstance(value, list):
        for entry in value:
            validate_money_fields(entry, response=response)
    elif isinstance(value, dict):
        for key, entry in value.items():
            if key in ("metadata", "fields", "inputFields", "insuranceData") or entry is None:
                continue
            if key in (
                "amount",
                "amountMinor",
                "authorizedAmount",
                "availableBalance",
                "balanceMinor",
                "buyerTotalCharge",
                "cancelledPremiumAmount",
                "capturedAmount",
                "capturedAmountMinor",
                "chargeAmount",
                "collectedAmountMinor",
                "collectedPremiumAmount",
                "compensatedAmount",
                "disputedAmount",
                "feeTotal",
                "fixedFee",
                "inForcePremiumAmount",
                "insuranceValueAmount",
                "legAmount",
                "legsAmount",
                "lineTotalMinor",
                "maxAmount",
                "maxAmountMinor",
                "minAmount",
                "minAmountMinor",
                "nonRefundableAmount",
                "paidAmount",
                "paidPrice",
                "pendingBalance",
                "premiumAmount",
                "price",
                "refundAmount",
                "refundOpenPremiumAmount",
                "refundableAmount",
                "refundedAmount",
                "refundedAmountMinor",
                "refundedPremiumAmount",
                "requestedAmount",
                "reservedBalance",
                "sourceAmountMinor",
                "targetAmountMinor",
                "taxAmountMinor",
                "taxTotal",
                "totalAmount",
                "unitPriceMinor",
            ):
                amount_minor(
                    entry,
                    positive=not response and key in ("amount", "price", "totalAmount"),
                    signed="balance" in key.lower(),
                )
            elif key == "suggestedAmountsMinor":
                if not isinstance(entry, list):
                    raise ConfigurationError("suggestedAmountsMinor must be a list.")
                for amount in entry:
                    amount_minor(amount)
            elif key in (
                "data",
                "details",
                "items",
                "rows",
                "results",
                "payments",
                "operations",
                "balances",
                "wallets",
                "legs",
                "aggregate",
                "refund",
                "refunds",
                "totals",
                "charge",
                "fees",
                "fee",
                "balance",
                "splits",
                "sellers",
                "basketItems",
                "promissoryNote",
                "schedule",
                "notes",
                "lines",
                "offers",
                "policies",
                "reconciliation",
                "quotes",
                "payment",
                "transactions",
                "accounts",
                "settlements",
                "payouts",
                "limits",
            ):
                validate_money_fields(entry, response=response)


def currency_code(value: str) -> str:
    if not isinstance(value, str) or value not in CURRENCIES:
        raise ConfigurationError("A supported uppercase currency is required.")
    return value


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value):
        raise ConfigurationError("Invalid resource identifier.")
    return value


def header_value(value: str, field: str, max_length: int = 200) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > max_length
        or any(ord(c) < 32 or ord(c) > 126 for c in value)
    ):
        raise ConfigurationError(f"Invalid {field} header.")
    return value


def origin_url(value: str, allow_loopback_http: bool = False) -> str:
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise ConfigurationError("base_url must be a trusted HTTPS origin.")
    u = urlsplit(value)
    try:
        valid_port = u.port is None or 1 <= u.port <= 65535
    except ValueError:
        valid_port = False
    loopback = False
    try:
        loopback = ipaddress.ip_address(u.hostname or "").is_loopback
    except ValueError:
        pass
    if (
        not u.hostname
        or u.username is not None
        or u.password is not None
        or "?" in value
        or "#" in value
        or u.path not in ("", "/")
        or not valid_port
        or (u.scheme != "https" and not (allow_loopback_http and u.scheme == "http" and loopback))
    ):
        raise ConfigurationError(
            "base_url must be an HTTPS origin; HTTP requires explicit numeric-loopback test opt-in."
        )
    return value.rstrip("/")


def gateway_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/api/v1/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
    ):
        raise ConfigurationError("Path must remain under /api/v1/ on the configured origin.")
    u = urlsplit(value)
    if u.netloc or u.scheme or u.fragment:
        raise ConfigurationError("Invalid gateway path.")
    decoded = u.path
    for _ in range(8):
        current = unquote(decoded)
        if current == decoded:
            break
        decoded = current
    if (
        "%" in decoded
        or "\\" in decoded
        or any(p in (".", "..") for p in decoded.split("/"))
        or "//" in decoded
    ):
        raise ConfigurationError("Path normalization or traversal is not permitted.")
    return value
