"""Physical POS payments, transactions, reports and end-of-day results.

Every route is under ``/api/v1/physical-pos`` and every call is signed per
request. The API key decides the environment; a TEST key reads only and is
refused on writes (``403 physical_pos.environment.test_key_read_only``).

===================================================  ==================================
``POST /payments``                                    :meth:`PhysicalPosClient.create_payment`
``POST /payments/{id}/reversals``                     :meth:`PhysicalPosClient.create_reversal`
``POST /payments/{id}/cancel``                        :meth:`PhysicalPosClient.cancel_payment`
``GET  /payments/{id}``                               :meth:`PhysicalPosClient.get_payment`
``GET  /payments``                                    :meth:`PhysicalPosClient.list_payments`
``GET  /transactions``                                :meth:`PhysicalPosClient.list_transactions`
``GET  /transactions/ambiguous``                      :meth:`PhysicalPosClient.list_ambiguous_payments`
``GET  /transactions/{paymentId}``                    :meth:`PhysicalPosClient.get_transaction`
``GET  /reports/sales-summary``                       :meth:`PhysicalPosClient.get_sales_summary`
``GET  /reports/tax-summary``                         :meth:`PhysicalPosClient.get_tax_summary`
``GET  /settlements``                                 :meth:`PhysicalPosClient.list_settlements`
===================================================  ==================================

🔴 NO CARD DATA. The card is read on the device; a request never carries a
card number, security code, track, PIN or expiry. A key that looks like one is
refused before sending with
:class:`~lunixi.errors.PhysicalPosCardDataRejectedError`.

🔴 STORE THE KEY FIRST. ``create_payment`` and ``create_reversal`` require
an ``idempotency_key``: create it with :meth:`PhysicalPosClient.new_idempotency_key`,
save it with your order, then call. If the call ends with
:class:`~lunixi.errors.PhysicalPosOutcomeUnknownError` (no answer, an
unreadable answer or a 5xx — the payment may exist), call again with the SAME
key: an existing payment comes back with ``replayed = True``; a new key can
charge the card twice. For a ``SALE``, a ``merchant_reference`` with
``allow_duplicate_reference`` left false is the gateway's second net against a
double charge.

🔴 A STARTED PAYMENT IS NOT A PAID PAYMENT. ``create_payment`` answers 202
with ``paymentStatus = NOT_STARTED``; the outcome arrives by webhook
(:class:`~lunixi.physical_pos.values.PhysicalPosEvents`) or ``get_payment``.

Resolving a payment under manual review is a panel action and is not part of
the API.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Mapping, Optional

from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from . import _support as s
from .results import PhysicalPosPaymentWriteResult
from ..webhook.verifier import WebhookVerifier
from .webhook import PhysicalPosWebhookEvent, parse_webhook_event

__all__ = ["PhysicalPosClient"]

_TARGET: s.Schema = {
    "deviceId": ("str", False, False),
    "vendorCode": ("str", False, False),
    "serialNumber": ("str", False, False),
    "externalRef": ("str", False, False),
}
_SALE_ITEM: s.Schema = {
    "lineNo": ("int", True, False),
    "name": ("str", True, False),
    "quantityMilli": ("int", True, False),
    "unitCode": ("str", True, False),
    "unitPriceMinor": ("money", True, False),
    "taxGroupCode": ("str", True, False),
    "lineTotalMinor": ("money", True, False),
    "barcode": ("str", False, False),
}
_REFUND_ITEM: s.Schema = {
    "lineNo": ("int", True, False),
    "quantityMilli": ("int", True, False),
    "amountMinor": ("money", False, False),
}
_PAYMENT: s.Schema = {
    "operation": ("str", True, False),
    "target": (_TARGET, True, False),
    "amountMinor": ("money", True, False),
    "currency": ("str", True, False),
    "installmentCount": ("int", False, False),
    "instrument": ("str", False, False),
    "merchantReference": ("str", False, False),
    "allowDuplicateReference": ("bool", False, False),
    "startTimeoutSeconds": ("int", False, False),
    "terminalAcquirerId": ("str", False, False),
    "items": (("list", _SALE_ITEM), False, False),
}
_REVERSAL: s.Schema = {
    "operation": ("str", True, False),
    "amountMinor": ("money", False, False),
    "currency": ("str", True, False),
    "merchantReference": ("str", False, False),
    "startTimeoutSeconds": ("int", False, False),
    "target": (_TARGET, False, False),
    "items": (("list", _REFUND_ITEM), False, False),
}


def _merge(request: Optional[Mapping[str, Any]], fields: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(request or {})
    overlap = sorted(set(merged) & set(fields))
    if overlap:
        raise ConfigurationError(
            "Field(s) given both in the request mapping and as keyword arguments: {}.".format(
                ", ".join(overlap)
            )
        )
    merged.update(fields)
    return merged


class PhysicalPosClient:
    """Physical POS payments and their records."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    # ── Payments ────────────────────────────────────────────────────────────

    def create_payment(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: str,
        **fields: Any,
    ) -> PhysicalPosPaymentWriteResult:
        """Starts a payment on a device: ``SALE``, ``PREAUTH_OPEN`` or ``REFUND_UNMATCHED``.

        Fields (wire or snake_case names): ``operation``, ``target`` (exactly
        one of ``{device_id}``, ``{vendor_code, serial_number}``,
        ``{external_ref}``), ``amount_minor`` (canonical minor-unit string),
        ``currency``, and optionally ``installment_count``, ``instrument``,
        ``merchant_reference``, ``allow_duplicate_reference``,
        ``start_timeout_seconds``, ``terminal_acquirer_id``, ``items`` (SALE
        only; leave it out for a sale without items).

        ``idempotency_key`` is REQUIRED (8–200 printable ASCII characters,
        sent exactly as given): create it with :meth:`new_idempotency_key`
        and store it with your order before calling. After
        :class:`~lunixi.errors.PhysicalPosOutcomeUnknownError` call again with
        THAT key — a new key can start a second payment.

        ``merchant_reference``, item ``name`` and ``tax_group_code`` must not
        hold a card number; one is refused before sending.
        """
        key = s.required_idempotency_key(idempotency_key)
        payload = s.body(_merge(request, fields), _PAYMENT)
        s.reject_pan_values(
            payload, ["merchantReference", "items[].taxGroupCode"], ["items[].name"]
        )
        return self._write(s.BASE + "/payments", payload, key, 202)

    def create_reversal(
        self,
        payment_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: str,
        **fields: Any,
    ) -> PhysicalPosPaymentWriteResult:
        """Reverses a payment: ``VOID``, ``REFUND`` (by amount or by item), ``PREAUTH_CLOSE``, ``PREAUTH_CANCEL``.

        ``payment_id`` is the original (root) payment. The answer's payment is
        the new child payment. ``amount_minor`` is required for ``REFUND`` and
        ``PREAUTH_CLOSE`` and left out for ``VOID`` / ``PREAUTH_CANCEL``; an
        item refund sends ``items=[{"line_no": 1, "quantity_milli": 1000}]``
        and the amount is derived by the gateway. ``target`` (another device)
        is allowed for ``REFUND`` only.

        ``idempotency_key`` is REQUIRED, with the same rules as
        :meth:`create_payment`: store it first, retry an unknown outcome with it.
        """
        key = s.required_idempotency_key(idempotency_key)
        path = f"{s.BASE}/payments/{s.path_id(payment_id, 'payment_id')}/reversals"
        payload = s.body(_merge(request, fields), _REVERSAL)
        s.reject_pan_values(payload, ["merchantReference"])
        return self._write(path, payload, key, 202)

    def cancel_payment(
        self, payment_id: str, *, idempotency_key: Optional[str] = None
    ) -> PhysicalPosPaymentWriteResult:
        """Cancels a payment whose start command has not reached the device yet.

        Read ``payment["paymentStatus"]`` in the answer: unless it is
        ``EXPIRED`` with ``statusReason = MERCHANT_CANCELLED_BEFORE_DISPATCH``
        nothing was cancelled (an already finished payment comes back as is,
        ``replayed = True``). Undo an approved sale with ``VOID`` or
        ``REFUND`` instead. Repeating a cancel is safe.

        ``idempotency_key`` is optional: when it is ``None`` the SDK creates
        one (returned in the result) so that its own retries are safe.
        """
        path = f"{s.BASE}/payments/{s.path_id(payment_id, 'payment_id')}/cancel"
        return self._write(path, {}, s.idempotency_key(idempotency_key), 200)

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        """One payment with its items and refund items. 404 ``physical_pos.payment.not_found``."""
        path = f"{s.BASE}/payments/{s.path_id(payment_id, 'payment_id')}"
        return s.member(self._get(path), "payment")

    def list_payments(self, **filters: Any) -> Page:
        """Payments and reversals, newest first.

        Filters: ``limit`` (1–100), ``cursor``, ``device_id``,
        ``payment_status``, ``created_from`` / ``created_to`` (ISO-8601 UTC
        ending with ``Z``), ``merchant_reference`` (exact match — use it to
        find a payment after an uncertain network outcome). Items are not
        listed; read them with :meth:`get_payment`.
        """
        return Page(self._get(s.BASE + "/payments", s.query(filters, "list_payments")))

    def iterate_payments(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Yields every payment matching the filters, following cursors."""
        return self._iterate(self.list_payments, filters)

    # ── Transactions ────────────────────────────────────────────────────────

    def list_transactions(self, **filters: Any) -> Page:
        """Transaction trees (root payment + its reversals), newest first.

        Filters: ``limit``, ``cursor``, ``device_id``, ``store_id``,
        ``register_id``, ``payment_status`` (of the root), ``created_from``,
        ``created_to``, ``merchant_reference``, ``amount_from_minor``,
        ``amount_to_minor``, ``origin`` (``API`` | ``DEVICE_DIRECT``),
        ``operation`` (``SALE`` | ``PREAUTH_OPEN`` | ``REFUND_UNMATCHED``).
        """
        return Page(self._get(s.BASE + "/transactions", s.query(filters, "list_transactions")))

    def iterate_transactions(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return self._iterate(self.list_transactions, filters)

    def get_transaction(self, payment_id: str) -> Dict[str, Any]:
        """One transaction tree with its timeline; a child id returns its root's tree."""
        path = f"{s.BASE}/transactions/{s.path_id(payment_id, 'payment_id')}"
        return s.member(self._get(path), "transaction")

    def list_ambiguous_payments(self, **filters: Any) -> Page:
        """Payments whose outcome is ``UNKNOWN`` or under ``MANUAL_REVIEW``.

        Filters: ``limit``, ``cursor``, ``device_id``, ``payment_status``
        (``UNKNOWN`` | ``MANUAL_REVIEW``). Do not charge such a payment again.
        """
        return Page(
            self._get(
                s.BASE + "/transactions/ambiguous", s.query(filters, "list_ambiguous_payments")
            )
        )

    def iterate_ambiguous_payments(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return self._iterate(self.list_ambiguous_payments, filters)

    # ── Reports and end of day ──────────────────────────────────────────────

    def get_sales_summary(self, **filters: Any) -> Dict[str, Any]:
        """Sale / refund / void counts and amounts with net.

        Filters: ``date_from`` / ``date_to`` (``YYYY-MM-DD`` business days,
        Europe/Istanbul, inclusive), ``device_id``, ``store_id``, ``group_by``
        (``DAY`` | ``STORE`` | ``DEVICE`` | ``INSTRUMENT``).
        """
        return s.data(
            self._get(s.BASE + "/reports/sales-summary", s.query(filters, "get_sales_summary"))
        )

    def get_tax_summary(self, **filters: Any) -> Dict[str, Any]:
        """Tax breakdown computed per item, with refunds and voids deducted.

        Filters: ``date_from``, ``date_to``, ``device_id``, ``store_id``.
        """
        return s.data(
            self._get(s.BASE + "/reports/tax-summary", s.query(filters, "get_tax_summary"))
        )

    def list_settlements(self, **filters: Any) -> Page:
        """End-of-day results per bank line, with reported, system and difference totals.

        Filters: ``limit``, ``cursor``, ``device_id``, ``line_status``
        (``MATCHED`` | ``MISMATCH`` | ``UNMAPPED``), ``created_from``,
        ``created_to``. Treat the cursor as opaque.

        Each line carries exactly one of ``commandId`` (end-of-day taken with
        a Lunixi command) and ``settlementRef`` (started on the device), plus
        ``acquirerRefRaw`` (the bank code as reported), ``acquirerName`` and
        ``deviceName``.
        """
        return Page(self._get(s.BASE + "/settlements", s.query(filters, "list_settlements")))

    def iterate_settlements(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return self._iterate(self.list_settlements, filters)

    # ── Webhooks ────────────────────────────────────────────────────────────

    @staticmethod
    def new_idempotency_key() -> str:
        """A new random UUID v4 for one payment start or reversal. Store it before calling."""
        return s.new_idempotency_key()

    @staticmethod
    def parse_webhook_event(
        raw_body: "str | bytes",
        headers: Mapping[str, Any],
        secret_or_verifier: "str | list[str] | WebhookVerifier",
        *,
        tolerance_seconds: Optional[int] = 300,
    ) -> PhysicalPosWebhookEvent:
        """Verifies and reads a physical POS webhook; see :func:`~lunixi.physical_pos.webhook.parse_webhook_event`."""
        return parse_webhook_event(
            raw_body, headers, secret_or_verifier, tolerance_seconds=tolerance_seconds
        )

    # ── Internals ───────────────────────────────────────────────────────────

    def _get(self, path: str, query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        return s.call(lambda: self._api.request("GET", path, None, query=query, step_up=True))

    def _write(
        self, path: str, payload: Dict[str, Any], key: str, fresh: int
    ) -> PhysicalPosPaymentWriteResult:
        response, payment = s.payment_write(self._api, path, payload, key)
        replayed = s.data(response).get("replayed") is True
        return PhysicalPosPaymentWriteResult(
            payment=payment,
            replayed=replayed,
            status_code=s.status_code(response, 200 if replayed else fresh),
            idempotency_key=key,
        )

    @staticmethod
    def _iterate(list_page: Any, filters: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        cursor = filters.pop("cursor", None)
        while True:
            page = list_page(cursor=cursor, **filters)
            for item in page.items:
                yield item
            if not page.has_more or not page.next_cursor:
                return
            cursor = page.next_cursor
