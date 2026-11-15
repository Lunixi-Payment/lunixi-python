"""Payment links: bodies, signing, keys, lists, QR and the three-step image upload."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi import (
    BinaryResponse,
    BuyerFieldRequirement,
    CreatePaymentLinkRequest,
    CustomFieldType,
    PaymentLinkCustomField,
    PaymentLinkDeliveryChannel,
    PaymentLinkImageContentType,
    PaymentLinkItem,
    PaymentLinkUsage,
)
from lunixi.auth.canonical_request import build_canonical_request
from lunixi.auth.ed25519_signer import verify_signature
from lunixi.errors import ApiError, ConfigurationError
from lunixi.http.transport import HttpResponse
from lunixi.payment_links import (
    PAYMENT_LINK_IMMUTABLE_FIELDS,
    PAYMENT_LINK_SPEC_FIELDS,
    PaymentLinkAmountMode,
    PaymentLinkState,
)

from .support.recording_transport import envelope, json_response

LINK = "pl_0123456789"
KEY = "link-create-0001"
ASSET = "5b0e4c1a-2f3d-4e5f-8a9b-0c1d2e3f4a5b"
UPLOAD_URL = "https://storage.test.invalid/bucket/plink/5b0e?X-Amz-Signature=abc&X-Amz-Expires=900"
CREDENTIAL_HEADERS = ("Authorization", "X-Key-Id", "X-Date", "X-Nonce", "X-Signature", "Digest")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
STORAGE_DENIED = b"<Error><Code>AccessDenied</Code></Error>"


def assert_signed(request, public_key):
    for header in ("X-Key-Id", "X-Date", "X-Nonce", "X-Signature"):
        assert request.header(header), header
    canonical = build_canonical_request(
        request.method,
        request.path,
        request.header("X-Date"),
        request.header("X-Nonce"),
        request.header("Digest"),
    )
    assert verify_signature(public_key, request.header("X-Signature"), canonical) is True


def query_of(request):
    return parse_qs(urlsplit(request.url).query)


def link(**fields):
    data = {"id": LINK, "state": "ACTIVE", "rowVersion": 3, "amountMinor": "150000"}
    data.update(fields)
    return json_response(envelope(data))


def page(items, **page_info):
    return json_response(envelope({"items": items}, pageInfo=page_info))


def upload_target(**overrides):
    target = {
        "assetId": ASSET,
        "uploadUrl": UPLOAD_URL,
        "uploadMethod": "PUT",
        "uploadHeaders": {"Content-Type": "image/png"},
        "expiresAt": "2026-11-15T10:15:00.000Z",
    }
    target.update(overrides)
    return json_response(envelope(target), 201)


def upload_png(client):
    return client.payment_links().upload_image(
        file_name="a.png", content_type="image/png", content=PNG
    )


def published():
    image = {"assetId": ASSET, "url": f"https://img.test.invalid/{ASSET}", "state": "PUBLISHED"}
    return json_response(envelope(image))


# ── constants ────────────────────────────────────────────────────────────────


def test_field_lists_and_values():
    assert PAYMENT_LINK_SPEC_FIELDS[:4] == ("usage", "amountMode", "currency", "amountMinor")
    assert PAYMENT_LINK_SPEC_FIELDS[-1] == "metadata"
    assert len(PAYMENT_LINK_SPEC_FIELDS) == 39
    assert PAYMENT_LINK_IMMUTABLE_FIELDS == ("usage", "amountMode", "currency")
    assert PaymentLinkAmountMode.ALL == ("FIXED", "OPEN", "ITEMIZED")
    assert PaymentLinkState.TAKEN_DOWN == "TAKEN_DOWN"
    assert PaymentLinkImageContentType.ALL == ("image/png", "image/jpeg", "image/webp")


# ── builders ─────────────────────────────────────────────────────────────────


def test_fixed_link_body_keeps_the_key_order():
    body = (
        CreatePaymentLinkRequest.fixed(PaymentLinkUsage.SINGLE_USE, "150000", "try", "Invoice 42")
        .with_recipient({"name": "Test Buyer", "email": "buyer@example.com"})
        .with_expires_at(datetime(2026, 12, 31, 21, 0, tzinfo=timezone(timedelta(hours=3))))
        .with_checkout(require_three_ds=True, enabled_installments=[3, 1])
        .with_metadata({"invoice": "42"})
        .to_dict()
    )
    assert list(body) == [
        "usage",
        "amountMode",
        "currency",
        "title",
        "amountMinor",
        "recipient",
        "expiresAt",
        "checkout",
        "metadata",
    ]
    assert body["currency"] == "TRY"
    assert body["expiresAt"] == "2026-12-31T18:00:00.000Z"
    assert body["checkout"] == {
        "requireThreeDs": True,
        "paymentMethods": [],
        "enabledInstallments": [1, 3],
    }


def test_open_and_itemized_links():
    open_body = CreatePaymentLinkRequest.open(
        PaymentLinkUsage.MULTI_USE,
        "TRY",
        "Donation",
        min_amount_minor="1000",
        suggested_amounts_minor=["5000", "10000"],
    ).to_dict()
    assert open_body["amountMode"] == "OPEN"
    assert open_body["minAmountMinor"] == "1000"
    assert open_body["suggestedAmountsMinor"] == ["5000", "10000"]

    item = (
        PaymentLinkItem("Ticket", "25000")
        .with_item_key("it_ticket")
        .with_quantity_range(0, 4)
        .with_capacity(None)
    )
    question = PaymentLinkCustomField("seat", "Seat", CustomFieldType.SELECT).with_options(["A"])
    itemized = (
        CreatePaymentLinkRequest.itemized(PaymentLinkUsage.MULTI_USE, "TRY", "Concert", [item])
        .add_custom_field(question)
        .with_buyer_fields({"email": BuyerFieldRequirement.REQUIRED})
        .to_dict()
    )
    assert itemized["items"] == [
        {
            "name": "Ticket",
            "unitPriceMinor": "25000",
            "itemKey": "it_ticket",
            "minQuantity": 0,
            "maxQuantity": 4,
            "capacity": None,
        }
    ]
    assert itemized["customFields"] == [
        {"key": "seat", "label": "Seat", "fieldType": "SELECT", "options": ["A"]}
    ]


@pytest.mark.parametrize(
    "build",
    [
        lambda: CreatePaymentLinkRequest("ONCE", "FIXED", "TRY", "t"),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FREE", "TRY", "t"),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", ""),
        lambda: CreatePaymentLinkRequest.fixed("SINGLE_USE", 150000, "TRY", "t"),
        lambda: CreatePaymentLinkRequest.fixed("SINGLE_USE", "15.00", "TRY", "t"),
        lambda: CreatePaymentLinkRequest.itemized("MULTI_USE", "TRY", "t", []),
        lambda: PaymentLinkItem("Ticket", "-1"),
        lambda: PaymentLinkItem("Ticket", "1").with_quantity_range(True, 2),
        lambda: PaymentLinkItem("Ticket", "1").with_image_asset_id("not-a-uuid"),
        lambda: PaymentLinkCustomField("k", "l", "FILE"),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_locale("de"),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_buyer_fields(
            {"age": "REQUIRED"}
        ),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_buyer_fields(
            {"email": "MUST"}
        ),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_recipient(
            {"name": "x", "iban": "TR00"}
        ),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_metadata({"a": 1}),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_checkout(
            enabled_installments=[2, 3]
        ),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_expires_at(
            datetime(2026, 12, 31)
        ),
        lambda: CreatePaymentLinkRequest("SINGLE_USE", "FIXED", "TRY", "t").with_verification(
            True, "PIGEON"
        ),
    ],
)
def test_broken_builder_input_is_refused(build):
    with pytest.raises(ConfigurationError):
        build()


# ── create / get / update / actions ──────────────────────────────────────────


def fixed_request():
    return CreatePaymentLinkRequest.fixed(PaymentLinkUsage.SINGLE_USE, "150000", "TRY", "Invoice")


def test_create_is_signed_with_the_key_and_unwraps_data(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(link(replayed=False))
    result = client.payment_links().create(fixed_request(), idempotency_key=KEY)
    assert result["id"] == LINK
    request = transport.last
    assert (request.method, request.path) == ("POST", "/api/v1/payments/links")
    assert request.body == (
        '{"usage":"SINGLE_USE","amountMode":"FIXED","currency":"TRY","title":"Invoice",'
        '"amountMinor":"150000"}'
    )
    assert request.header("Idempotency-Key") == KEY
    assert_signed(request, public_key)


@pytest.mark.parametrize("key", [None, "", "short", "has space 123", "k" * 201, "ключ-12345"])
def test_create_needs_a_valid_key(client_factory, key):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().create(fixed_request(), idempotency_key=key)
    assert transport.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"usage": "SINGLE_USE", "unknownField": 1},
        {"usage": "SINGLE_USE", "expectedRowVersion": 1},
        {"usage": "SINGLE_USE", "expiresAt": ""},
        ["usage"],
    ],
)
def test_a_broken_raw_create_body_is_refused(client_factory, body):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().create(body, idempotency_key=KEY)
    assert transport.requests == []


def test_a_raw_create_body_converts_items_and_times(client_factory):
    transport, client = client_factory(link())
    when = datetime(2027, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)
    client.payment_links().create(
        {
            "usage": "MULTI_USE",
            "amountMode": "ITEMIZED",
            "currency": "TRY",
            "title": "Shop",
            "items": [PaymentLinkItem("Mug", "9900")],
            "startsAt": when,
        },
        idempotency_key=KEY,
    )
    body = json.loads(transport.last.body)
    assert body["items"] == [{"name": "Mug", "unitPriceMinor": "9900"}]
    assert body["startsAt"] == "2027-01-02T03:04:05.678Z"


def test_get_is_signed(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(link())
    assert client.payment_links().get("pl/1")["id"] == LINK
    request = transport.last
    assert (request.method, request.path, request.body) == (
        "GET",
        "/api/v1/payments/links/pl%2F1",
        None,
    )
    assert_signed(request, public_key)


def test_update_sends_the_row_version_first(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(link(rowVersion=4))
    client.payment_links().update(LINK, 3, {"title": "New", "description": None})
    request = transport.last
    assert (request.method, request.path) == ("PATCH", f"/api/v1/payments/links/{LINK}")
    assert request.body == '{"expectedRowVersion":3,"title":"New","description":null}'
    assert request.header("Idempotency-Key") is None
    assert_signed(request, public_key)


@pytest.mark.parametrize(
    "args",
    [
        (LINK, 3, {"currency": "EUR"}),
        (LINK, 3, {"usage": "MULTI_USE"}),
        (LINK, 3, {"environment": "LIVE"}),
        (LINK, 3, {}),
        (LINK, -1, {"title": "x"}),
        (LINK, True, {"title": "x"}),
        (LINK, "3", {"title": "x"}),
        ("", 3, {"title": "x"}),
    ],
)
def test_a_broken_update_is_refused(client_factory, args):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().update(*args)
    assert transport.requests == []


@pytest.mark.parametrize("action", ["pause", "resume", "deactivate"])
def test_state_actions(client_factory, test_key_pair, action):
    _, public_key = test_key_pair
    transport, client = client_factory(link(), link())
    getattr(client.payment_links(), action)(LINK)
    bare = transport.last
    assert (bare.method, bare.path, bare.body) == (
        "POST",
        f"/api/v1/payments/links/{LINK}/{action}",
        "{}",
    )
    assert bare.header("Idempotency-Key") is None
    assert_signed(bare, public_key)
    client.payment_links().action(
        LINK, action, expected_row_version=3, reason="Stock", idempotency_key="action-key-1"
    )
    full = transport.last
    assert full.body == '{"expectedRowVersion":3,"reason":"Stock"}'
    assert full.header("Idempotency-Key") == "action-key-1"


@pytest.mark.parametrize(
    "call",
    [
        lambda links: links.action(LINK, "archive"),
        lambda links: links.pause(LINK, expected_row_version=-1),
        lambda links: links.resume(LINK, idempotency_key="short"),
        lambda links: links.deactivate(" "),
    ],
)
def test_broken_actions_send_nothing(client_factory, call):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        call(client.payment_links())
    assert transport.requests == []


# ── send / qr ────────────────────────────────────────────────────────────────


def test_send_is_signed_with_the_required_key(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        json_response(envelope({"delivery": {"state": "QUEUED"}, "replayed": False}))
    )
    result = client.payment_links().send(
        LINK,
        channel=PaymentLinkDeliveryChannel.EMAIL,
        recipient_email="buyer@example.com",
        locale="tr",
        idempotency_key="send-key-1",
    )
    assert result["delivery"]["state"] == "QUEUED"
    request = transport.last
    assert request.path == f"/api/v1/payments/links/{LINK}/send"
    assert request.body == '{"channel":"EMAIL","recipientEmail":"buyer@example.com","locale":"tr"}'
    assert request.header("Idempotency-Key") == "send-key-1"
    assert_signed(request, public_key)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channel": "EMAIL", "idempotency_key": None},
        {"channel": "FAX", "idempotency_key": "send-key-1"},
        {"channel": "SMS", "idempotency_key": "send-key-1", "locale": "de"},
    ],
)
def test_broken_send_is_refused(client_factory, kwargs):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().send(LINK, **kwargs)
    assert transport.requests == []


def test_qr_is_a_signed_binary_get(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(HttpResponse(200, {"Content-Type": "image/png"}, PNG))
    image = client.payment_links().qr(LINK, format="png", size=256)
    assert isinstance(image, BinaryResponse)
    assert image.content == PNG
    request = transport.last
    assert urlsplit(request.url).path == f"/api/v1/payments/links/{LINK}/qr"
    assert query_of(request) == {"format": ["png"], "size": ["256"]}
    assert request.header("Accept") == "image/png, application/json"
    assert_signed(request, public_key)


@pytest.mark.parametrize(
    "kwargs", [{"format": "gif"}, {"size": 127}, {"size": 2049}, {"size": True}]
)
def test_broken_qr_options_are_refused(client_factory, kwargs):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().qr(LINK, **kwargs)
    assert transport.requests == []


def test_a_json_success_is_not_taken_for_a_qr_image(client_factory):
    _, client = client_factory(json_response(envelope({})))
    with pytest.raises(ApiError, match="QR"):
        client.payment_links().qr(LINK)


# ── lists ────────────────────────────────────────────────────────────────────


def test_list_sends_filters_signed_and_reads_the_page(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(
        page([{"id": LINK}], hasMore=True, nextCursor="c2", totalCount=7)
    )
    result = client.payment_links().list(
        state=["ACTIVE", "PAUSED"], limit=20, includeTotal=True, tag=None
    )
    assert result.items == [{"id": LINK}]
    assert (result.has_more, result.next_cursor, result.total_count) == (True, "c2", 7)
    request = transport.last
    assert urlsplit(request.url).path == "/api/v1/payments/links"
    assert query_of(request) == {
        "state": ["ACTIVE,PAUSED"],
        "limit": ["20"],
        "includeTotal": ["true"],
    }
    assert_signed(request, public_key)


def test_iterate_follows_cursors(client_factory):
    transport, client = client_factory(
        page([{"id": "a"}], hasMore=True, nextCursor="c2"), page([{"id": "b"}], hasMore=False)
    )
    assert [row["id"] for row in client.payment_links().iterate(limit=1)] == ["a", "b"]
    assert query_of(transport.last) == {"limit": ["1"], "cursor": ["c2"]}


def test_attempt_and_payment_lists(client_factory, test_key_pair):
    _, public_key = test_key_pair
    transport, client = client_factory(page([]), page([]))
    client.payment_links().list_attempts(LINK, state=["FAILED"], cursor="c1")
    attempts = transport.last
    assert urlsplit(attempts.url).path == f"/api/v1/payments/links/{LINK}/attempts"
    assert query_of(attempts) == {"state": ["FAILED"], "cursor": ["c1"]}
    assert_signed(attempts, public_key)
    client.payment_links().list_payments(LINK, limit=5)
    payments = transport.last
    assert urlsplit(payments.url).path == f"/api/v1/payments/links/{LINK}/payments"
    assert_signed(payments, public_key)


@pytest.mark.parametrize(
    "call",
    [
        lambda links: links.list(status="ACTIVE"),
        lambda links: links.list_attempts(LINK, usage="SINGLE_USE"),
        lambda links: links.list_payments(LINK, state="OPEN"),
        lambda links: links.list(state=["ACTIVE", 1]),
    ],
)
def test_unknown_list_filters_are_refused(client_factory, call):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        call(client.payment_links())
    assert transport.requests == []


# ── image upload ─────────────────────────────────────────────────────────────


def test_upload_image_runs_three_steps_and_the_put_carries_no_credentials(
    client_factory, test_key_pair
):
    _, public_key = test_key_pair
    transport, client = client_factory(upload_target(), HttpResponse(200, {}, b""), published())
    image = client.payment_links().upload_image(
        file_name="cover.png", content_type=PaymentLinkImageContentType.PNG, content=PNG
    )
    assert image == {
        "assetId": ASSET,
        "url": f"https://img.test.invalid/{ASSET}",
        "state": "PUBLISHED",
    }
    _, create, put, confirm = transport.requests

    assert (create.method, create.path) == ("POST", "/api/v1/payments/links/images")
    assert json.loads(create.body) == {
        "fileName": "cover.png",
        "contentType": "image/png",
        "sizeBytes": len(PNG),
    }
    assert create.header("Idempotency-Key") is None
    assert_signed(create, public_key)

    assert put.method == "PUT"
    assert put.url == UPLOAD_URL
    assert put.body == PNG
    assert put.headers == {"Content-Type": "image/png"}
    for header in CREDENTIAL_HEADERS + ("Idempotency-Key", "User-Agent"):
        assert put.header(header) is None, header

    assert (confirm.method, confirm.path, confirm.body) == (
        "POST",
        f"/api/v1/payments/links/images/{ASSET}/confirm",
        "{}",
    )
    assert_signed(confirm, public_key)


@pytest.mark.parametrize(
    "target",
    [
        {"uploadMethod": "POST"},
        {"uploadUrl": "ftp://storage.test.invalid/x"},
        {"uploadUrl": "https://user:pw@storage.test.invalid/x"},
        {"uploadUrl": "not a url"},
        {"assetId": "asset-1"},
        {"uploadHeaders": {"Content-Type": "image/png\r\nAuthorization: Bearer x"}},
        {"uploadHeaders": {"Bad Header": "x"}},
        {"uploadHeaders": ["Content-Type"]},
    ],
)
def test_an_unusable_upload_target_stops_before_the_put(client_factory, target):
    transport, client = client_factory(upload_target(**target))
    with pytest.raises(ApiError, match="upload target"):
        upload_png(client)
    assert [request.method for request in transport.requests] == ["POST", "POST"]


def test_a_failed_put_raises_with_the_storage_status_and_code(client_factory):
    transport, client = client_factory(
        upload_target(),
        HttpResponse(403, {"content-type": "application/xml"}, STORAGE_DENIED),
    )
    with pytest.raises(ApiError) as caught:
        upload_png(client)
    assert (caught.value.status_code, caught.value.code) == (403, "AccessDenied")
    assert len(transport.requests) == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file_name": "a.svg", "content_type": "image/svg+xml", "content": b"<svg/>"},
        {"file_name": "", "content_type": "image/png", "content": PNG},
        {"file_name": "a.png", "content_type": "image/png", "content": b""},
        {"file_name": "a.png", "content_type": "image/png", "content": "text"},
    ],
)
def test_broken_upload_input_sends_nothing(client_factory, kwargs):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().upload_image(**kwargs)
    assert transport.requests == []


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_create_image_upload_needs_a_positive_size(client_factory, size):
    transport, client = client_factory()
    with pytest.raises(ConfigurationError):
        client.payment_links().create_image_upload(
            file_name="a.png", content_type="image/png", size_bytes=size
        )
    assert transport.requests == []


def test_confirm_needs_an_asset_id_and_a_published_answer(client_factory):
    draft = json_response(envelope({"assetId": ASSET, "state": "DRAFT"}))
    transport, client = client_factory(draft)
    with pytest.raises(ConfigurationError):
        client.payment_links().confirm_image_upload("../asset")
    assert transport.requests == []
    with pytest.raises(ApiError, match="published"):
        client.payment_links().confirm_image_upload(ASSET.upper())
    assert transport.last.path == f"/api/v1/payments/links/images/{ASSET.upper()}/confirm"
