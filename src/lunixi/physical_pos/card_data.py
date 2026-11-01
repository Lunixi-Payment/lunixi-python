"""Card data key detection — the gateway's own token rule, applied before sending.

The physical POS API never takes card data: the card is read on the device. A
body or query key that looks like a card number, security code, track, PIN or
expiry is refused with ``400 physical_pos.payment.card_data_rejected`` by the
gateway; the SDK refuses it first, so the value never leaves the process.

The rule matches the gateway's ``isPhysicalPosCardDataKey``: the key is split
into tokens at camelCase, PascalCase, acronym, letter–digit and separator
boundaries (``CVVCode`` → cvv·code, ``track2Data`` → track·2·data) and compared
as joined token runs. Raw substrings are NOT searched, so ``panel``,
``expiresAt`` or ``trackingNo`` are not card data.

Free-text VALUES are scanned too (:func:`contains_pan_like_value`, the
gateway service's ``containsPanLikeValue``): a standalone 13–19 digit number,
plain or space / dash separated, that passes the Luhn check is a card number.
The value is never echoed in an error.
"""

from __future__ import annotations

import re
from typing import Any, FrozenSet, List, Mapping, Optional, Tuple

__all__ = ["is_card_data_key", "find_card_data_field", "contains_pan_like_value"]

_CARD_NUMBER_TERMS: Tuple[str, ...] = (
    "pan",
    "pannumber",
    "cardpan",
    "cardnumber",
    "cardno",
    "cardnum",
    "cardnr",
    "ccnumber",
    "ccnum",
    "primaryaccountnumber",
)
_CARD_SECRET_TERMS: Tuple[str, ...] = (
    "cvv",
    "cvv2",
    "cvc",
    "cvc2",
    "cvn",
    "cvn2",
    "cav2",
    "cvvcode",
    "cvccode",
    "cardcode",
    "securitycode",
    "cardverificationcode",
    "cardverificationvalue",
    "track1",
    "track2",
    "track3",
    "tracki",
    "trackii",
    "trackiii",
    "trackdata",
    "magstripe",
    "magneticstripe",
    "pinblock",
    "pincode",
    "pinnumber",
    "pindata",
    "cardpin",
    "cardholderpin",
    "encryptedpin",
    "expdate",
    "expmonth",
    "expyear",
    "expmmyy",
    "expirydate",
    "expirymonth",
    "expiryyear",
    "expirymmyy",
    "expirationdate",
    "expirationmonth",
    "expirationyear",
    "expiremonth",
    "expireyear",
    "cardexpiry",
    "cardexpiration",
)
_CARD_DATA_TERMS: FrozenSet[str] = frozenset(_CARD_NUMBER_TERMS + _CARD_SECRET_TERMS)
_SUFFIX_TERMS: Tuple[str, ...] = (
    "cardnumber",
    "pannumber",
    "primaryaccountnumber",
    "cvv",
    "cvv2",
    "cvc",
    "cvc2",
    "cvvcode",
    "securitycode",
    "track1",
    "track2",
    "trackdata",
    "pinblock",
    "expmonth",
    "expyear",
    "expirydate",
    "expirymonth",
    "expiryyear",
    "expirationdate",
    "cardexpiry",
)
_WHOLE_KEY_TERMS: FrozenSet[str] = frozenset(("track", "expiry", "expiration", "pin", "cid", "csc"))
_MASK_TOKENS: FrozenSet[str] = frozenset(("masked", "mask"))
_NUMBER_TERMS: FrozenSet[str] = frozenset(_CARD_NUMBER_TERMS)

#: A key holding a 13+ digit run (optionally space / dash separated) can only be a card number.
_DIGIT_RUN = re.compile(r"[0-9](?:[ -]?[0-9]){12,}")
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_MAX_NODES = 10_000


