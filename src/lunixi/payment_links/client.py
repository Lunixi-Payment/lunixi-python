"""Payment links — ``/api/v1/payments/links``.

Every gateway call here is signed per request (``step_up``), reads included: a
request with only the access token is 401 ``AUTH_HEADERS_MISSING``. The
merchant and the environment come from the signing key, so a TEST key sees and
changes only TEST links. The key needs the matching scope
(``payment-link:create``, ``:view``, ``:manage``, ``:send``); a missing scope is
403 ``API_INSUFFICIENT_SCOPE``.

The one request that does not go through the authenticated client is the image
PUT of :meth:`PaymentLinksClient.upload_image`: it goes to the storage host
behind a presigned URL, not to the gateway, and carries only the
``uploadHeaders`` the gateway returned — no access token, no signature.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from ..api_client import ApiClient, BinaryResponse
from ..configuration import Configuration
from ..errors import ApiError, ConfigurationError
from ..http.envelope import Page, data_of
from ..http.transport import TransportError, encode_path_segment
from .requests import CreatePaymentLinkRequest, iso_or_null, plain
from .values import (
    ASSET_ID_PATTERN,
    IDEMPOTENCY_KEY_PATTERN,
    PAYMENT_LINK_ACTIONS,
    PAYMENT_LINK_ATTEMPT_LIST_FILTERS,
    PAYMENT_LINK_IMMUTABLE_FIELDS,
    PAYMENT_LINK_LIST_FILTERS,
    PAYMENT_LINK_PAYMENT_LIST_FILTERS,
    PAYMENT_LINK_SPEC_FIELDS,
    QR_MAX_SIZE,
    QR_MIN_SIZE,
    PaymentLinkDeliveryChannel,
    PaymentLinkImageContentType,
    PaymentLinkLocale,
    PaymentLinkQrFormat,
)

__all__ = ["PaymentLinksClient"]

_BASE = "/api/v1/payments/links"
_IMAGES = _BASE + "/images"
_CREATE_FIELDS = ("environment", *PAYMENT_LINK_SPEC_FIELDS)
_TIME_FIELDS = ("startsAt", "expiresAt", "eventAt")
_NESTED_LISTS = ("items", "customFields")
_UPLOAD_SCHEMES = ("https", "http")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}")
_STORAGE_ERROR_CODE = re.compile(r"<Code>([A-Za-z0-9.]{1,64})</Code>")


class PaymentLinksClient:
    """Create, change, share and follow payment links.

    Single-object answers are the envelope's ``data``; list calls return a
    :class:`~lunixi.http.envelope.Page` (``items``, ``has_more``,
    ``next_cursor``, ``total_count``).
    """

    def __init__(self, api: ApiClient, config: Configuration) -> None:
        self._api = api
        self._config = config

    # ── links ────────────────────────────────────────────────────────────────

    def create(
        self,
        request: CreatePaymentLinkRequest | Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """Creates a payment link (``POST /payments/links``, scope ``payment-link:create``).

        ``idempotency_key`` is required (8–200 printable ASCII characters):
        the same key with the same body returns the stored link with
        ``replayed: True`` instead of creating a second one; the same key with
        a different body is 409 ``payment_link.idempotency.conflict``.
        """
        body = _create_body(request)
        return _unwrap(
            self._api.request(
                "POST",
                _BASE,
                body,
                step_up=True,
                idempotency_key=_required_key(idempotency_key, "payment link create"),
            )
        )

    def list(self, **filters: Any) -> Page:
        """One page of links, newest first.

        Filters: ``limit``, ``cursor``, ``includeTotal``, ``state``, ``usage``,
        ``amountMode`` (these three take a list, sent as a comma list),
        ``environment``, ``tag``, ``branchCode``, ``createdById``, ``query``
        (a short code exactly, or a title/reference prefix), ``createdFrom`` /
        ``createdTo`` (a half-open window ``[from, to)``).
        """
        query = _query(filters, PAYMENT_LINK_LIST_FILTERS, "list")
        return Page(self._api.request("GET", _BASE, query=query or None, step_up=True))

    def iterate(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Every link matching the filters, following cursors."""
        return _paginate(lambda page_filters: self.list(**page_filters), filters)

    def get(self, link_id: str) -> Dict[str, Any]:
        return _unwrap(self._api.request("GET", _link_path(link_id), step_up=True))

    def update(
        self,
        link_id: str,
        expected_row_version: int,
        changes: Mapping[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Changes a link and creates a new version of it (``PATCH /payments/links/{id}``).

        Only the keys in ``changes`` are updated; ``None`` clears a field and a
        nested object (``recipient``, ``checkout``, …) is replaced whole.
        ``expected_row_version`` is the link's current ``rowVersion``: a link
        changed in between is 409 ``payment_link.link.version_conflict``.
        ``usage``, ``amountMode`` and ``currency`` cannot change.
        """
        body = {"expectedRowVersion": _row_version(expected_row_version), **_update_body(changes)}
        return _unwrap(
            self._api.request(
                "PATCH",
                _link_path(link_id),
                body,
                step_up=True,
                idempotency_key=_optional_key(idempotency_key),
            )
        )

    def pause(
        self,
        link_id: str,
        *,
        expected_row_version: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stops accepting payments until :meth:`resume`."""
        return self.action(
            link_id,
            "pause",
            expected_row_version=expected_row_version,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def resume(
        self,
        link_id: str,
        *,
        expected_row_version: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.action(
            link_id,
            "resume",
            expected_row_version=expected_row_version,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def deactivate(
        self,
        link_id: str,
        *,
        expected_row_version: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Closes the link for good; it cannot be reopened."""
        return self.action(
            link_id,
            "deactivate",
            expected_row_version=expected_row_version,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def action(
        self,
        link_id: str,
        action: str,
        *,
        expected_row_version: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """``pause``, ``resume`` or ``deactivate`` (``POST /payments/links/{id}/{action}``).

        ``expected_row_version`` is optional here (omitted = no version check);
        send it to fail with 409 ``payment_link.link.version_conflict`` when the
        link changed in between.
        """
        if action not in PAYMENT_LINK_ACTIONS:
            raise ConfigurationError(
                f"Payment link action must be one of {', '.join(PAYMENT_LINK_ACTIONS)}."
            )
        body: Dict[str, Any] = {}
        if expected_row_version is not None:
            body["expectedRowVersion"] = _row_version(expected_row_version)
        if reason is not None:
            if not isinstance(reason, str):
                raise ConfigurationError("reason must be a string.")
            body["reason"] = reason
        return _unwrap(
            self._api.request(
                "POST",
                f"{_link_path(link_id)}/{action}",
                body,
                step_up=True,
                idempotency_key=_optional_key(idempotency_key),
            )
        )

    def send(
        self,
        link_id: str,
        *,
        channel: str,
        idempotency_key: str,
        recipient_email: Optional[str] = None,
        recipient_phone: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends the link by e-mail or SMS (``POST /payments/links/{id}/send``).

        Without ``recipient_email`` / ``recipient_phone`` the link's
        ``recipient`` is used. ``idempotency_key`` is required so a retried call
        cannot send twice. An accepted delivery can still fail: check
        ``delivery.state`` and ``delivery.failureReason``.
        """
        body: Dict[str, Any] = {
            "channel": _one_of(channel, PaymentLinkDeliveryChannel.ALL, "Send channel")
        }
        if recipient_email is not None:
            body["recipientEmail"] = _string(recipient_email, "recipient_email")
        if recipient_phone is not None:
            body["recipientPhone"] = _string(recipient_phone, "recipient_phone")
        if locale is not None:
            body["locale"] = _one_of(locale, PaymentLinkLocale.ALL, "Send locale")
        return _unwrap(
            self._api.request(
                "POST",
                f"{_link_path(link_id)}/send",
                body,
                step_up=True,
                idempotency_key=_required_key(idempotency_key, "payment link send"),
            )
        )

    def qr(
        self, link_id: str, *, format: str = PaymentLinkQrFormat.SVG, size: Optional[int] = None
    ) -> BinaryResponse:
        """The link's QR code as an image (``GET /payments/links/{id}/qr``).

        ``format`` is ``svg`` or ``png``; ``size`` in pixels, 128–2048 (the
        gateway default is 512). An error answer is still the JSON envelope and
        raises as usual.
        """
        image_format = _one_of(format, PaymentLinkQrFormat.ALL, "QR format")
        query: Dict[str, Any] = {"format": image_format}
        if size is not None:
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not QR_MIN_SIZE <= size <= QR_MAX_SIZE
            ):
                raise ConfigurationError(
                    f"QR size must be an integer in pixels, {QR_MIN_SIZE}-{QR_MAX_SIZE}."
                )
            query["size"] = size
        accept = "image/svg+xml" if image_format == PaymentLinkQrFormat.SVG else "image/png"
        image = self._api.request_binary(
            "GET",
            f"{_link_path(link_id)}/qr",
            query=query,
            step_up=True,
            accept=accept + ", application/json",
        )
        if not (image.content_type or "").lower().startswith("image/"):
            raise ApiError("The gateway did not return a QR image.")
        return image

    def list_attempts(self, link_id: str, **filters: Any) -> Page:
        """Payment attempts on the link, newest first (``state`` takes a list)."""
        query = _query(filters, PAYMENT_LINK_ATTEMPT_LIST_FILTERS, "attempt list")
        return Page(
            self._api.request(
                "GET", f"{_link_path(link_id)}/attempts", query=query or None, step_up=True
            )
        )

    def iterate_attempts(self, link_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return _paginate(lambda page_filters: self.list_attempts(link_id, **page_filters), filters)

    def list_payments(self, link_id: str, **filters: Any) -> Page:
        """Successful payments on the link, with refund totals."""
        query = _query(filters, PAYMENT_LINK_PAYMENT_LIST_FILTERS, "payment list")
        return Page(
            self._api.request(
                "GET", f"{_link_path(link_id)}/payments", query=query or None, step_up=True
            )
        )

    def iterate_payments(self, link_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return _paginate(lambda page_filters: self.list_payments(link_id, **page_filters), filters)

    # ── link image ───────────────────────────────────────────────────────────

    def create_image_upload(
        self, *, file_name: str, content_type: str, size_bytes: int
    ) -> Dict[str, Any]:
        """Link image, step 1 of 3: an upload target (``POST /payments/links/images``).

        Returns ``{"assetId", "uploadUrl", "uploadMethod": "PUT", "uploadHeaders",
        "expiresAt"}``. Step 2 is a PUT of the file's bytes to ``uploadUrl``
        with exactly ``uploadHeaders`` before ``expiresAt``; step 3 is
        :meth:`confirm_image_upload`. :meth:`upload_image` runs all three.
        ``uploadUrl`` is the storage host, not the gateway: send it no access
        token and no signature.

        ``content_type`` is PNG, JPEG or WebP (:class:`PaymentLinkImageContentType`;
        SVG is refused). A declared ``size_bytes`` over 2 MiB is refused by the
        gateway before anything is uploaded (400 ``media.public_asset.too_large``).
        """
        body = {
            "fileName": _text(file_name, "file_name"),
            "contentType": _one_of(
                content_type,
                PaymentLinkImageContentType.ALL,
                "Image content_type (SVG is not accepted)",
            ),
            "sizeBytes": _image_size(size_bytes),
        }
        target = _unwrap(self._api.request("POST", _IMAGES, body, step_up=True))
        return _upload_target(target)

    def confirm_image_upload(self, asset_id: str) -> Dict[str, Any]:
        """Link image, step 3 of 3: publishes the uploaded image.

        (``POST /payments/links/images/{assetId}/confirm``.) The stored bytes
        must be the declared type, at most 2 MiB and 4096×4096 px; a file that
        fails is deleted (400) and is uploaded again from
        :meth:`create_image_upload`. Confirming before the PUT has landed is 400
        ``media.confirm.object_missing`` and can be retried.

        Returns ``{"assetId", "url", "state": "PUBLISHED"}``; use ``assetId``
        as the ``imageAssetId`` of a link or an item. ``url`` is ``None`` when
        the public image host is not configured.
        """
        path = f"{_IMAGES}/{encode_path_segment(_asset_id(asset_id))}/confirm"
        image = _unwrap(self._api.request("POST", path, {}, step_up=True))
        if (
            not isinstance(image, dict)
            or not isinstance(image.get("assetId"), str)
            or image.get("state") != "PUBLISHED"
        ):
            raise ApiError("Image confirmation did not return a published image.")
        return image

    def upload_image(self, *, file_name: str, content_type: str, content: bytes) -> Dict[str, Any]:
        """Uploads a link image in one call and returns the published image.

        Runs :meth:`create_image_upload`, the PUT of ``content`` to the
        returned ``uploadUrl``, then :meth:`confirm_image_upload`. The PUT goes
        through the configured transport straight to the storage host with
        only ``uploadHeaders``: it does not go through the authenticated
        client, so the access token and the request signature are never sent
        there. A failed PUT is not retried; it raises :class:`ApiError` with the
        storage host's HTTP status (and its error code, e.g. ``AccessDenied``
        once the URL has expired). Call ``upload_image()`` again for a new URL.
        """
        data = _image_content(content)
        target = self.create_image_upload(
            file_name=file_name, content_type=content_type, size_bytes=len(data)
        )
        self._put_to_storage(target, data)
        return self.confirm_image_upload(target["assetId"])

    def _put_to_storage(self, target: Mapping[str, Any], data: bytes) -> None:
        """The presigned PUT. Deliberately NOT ``ApiClient.request()``.

        That path adds the bearer token and the Ed25519 signature headers, which
        must never reach the storage host (a presigned URL also refuses a
        request carrying ``Authorization``). Only the headers the URL was
        signed for are sent.
        """
        headers = dict(target["uploadHeaders"])
        try:
            response = self._config.transport.send(
                "PUT", target["uploadUrl"], headers, data, self._config.timeout_seconds
            )
        except TransportError:
            raise ApiError("Image upload to storage failed without a response.") from None
        if not response.ok:
            match = _STORAGE_ERROR_CODE.search(response.text())
            code = match.group(1) if match else None
            raise ApiError(
                f"Image upload to storage failed (HTTP {response.status_code}"
                f"{', ' + code if code else ''}).",
                status_code=response.status_code,
                code=code,
            )


# ── bodies ───────────────────────────────────────────────────────────────────


def _create_body(request: Any) -> Dict[str, Any]:
    body = plain(request)
    if not isinstance(body, Mapping):
        raise ConfigurationError(
            "Payment link request must be a CreatePaymentLinkRequest or a mapping."
        )
    body = dict(body)
    _assert_known(body, _CREATE_FIELDS, "create")
    return _normalize(body)


def _update_body(changes: Any) -> Dict[str, Any]:
    if not isinstance(changes, Mapping):
        raise ConfigurationError("Payment link changes must be a mapping.")
    if len(changes) == 0:
        raise ConfigurationError("Payment link update needs at least one changed field.")
    for key in changes:
        if key in PAYMENT_LINK_IMMUTABLE_FIELDS:
            raise ConfigurationError(
                f"'{key}' is fixed when a payment link is created and cannot be updated. "
                "Create a new link instead."
            )
    body = dict(changes)
    _assert_known(body, PAYMENT_LINK_SPEC_FIELDS, "update")
    return _normalize(body)


def _assert_known(body: Mapping[str, Any], allowed: Tuple[str, ...], operation: str) -> None:
    unknown = [str(key) for key in body if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown payment link {operation} field(s): {', '.join(unknown)}. "
            "The gateway rejects unknown fields with 400."
        )


def _normalize(body: Dict[str, Any]) -> Dict[str, Any]:
    for key in _TIME_FIELDS:
        if key in body:
            body[key] = iso_or_null(body[key], key)
    for key in _NESTED_LISTS:
        if isinstance(body.get(key), (list, tuple)):
            body[key] = [plain(entry) for entry in body[key]]
    return body


# ── query and paging ─────────────────────────────────────────────────────────


def _query(filters: Mapping[str, Any], allowed: Tuple[str, ...], operation: str) -> Dict[str, Any]:
    unknown = sorted(set(filters) - set(allowed))
    if unknown:
        raise ConfigurationError(
            f"Unknown payment link {operation} filter(s): {', '.join(unknown)}. "
            f"Accepted filters: {', '.join(allowed)}."
        )
    query: Dict[str, Any] = {}
    for key in allowed:
        value = filters.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            if any(not isinstance(entry, str) for entry in value):
                raise ConfigurationError(f"{key} must be a value or a list of strings.")
            if value:
                query[key] = ",".join(value)
        elif isinstance(value, datetime):
            query[key] = iso_or_null(value, key)
        else:
            query[key] = value
    return query


def _paginate(fetch_page: Any, filters: Mapping[str, Any]) -> Iterator[Dict[str, Any]]:
    cursor = filters.get("cursor")
    while True:
        page = fetch_page({**filters, "cursor": cursor})
        yield from page.items
        if not page.has_more or not page.next_cursor:
            return
        cursor = page.next_cursor


def _unwrap(response: Any) -> Any:
    return data_of(response)


# ── checks ───────────────────────────────────────────────────────────────────


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{name} is required.")
    return value.strip()


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string.")
    return value


def _one_of(value: Any, allowed: Tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise ConfigurationError(f"{name} must be one of {', '.join(allowed)}.")
    return value


def _link_path(link_id: Any) -> str:
    return f"{_BASE}/{encode_path_segment(_text(link_id, 'link_id'))}"


def _row_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigurationError(
            "expected_row_version must be the link's current rowVersion (a non-negative integer)."
        )
    return value


def _key_format(value: str) -> str:
    if IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ConfigurationError(
            "Idempotency-Key must be 8-200 printable ASCII characters without spaces."
        )
    return value


def _required_key(value: Any, operation: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(
            f"A stable idempotency_key is required for {operation}. Reuse the same key when "
            "retrying the same operation."
        )
    return _key_format(value)


def _optional_key(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigurationError("idempotency_key must be a string.")
    return _key_format(value)


def _image_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(
            f"Image size_bytes must be the file size in bytes (a positive integer); got {value!r}."
        )
    return value


def _image_content(content: Any) -> bytes:
    if not isinstance(content, (bytes, bytearray, memoryview)) or len(content) == 0:
        raise ConfigurationError("Image content must be non-empty bytes.")
    return bytes(content)


def _asset_id(value: Any) -> str:
    asset_id = value.strip() if isinstance(value, str) else ""
    if ASSET_ID_PATTERN.fullmatch(asset_id) is None:
        raise ConfigurationError(f"asset_id must be the image's asset id (uuid); got {value!r}.")
    return asset_id


def _upload_target(target: Any) -> Dict[str, Any]:
    """Uses an upload target only if it can be PUT as the contract describes.

    An asset id, an http(s) URL, the PUT method and string headers safe to
    send; anything else fails before a byte is uploaded.
    """
    headers = target.get("uploadHeaders") if isinstance(target, dict) else None
    usable = (
        isinstance(target, dict)
        and isinstance(target.get("assetId"), str)
        and ASSET_ID_PATTERN.fullmatch(target["assetId"]) is not None
        and _is_upload_url(target.get("uploadUrl"))
        and target.get("uploadMethod") == "PUT"
        and isinstance(headers, dict)
        and all(
            isinstance(name, str)
            and _HEADER_NAME.fullmatch(name) is not None
            and isinstance(value, str)
            and all(32 <= ord(c) < 127 for c in value)
            for name, value in headers.items()
        )
    )
    if not usable:
        raise ApiError("Image upload creation did not return a usable upload target.")
    return target


def _is_upload_url(value: Any) -> bool:
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme in _UPLOAD_SCHEMES
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False
