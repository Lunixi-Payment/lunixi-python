"""The client-side card data key rule mirrors the gateway's token rule.

Contract source: nest-payment-gateway libs/proto/src/physical-pos-card-data.ts
(isPhysicalPosCardDataKey) and apps/api-gateway/src/physical-pos/payments/
physical-pos-card-data.guard.ts (findCardDataFieldPath).
"""

from __future__ import annotations

import pytest

from lunixi.physical_pos import (
    PAYMENT_FIELDS,
    PAYMENT_TARGET_FIELDS,
    PHYSICAL_POS_FILTERS,
    REFUND_ITEM_FIELDS,
    REVERSAL_FIELDS,
    SALE_ITEM_FIELDS,
    find_card_data_field,
    is_card_data_key,
)


@pytest.mark.parametrize(
    "key",
    [
        "pan",
        "PAN",
        "cardNumber",
        "card_number",
        "card-no",
        "primaryAccountNumber",
        "cvv",
        "CVV2",
        "CVVCode",
        "cardSecurityCode",
        "securityCode",
        "track2Data",
        "trackII",
        "track",
        "expiry",
        "expiration",
        "expMonth",
        "expiryDate",
        "pin",
        "pinBlock",
        "cardholderPin",
        "customercardnumber",
        "vendortrack2",
        "cid",
        "csc",
    ],
)
def test_card_data_keys(key):
    assert is_card_data_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "panel",
        "company",
        "span",
        "japan",
        "expiresAt",
        "expectedAmount",
        "trackingNo",
        "trackUrl",
        "tokenExpiry",
        "pinKeyKcv",
        "maskedPan",
        "cardNumberMasked",
        "cardMasked",
        "merchantReference",
    ],
)
def test_not_card_data_keys(key):
    assert is_card_data_key(key) is False


def test_no_sdk_wire_field_is_card_data():
    names = set(
        PAYMENT_FIELDS
        + PAYMENT_TARGET_FIELDS
        + SALE_ITEM_FIELDS
        + REVERSAL_FIELDS
        + REFUND_ITEM_FIELDS
    )
    for fields in PHYSICAL_POS_FILTERS.values():
        names.update(fields)
    assert [name for name in sorted(names) if is_card_data_key(name)] == []


def test_paths_follow_the_gateway_format():
    assert find_card_data_field({"a": 1}) is None
    assert find_card_data_field({"cvv": "x"}) == "cvv"
    assert find_card_data_field({"items": [{"name": "x"}, {"pan": "x"}]}) == "items[1].pan"
    assert find_card_data_field({"target": {"4543 6000 0000 1234": 1}}) == "target"
    assert find_card_data_field({"4543-6000-0000-1234": 1}, "(query)") == "(query)"
    assert find_card_data_field({"weird key": {"cvv": 1}}) == "[?].cvv"