def _tokens(key: str) -> List[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", value)
    value = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", value)
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def is_card_data_key(key: str) -> bool:
    """True when a field NAME looks like card data. The value is never read."""
    if not isinstance(key, str):
        return False
    tokens = _tokens(key)
    if not tokens:
        return False
    if "".join(tokens) in _WHOLE_KEY_TERMS:
        return True
    masked = any(token in _MASK_TOKENS for token in tokens)
    for start in range(len(tokens)):
        joined = ""
        for end in range(start, len(tokens)):
            joined += tokens[end]
            if joined in _CARD_DATA_TERMS and not (masked and joined in _NUMBER_TERMS):
                return True
            for term in _SUFFIX_TERMS:
                if joined.endswith(term) and not (masked and term in _NUMBER_TERMS):
                    return True
    return False


def _child(path: str, key: str) -> str:
    if _IDENTIFIER.fullmatch(key):
        return key if path == "" else f"{path}.{key}"
    return f"{path}[?]"


def find_card_data_field(value: Any, root: str = "(body)") -> Optional[str]:
    """Path of the first card-data key in a body or query (``items[1].cvv``), else ``None``.

    Walks key NAMES only, in the gateway's order. A key that is itself a long
    digit run yields the path of the object holding it (never the key). A body
    too large to scan is treated as carrying card data (fail-closed).
    """
    stack: List[Tuple[Any, str]] = [(value, "")]
    visited = 0
    while stack:
        if visited >= _MAX_NODES:
            return root
        node, path = stack.pop()
        visited += 1
        if isinstance(node, (list, tuple)):
            for index in range(len(node) - 1, -1, -1):
                stack.append((node[index], f"{path}[{index}]"))
            continue
        if not isinstance(node, Mapping):
            continue
        keys = [str(key) for key in node.keys()]
        for key in keys:
            if _DIGIT_RUN.search(key):
                return root if path == "" else path
            if is_card_data_key(key):
                return _child(path, key)
        for key in reversed(list(node.keys())):
            stack.append((node[key], _child(path, str(key))))
    return None


# ── Card numbers in values (service ``containsPanLikeValue``) ────────────────

#: ``[^\W_]`` is Python's ``[\p{L}\p{N}]`` (a Unicode letter or number); digits
#: of the candidate itself are ASCII only. A dash glued to a letter / number on
#: either side joins the run into an identifier (``ORD-4111…``, UUIDs).
_PAN_CANDIDATE = re.compile(
    r"(?<![^\W_])(?<![^\W_]-)[0-9](?:[ -]?[0-9]){12,18}(?![^\W_])(?!-[^\W_])"
)
_GTIN = re.compile(r"(?:[0-9]{8}|[0-9]{12,14})")

#: Scan modes. ``ITEM_TEXT`` (item names only) treats an unseparated 13 or 14
#: digit number with a valid GTIN check digit as a barcode.
PAN_SCAN_STRICT = "STRICT"
PAN_SCAN_ITEM_TEXT = "ITEM_TEXT"


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = ord(char) - 48
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _gtin_valid(digits: str) -> bool:
    if not _GTIN.fullmatch(digits):
        return False
    total = 0
    weight = 3
    for char in reversed(digits[:-1]):
        total += (ord(char) - 48) * weight
        weight = 1 if weight == 3 else 3
    return (10 - total % 10) % 10 == ord(digits[-1]) - 48


def contains_pan_like_value(text: str, mode: str = PAN_SCAN_STRICT) -> bool:
    """True when ``text`` holds a standalone Luhn-valid 13–19 digit number."""
    if not isinstance(text, str):
        return False
    for match in _PAN_CANDIDATE.finditer(text):
        candidate = match.group(0)
        digits = candidate.replace(" ", "").replace("-", "")
        if not 13 <= len(digits) <= 19:
            continue
        if mode == PAN_SCAN_ITEM_TEXT and digits == candidate and len(digits) <= 14 and _gtin_valid(digits):
            continue
        if _luhn_valid(digits):
            return True
    return False
