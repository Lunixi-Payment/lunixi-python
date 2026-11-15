"""Insurance — offer, sell and service insurance for your basket items, and submit leads.

``/api/v1/insurance``, product ``INSURANCE_SERVICE``. Every call is signed,
reads included; an unsigned request is 401 ``AUTH_HEADERS_MISSING`` and a key
without the product is 403 ``PRODUCT_NOT_ENABLED``. The key decides the
environment (TEST or LIVE).

Single-record answers are the envelope's ``data``; list calls return a
:class:`~lunixi.http.envelope.Page`. Request fields and query filters are
checked before anything is sent (the gateway rejects an unknown field with
400) and may be given in camelCase or snake_case (``from_`` for the ``from``
filter). The field rules of an insurance type's own object (``insured``,
``tickets`` …) are not repeated here: a violation comes back as 422
``insurance.validation.invalid`` with every ``details.errors[{field, reason}]``
at once. Amounts are canonical minor-unit strings.

``create_order``, ``confirm_payment``, ``issue_policy``, ``cancel_order``,
``refund_premium`` and ``create_lead`` require an ``idempotency_key``
(8–200 printable ASCII characters); ``create_quote`` and ``bind_payment``
take one optionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .._routes import (
    compact,
    currency_text,
    cursor_text,
    data_of,
    iso_time,
    items_page,
    merge_request,
    page_limit,
    paginate,
    path_segment,
    present,
    text,
    wire_fields,
)
from ..api_client import ApiClient, BinaryResponse
from ..errors import ConfigurationError
from ..http.envelope import Page
from ..validation import amount_minor
from .values import (
    INSURANCE_CONSENT_FIELDS,
    INSURANCE_CURSOR_MAX_LENGTH,
    INSURANCE_EXTERNAL_PAYMENT_FIELDS,
    INSURANCE_EXTERNAL_REFUND_FIELDS,
    INSURANCE_FILTERS,
    INSURANCE_IDEMPOTENCY_KEY_PATTERN,
    INSURANCE_LEAD_FIELDS,
    INSURANCE_LEAD_NOTE_MAX_LENGTH,
    INSURANCE_MAX_CONTEXT_ITEMS,
    INSURANCE_MAX_LIMIT,
    INSURANCE_ORDER_FIELDS,
    INSURANCE_PRODUCT_SEARCH_FIELDS,
    INSURANCE_QUOTE_FIELDS,
    InsuranceLeadStatus,
    InsurancePremiumCollectedBy,
    InsuranceReferenceKind,
)

__all__ = ["InsuranceClient", "InsuranceReconciliationExport"]

_BASE = "/api/v1/insurance"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_KEY = re.compile(INSURANCE_IDEMPOTENCY_KEY_PATTERN)
_TEXT_MAX_LENGTH = 128
_PDF_ACCEPT = "application/pdf, application/json"
_CSV_ACCEPT = "text/csv, application/json"
_TRUNCATED_LINE = re.compile(r"^# truncated=true orderCap=(\d+) nextCursor=(\S+)\s*$")
_ABORTED_LINE = re.compile(r"^# export-aborted=true\s*$")

Request = Optional[Mapping[str, Any]]


@dataclass(frozen=True)
class InsuranceReconciliationExport:
    """The reconciliation report as CSV (UTF-8 with BOM, one line per policy, minor-unit amounts).

    A file holds at most 20000 orders: when it was cut, ``truncated`` is true
    and ``next_cursor`` continues it (pass it as ``cursor``). ``aborted`` is
    true when the file ends with the gateway's abort line: it is incomplete,
    request it again.
    """

    content_type: Optional[str]
    content: bytes = field(repr=False)
    truncated: bool = False
    next_cursor: Optional[str] = None
    aborted: bool = False


class InsuranceClient:
    """Products, quotes, orders, policies, reconciliation and leads (I1–I22)."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    # ── Products and reference codes ─────────────────────────────────────────

    def list_products(self, **filters: Any) -> Any:
        """Insurance types offered for a payment's basket (``GET /products``).

        ``currency`` is required. With ``paymentIntentId`` the types are read
        from the items sent when the payment was created; without it, the
        insurance types sold without a basket item. An empty list means
        insurance is not offered; it is not an error.
        """
        query = _build_query(filters, "listProducts")
        _require_filters(query, ("currency",), "listProducts")
        return data_of(self._read("/products", query))

    def search_products(self, request: Request = None, **fields: Any) -> Any:
        """Insurance types offered for basket items before the payment exists (read-only).

        Send the items you will send in the payment: ``currency``, optional
        ``insuranceType``, ``context: {items}``.
        """
        body = _plain(merge_request(request, fields), "searchProducts request")
        _assert_keys(body, INSURANCE_PRODUCT_SEARCH_FIELDS, "searchProducts request")
        payload: Dict[str, Any] = {
            "currency": currency_text(body.get("currency"), "currency"),
            "context": _context(body.get("context")),
        }
        if present(body.get("insuranceType")):
            payload["insuranceType"] = text(body["insuranceType"], "insuranceType")
        return data_of(self._write("/products", payload))

    def list_reference_values(self, kind: str, **filters: Any) -> Page:
        """Lunixi reference codes of one :class:`~lunixi.insurance.values.InsuranceReferenceKind`.

        Filters: ``parentCode``, ``limit``, ``cursor``.
        """
        path = f"/reference/{path_segment(_reference_kind(kind), 'kind')}"
        return items_page(self._read(path, _build_query(filters, "listReferenceValues")))

    def iterate_reference_values(self, kind: str, **filters: Any) -> Iterator[Any]:
        _reference_kind(kind)
        return paginate(lambda page: self.list_reference_values(kind, **page), filters)

    # ── Quotes and orders ────────────────────────────────────────────────────

    def create_quote(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """Prices an insurance type (HTTP 201).

        The basket is either a payment's recorded basket (``paymentIntentId``)
        or the items you will send in the payment (``context.items``), not
        both. Send neither for an insurance type sold without a basket item.
        Every option of the answer has its own ``quoteId``, ``terms`` and
        ``expiresAt``; a company the request could not be priced with is in
        ``excludedOptions``. The ``idempotency_key`` is optional and only
        correlates traces: every call is a new, time-limited price.
        """
        body = _plain(merge_request(request, fields), "createQuote request")
        _assert_keys(body, INSURANCE_QUOTE_FIELDS, "createQuote request")
        has_payment = present(body.get("paymentIntentId"))
        has_items = present(body.get("context"))
        if has_payment and has_items:
            raise ConfigurationError(
                "Send the basket either as 'paymentIntentId' (a payment that exists) or as "
                "'context.items' (before the payment), not both. Send neither for an insurance "
                "type sold without a basket item."
            )
        payload = dict(body)
        payload["insuranceType"] = text(body.get("insuranceType"), "insuranceType")
        payload["currency"] = currency_text(body.get("currency"), "currency")
        payload["paymentIntentId"] = None
        payload["context"] = None
        if has_payment:
            payload["paymentIntentId"] = _uuid(body["paymentIntentId"], "paymentIntentId")
        if has_items:
            payload["context"] = _context(body["context"])
        order_id = body.get("merchantOrderId")
        payload["merchantOrderId"] = None
        if present(order_id):
            payload["merchantOrderId"] = text(order_id, "merchantOrderId", _TEXT_MAX_LENGTH)
        key = _optional_key(idempotency_key)
        return data_of(self._write("/quotes", compact(payload), key))

    def get_quote(self, quote_id: str) -> Any:
        """One quote option. 404 ``insurance.quote.not_found`` for an unknown or another merchant's quote."""
        return data_of(self._read(f"/quotes/{path_segment(quote_id, 'quote_id')}"))

    def create_order(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """Turns a quote option into an order (HTTP 201) and records the buyer's consent.

        Fields: ``quoteId``, optional ``merchantOrderId``, ``consent``
        (:meth:`consent_from_quote` builds it). No provider call and no money
        movement. The same key with the same body returns the recorded order,
        with another body 409 ``insurance.idempotency.conflict``.
        """
        body = _plain(merge_request(request, fields), "createOrder request")
        _assert_keys(body, INSURANCE_ORDER_FIELDS, "createOrder request")
        consent = _plain(body.get("consent"), "consent")
        _assert_keys(consent, INSURANCE_CONSENT_FIELDS, "consent")
        payload: Dict[str, Any] = {"quoteId": text(body.get("quoteId"), "quoteId")}
        order_id = body.get("merchantOrderId")
        if present(order_id):
            payload["merchantOrderId"] = text(order_id, "merchantOrderId", _TEXT_MAX_LENGTH)
        payload["consent"] = {
            "termsVersion": text(consent.get("termsVersion"), "consent.termsVersion"),
            "termsSha256": text(consent.get("termsSha256"), "consent.termsSha256"),
            "acceptedAt": iso_time(consent.get("acceptedAt"), "consent.acceptedAt"),
        }
        key = _required_key("insurance order create", idempotency_key)
        return data_of(self._write("/orders", payload, key))

    def list_orders(self, **filters: Any) -> Page:
        """Your insurance orders, newest first.

        Filters: ``limit``, ``cursor``, ``paymentIntentId``, ``merchantOrderId``.
        """
        return items_page(self._read("/orders", _build_query(filters, "listOrders")))

    def iterate_orders(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_orders(**page), filters)

    def get_order(self, order_id: str) -> Any:
        """404 ``insurance.order.not_found`` for an unknown or another merchant's order."""
        return data_of(self._read(_order_path(order_id)))

    def bind_payment(
        self, order_id: str, payment_intent_id: str, *, idempotency_key: Optional[str] = None
    ) -> Any:
        """Binds an order to the Lunixi payment that collects its premium.

        When you collect it (``premiumCollectedBy: MERCHANT``) the payment
        basket must hold the premium item (:meth:`premium_basket_item`); when
        the provider collects it, it must not. Binding the same payment again
        returns the order.
        """
        payload = {"paymentIntentId": _uuid(payment_intent_id, "paymentIntentId")}
        key = _optional_key(idempotency_key)
        return data_of(self._write(f"{_order_path(order_id)}/bind-payment", payload, key))

    def confirm_payment(
        self,
        order_id: str,
        payment: Mapping[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Records a premium you collected outside Lunixi.

        ``payment``: ``externalPaymentId``, ``paidAmount``, ``paidCurrency``,
        ``paidAt``, optional ``paymentProvider``. ``paidAmount`` and
        ``paidCurrency`` must equal the order's premium. Repeating the same
        ``externalPaymentId`` returns the order.
        """
        body = _plain(payment, "payment")
        _assert_keys(body, INSURANCE_EXTERNAL_PAYMENT_FIELDS, "payment")
        record: Dict[str, Any] = {
            "externalPaymentId": text(
                body.get("externalPaymentId"), "payment.externalPaymentId", _TEXT_MAX_LENGTH
            ),
            "paidAmount": _positive_minor(body.get("paidAmount"), "payment.paidAmount"),
            "paidCurrency": currency_text(body.get("paidCurrency"), "payment.paidCurrency"),
            "paidAt": iso_time(body.get("paidAt"), "payment.paidAt"),
        }
        provider = body.get("paymentProvider")
        if present(provider):
            record["paymentProvider"] = text(provider, "payment.paymentProvider", 64)
        key = _required_key("insurance payment confirmation", idempotency_key)
        path = f"{_order_path(order_id)}/confirm-payment"
        return data_of(self._write(path, {"payment": record}, key))

    def issue_policy(self, order_id: str, *, idempotency_key: Optional[str] = None) -> Any:
        """Requests the policy of an order whose premium you collected outside Lunixi.

        ``policyStatus`` becomes ``PENDING``; the result arrives by webhook.
        412 ``insurance.premium.not_captured`` before the premium is collected.
        """
        key = _required_key("insurance policy issue", idempotency_key)
        return data_of(self._write(f"{_order_path(order_id)}/issue-policy", None, key))

    def cancel_order(self, order_id: str, *, idempotency_key: Optional[str] = None) -> Any:
        """Opens a cancellation at the provider for every issued policy of the order.

        ``policyStatus`` becomes ``CANCEL_PENDING``; ``insurance.policy.cancelled``
        confirms it. Cancelling does not refund the premium: call
        :meth:`refund_premium` after it.
        """
        key = _required_key("insurance order cancel", idempotency_key)
        return data_of(self._write(f"{_order_path(order_id)}/cancel", None, key))

    def refund_premium(
        self,
        order_id: str,
        *,
        external_refund: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Refunds the premium.

        With a Lunixi payment, leave ``external_refund`` out: the premium is
        refunded from that payment (``refundStatus: PENDING``, then
        ``insurance.refund.completed``); the body is an empty JSON object. For
        a premium collected outside Lunixi, send the refund you made:
        ``{externalRefundId, refundedAt}``. An in-force policy must be
        cancelled first (409, ``policy_active``).
        """
        payload: Dict[str, Any] = {}
        if present(external_refund):
            refund = _plain(external_refund, "externalRefund")
            _assert_keys(refund, INSURANCE_EXTERNAL_REFUND_FIELDS, "externalRefund")
            payload["externalRefund"] = {
                "externalRefundId": text(
                    refund.get("externalRefundId"),
                    "externalRefund.externalRefundId",
                    _TEXT_MAX_LENGTH,
                ),
                "refundedAt": iso_time(refund.get("refundedAt"), "externalRefund.refundedAt"),
            }
        key = _required_key("insurance premium refund", idempotency_key)
        return data_of(self._write(f"{_order_path(order_id)}/refund-premium", payload, key))

    # ── Leads ────────────────────────────────────────────────────────────────

    def create_lead(
        self, request: Request = None, *, idempotency_key: Optional[str] = None, **fields: Any
    ) -> Any:
        """Submits a lead (HTTP 201) for an insurance type sold by request only.

        The provider gives no quote, so there is no premium, order, policy or
        document. ``policyholder``, the type object and an optional ``note``
        (sent as given, at most 1000 characters) follow the type's lead
        schema. The answer's ``status`` is ``SUBMITTED`` or ``UNKNOWN`` (the
        lead is not sent again). The same key with the same body returns the
        same lead, with another body 409 ``insurance.idempotency.conflict``.
        """
        key = _required_key("insurance lead submit", idempotency_key)
        body = _plain(merge_request(request, fields), "createLead request")
        _assert_keys(body, INSURANCE_LEAD_FIELDS, "createLead request")
        payload = dict(body)
        payload["insuranceType"] = text(body.get("insuranceType"), "insuranceType", 64)
        payload["note"] = _lead_note(body["note"]) if present(body.get("note")) else None
        return data_of(self._write("/leads", compact(payload), key))

    def list_leads(self, **filters: Any) -> Page:
        """Your leads, newest first; personal data is masked in ``requestMasked``.

        Filters: ``limit``, ``cursor``, ``insuranceType``, ``status``.
        """
        return items_page(self._read("/leads", _build_query(filters, "listLeads")))

    def iterate_leads(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_leads(**page), filters)

    def get_lead(self, lead_id: str) -> Any:
        """404 ``insurance.lead.not_found`` for an unknown or another merchant's lead."""
        return data_of(self._read(f"/leads/{path_segment(lead_id, 'lead_id')}"))

    # ── Policy files ─────────────────────────────────────────────────────────

    def get_policy_document(self, policy_id: str) -> BinaryResponse:
        """The policy PDF, read from the provider on every call.

        Available while the policy is in force (``ISSUED``,
        ``CANCEL_PENDING``); 503 ``insurance.document.unavailable`` is
        temporary — retry later.
        """
        return self._policy_file(policy_id, "document")

    def get_policy_receipt(self, policy_id: str) -> BinaryResponse:
        """The provider's premium receipt PDF; 412 ``insurance.document.not_supported`` when the
        product issues none."""
        return self._policy_file(policy_id, "receipt")

    def get_policy_certificate(self, policy_id: str) -> BinaryResponse:
        """The provider's policy certificate PDF (for example a motor Green Card); 412
        ``insurance.document.not_supported`` when the product issues none."""
        return self._policy_file(policy_id, "certificate")

    # ── Reconciliation ───────────────────────────────────────────────────────

    def get_reconciliation_summary(self, **filters: Any) -> Any:
        """Totals grouped by provider connection, currency and ``premiumCollectedBy``.

        ``from`` (inclusive; pass it as ``from_``) and ``to`` (exclusive) are
        required, on the order creation time, an aware datetime or an
        ISO-8601 string with a time zone, at most 366 days apart. Optional
        ``connectionId``, ``insuranceType``, ``currency``.
        """
        query = _build_query(filters, "getReconciliationSummary")
        _require_filters(query, ("from", "to"), "getReconciliationSummary")
        return data_of(self._read("/reconciliation/summary", query))

    def list_reconciliation_orders(self, **filters: Any) -> Page:
        """The orders and policies behind the summary for the same filter, newest first."""
        query = _build_query(filters, "listReconciliationOrders")
        _require_filters(query, ("from", "to"), "listReconciliationOrders")
        return items_page(self._read("/reconciliation/orders", query))

    def iterate_reconciliation_orders(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_reconciliation_orders(**page), filters)

    def export_reconciliation(self, **filters: Any) -> InsuranceReconciliationExport:
        """The reconciliation report as CSV, with its continuation state."""
        query = _build_query(filters, "exportReconciliation")
        _require_filters(query, ("from", "to"), "exportReconciliation")
        file = self._api.request_binary(
            "GET", f"{_BASE}/reconciliation/export", query=query, step_up=True, accept=_CSV_ACCEPT
        )
        return _export(file)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def consent_from_quote(option: Mapping[str, Any], accepted_at: Any) -> Dict[str, str]:
        """``consent`` for :meth:`create_order`.

        The quote option's ``terms`` unchanged and the moment the buyer
        accepted them (an aware datetime or an ISO-8601 string with a time
        zone, not in the future).
        """
        if not isinstance(option, Mapping):
            raise ConfigurationError("quote option must be a mapping.")
        terms = option.get("terms")
        if not isinstance(terms, Mapping):
            raise ConfigurationError(
                "The quote option has no 'terms': pass an option returned by create_quote() "
                "or get_quote()."
            )
        return {
            "termsVersion": text(terms.get("version"), "terms.version"),
            "termsSha256": text(terms.get("sha256"), "terms.sha256"),
            "acceptedAt": iso_time(accepted_at, "accepted_at"),
        }

    @staticmethod
    def premium_basket_item(
        order: Mapping[str, Any],
        *,
        name: str,
        category1: str,
        category2: Optional[str] = None,
    ) -> Dict[str, str]:
        """The premium basket item for a payment that collects the premium of an order.

        Only for ``premiumCollectedBy: MERCHANT``: ``id`` = ``orderId``,
        ``itemType: VIRTUAL``, ``price`` = ``premiumAmount``. Add it to the
        payment's basket next to the insured items and add the premium to the
        payment ``amount``; for insurance sold without a basket item it can be
        the only item. It carries no insurance field. A ``PROVIDER`` order
        must not have one.
        """
        if not isinstance(order, Mapping):
            raise ConfigurationError("order must be a mapping.")
        if order.get("premiumCollectedBy") != InsurancePremiumCollectedBy.MERCHANT:
            raise ConfigurationError(
                "Only an order whose premium you collect (premiumCollectedBy MERCHANT) has a "
                "premium basket item."
            )
        item = {
            "id": text(order.get("orderId"), "order.orderId"),
            "price": _positive_minor(order.get("premiumAmount"), "order.premiumAmount"),
            "name": text(name, "name"),
            "category1": text(category1, "category1"),
        }
        if present(category2):
            item["category2"] = text(category2, "category2")
        item["itemType"] = "VIRTUAL"
        return item

    def _read(self, path: str, query: Optional[Mapping[str, Any]] = None) -> Any:
        return self._api.request("GET", f"{_BASE}{path}", query=query or None, step_up=True)

    def _write(self, path: str, payload: Any, key: Optional[str] = None) -> Any:
        return self._api.request(
            "POST", f"{_BASE}{path}", payload, step_up=True, idempotency_key=key
        )

    def _policy_file(self, policy_id: str, file: str) -> BinaryResponse:
        path = f"{_BASE}/policies/{path_segment(policy_id, 'policy_id')}/{file}"
        return self._api.request_binary("GET", path, step_up=True, accept=_PDF_ACCEPT)


# ── checks ───────────────────────────────────────────────────────────────────


def _build_query(filters: Mapping[str, Any], route: str) -> Dict[str, Any]:
    allowed = INSURANCE_FILTERS[route]
    given = wire_fields(filters, "Insurance filters")
    unknown = [key for key in given if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown insurance filter(s): {', '.join(unknown)}. Allowed: {', '.join(allowed)}. "
            "The gateway rejects unknown query fields with 400."
        )
    query: Dict[str, Any] = {}
    for key in allowed:
        if present(given.get(key)):
            query[key] = _filter_value(key, given[key])
    return query


def _filter_value(key: str, value: Any) -> Any:
    if key == "limit":
        return page_limit(value, INSURANCE_MAX_LIMIT)
    if key == "cursor":
        return cursor_text(value, INSURANCE_CURSOR_MAX_LENGTH)
    if key == "currency":
        return currency_text(value, key)
    if key in ("paymentIntentId", "connectionId"):
        return _uuid(value, key)
    if key in ("from", "to"):
        return iso_time(value, key)
    if key in ("insuranceType", "parentCode"):
        return text(value, key, 64)
    if key == "merchantOrderId":
        return text(value, key, _TEXT_MAX_LENGTH)
    if key == "status":
        if value not in InsuranceLeadStatus.ALL:
            raise ConfigurationError(
                f"'status' must be one of {', '.join(InsuranceLeadStatus.ALL)}."
            )
        return value
    raise ConfigurationError(f"Unknown insurance filter '{key}'.")  # pragma: no cover


def _require_filters(query: Mapping[str, Any], required: Any, route: str) -> None:
    missing = [key for key in required if key not in query]
    if missing:
        raise ConfigurationError(
            f"{route} requires " + " and ".join(f"'{key}'" for key in missing) + "."
        )


def _reference_kind(kind: Any) -> str:
    if kind not in InsuranceReferenceKind.ALL:
        raise ConfigurationError(
            f"Reference kind must be one of {', '.join(InsuranceReferenceKind.ALL)}."
        )
    return kind


def _context(value: Any) -> Dict[str, List[Any]]:
    """``context: {items}`` — the same basket items the payment carries (1–100)."""
    if not present(value):
        raise ConfigurationError("'context.items' is required.")
    context = _plain(value, "context")
    _assert_keys(context, ("items",), "context")
    items = context.get("items")
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= INSURANCE_MAX_CONTEXT_ITEMS:
        raise ConfigurationError(
            f"'context.items' must hold 1 to {INSURANCE_MAX_CONTEXT_ITEMS} basket items."
        )
    return {"items": list(items)}


def _plain(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be a mapping.")
    return wire_fields(value, label)


def _assert_keys(value: Mapping[str, Any], allowed: Any, label: str) -> None:
    unknown = [key for key in value if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown {label} field(s): {', '.join(unknown)}. Allowed: {', '.join(allowed)}. "
            "The gateway rejects unknown fields with 400."
        )


def _uuid(value: Any, field_name: str) -> str:
    identifier = value.strip() if isinstance(value, str) else ""
    if not _UUID.fullmatch(identifier):
        raise ConfigurationError(f"'{field_name}' must be a Lunixi id (UUID).")
    return identifier


def _positive_minor(value: Any, field_name: str) -> str:
    try:
        return amount_minor(value)
    except ConfigurationError:
        raise ConfigurationError(
            f"{field_name} must be a positive canonical minor-unit string."
        ) from None


def _lead_note(value: Any) -> str:
    """The lead ``note`` is free text sent as given (not trimmed), at most 1000 characters."""
    if not isinstance(value, str):
        raise ConfigurationError("'note' must be a string.")
    if len(value) > INSURANCE_LEAD_NOTE_MAX_LENGTH:
        raise ConfigurationError(
            f"'note' must be at most {INSURANCE_LEAD_NOTE_MAX_LENGTH} characters."
        )
    return value


def _optional_key(key: Any) -> Optional[str]:
    if key is None or key == "":
        return None
    return _key_format(str(key).strip())


def _required_key(operation: str, key: Any) -> str:
    value = key.strip() if isinstance(key, str) else ""
    if not value:
        raise ConfigurationError(
            f"A stable Idempotency-Key is required for {operation}. "
            "Reuse the same key when retrying the same operation."
        )
    return _key_format(value)


def _key_format(value: str) -> str:
    if not _KEY.fullmatch(value):
        raise ConfigurationError(
            "Idempotency-Key must be 8-200 printable ASCII characters without spaces."
        )
    return value


def _order_path(order_id: str) -> str:
    return f"/orders/{path_segment(order_id, 'order_id')}"


def _export(file: BinaryResponse) -> InsuranceReconciliationExport:
    lines = [line for line in re.split(r"\r?\n", file.content.decode("utf-8", "replace")) if line]
    last = lines[-1] if lines else ""
    truncated = _TRUNCATED_LINE.match(last)
    return InsuranceReconciliationExport(
        content_type=file.content_type,
        content=file.content,
        truncated=truncated is not None,
        next_cursor=truncated.group(2) if truncated else None,
        aborted=_ABORTED_LINE.match(last) is not None,
    )
