"""Outgoing bank transfers and currency exchange — ``bank_connect().transfers`` and ``bank_connect().fx``.

Available on a connection whose ``capabilities`` include ``OUTGOING_TRANSFER``
(transfers) or ``FX_EXCHANGE`` (exchange). Every route, reads included, is
signed and needs the ``bank-connect:transfer`` scope; the key must have an IP
allowlist and the request must come from a listed IP (403
``bank_connect.auth.ip_allowlist_required`` / ``bank_connect.auth.ip_not_allowed``).

With an API key there is no e-mail code: the key's scope, the signature and
the source IP approve the transfer, so a created transfer is ``SUBMITTED`` and
queued for the bank. Follow it with ``get()`` or the ``bank_transfer.*``
webhooks. The bank chooses the rail; Lunixi does not check the balance — the
bank decides.

Every call is checked against
:data:`~lunixi.bank_connect.values.BANK_TRANSFER_ROUTES` before it is sent.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterator, Mapping, Optional

from .._routes import (
    currency_text,
    cursor_text,
    data_of,
    fill_path,
    iso_time,
    items_page,
    merge_request,
    page_limit,
    paginate,
    present,
    text,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from ..validation import amount_minor
from .values import (
    BANK_CONNECT_CURSOR_MAX_LENGTH,
    BANK_CONNECT_MAX_LIMIT,
    BANK_TRANSFER_DESCRIPTION_MAX,
    BANK_TRANSFER_IBAN_MAX,
    BANK_TRANSFER_IDEMPOTENCY_KEY_PATTERN,
    BANK_TRANSFER_PAYMENT_PURPOSE_PATTERN,
    BANK_TRANSFER_RECEIVER_NAME_MAX,
    BANK_TRANSFER_RECEIVER_NAME_MIN,
    BANK_TRANSFER_ROUTES,
    BankFxOrderStatus,
    BankTransferStatus,
)

__all__ = ["BankTransferClient", "BankFxClient", "transfer_idempotency_key"]

_KEY = re.compile(BANK_TRANSFER_IDEMPOTENCY_KEY_PATTERN)
_PURPOSE = re.compile(BANK_TRANSFER_PAYMENT_PURPOSE_PATTERN)
_AMOUNT_FIELDS = ("amountMinor", "sourceAmountMinor", "targetAmountMinor")


class BankTransferClient:
    """Outgoing transfers (``/api/v1/bank-connect/transfers``)."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def list_purposes(self, connection_id: str) -> Any:
        """Payment purpose codes the bank accepts on this connection: ``{items: [{code, name, order}]}``.

        Pass one as ``paymentPurpose`` to :meth:`create`; leave it out for the
        bank's default.
        """
        query = {"connectionId": text(connection_id, "connection_id")}
        return data_of(_invoke(self._api, "listTransferPurposes", {"query": query}))

    def create(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Creates an outgoing transfer (HTTP 201): ``{transfer, stepUp, replayed}``.

        Fields: ``accountId`` (source account), ``receiverIban`` (TR IBAN),
        ``receiverName`` (2–140 characters), ``amountMinor`` (positive
        canonical minor-unit string: ``"150075"`` = 1,500.75 TRY), optional
        ``currency`` (TRY), ``paymentPurpose`` and ``description`` (at most
        140 characters).

        ``idempotency_key`` (8–200 printable ASCII) is generated (UUID v4) when
        left out; a network error or a 5xx is retried with the same key. Keep
        your own key (e.g. your payout id) to retry safely across processes:
        the same key with the same body answers the existing transfer with
        ``replayed: True``; with another body it is 409
        ``bank_connect.transfer.idempotency_conflict``. The key used is also
        in ``transfer.idempotencyKey``.
        """
        body = _check_body("createTransfer", merge_request(request, fields))
        _check_transfer_body(body)
        key = transfer_idempotency_key(idempotency_key)
        return data_of(_invoke(self._api, "createTransfer", None, body, key))

    def list(self, **filters: Any) -> Page:
        """Transfers, newest first.

        Filters: ``accountId``, ``status`` (one or a list of
        :class:`~lunixi.bank_connect.values.BankTransferStatus`),
        ``createdFrom`` (inclusive) / ``createdTo`` (exclusive) as an aware
        datetime or an ISO-8601 string, ``limit`` 1–100, ``cursor``.
        """
        query = _transfer_query(filters, "listTransfers")
        return items_page(_invoke(self._api, "listTransfers", {"query": query}))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def get(self, transfer_id: str) -> Any:
        """One transfer. 404 ``bank_connect.transfer.not_found`` for an unknown id."""
        return data_of(_invoke(self._api, "getTransfer", {"transferId": transfer_id}))


class BankFxClient:
    """Currency exchange between two of your accounts (``/api/v1/bank-connect/fx``).

    The two accounts are active accounts of the same connection in different
    currencies. Flow: :meth:`list_rates` (optional) → :meth:`create_quote` →
    :meth:`create_order` with the quote id before ``quote.expiresAt`` (the
    bank sets the validity, typically under two minutes; see
    ``validForSeconds``). The order is ``SUBMITTED`` and queued; follow it with
    :meth:`get_order`. There is no webhook for exchange orders.
    """

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def list_rates(self, connection_id: str) -> Any:
        """Current rates on the connection: ``{items, refreshSeconds, fetchedAt}``; rates are decimal strings."""
        query = {"connectionId": text(connection_id, "connection_id")}
        return data_of(_invoke(self._api, "listFxRates", {"query": query}))

    def create_quote(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        """Quotes an exchange (HTTP 201).

        Fields: ``sourceAccountId`` (you sell from it), ``targetAccountId``
        (you buy into it) and exactly one of ``sourceAmountMinor`` /
        ``targetAmountMinor`` (positive canonical minor-unit string of that
        account's currency). Nothing is booked; a quote is used by one order.
        """
        body = _check_body("createFxQuote", merge_request(request, fields))
        if ("sourceAmountMinor" in body) == ("targetAmountMinor" in body):
            raise ConfigurationError(
                "createFxQuote takes exactly one of sourceAmountMinor and targetAmountMinor."
            )
        if body["sourceAccountId"] == body["targetAccountId"]:
            raise ConfigurationError("createFxQuote needs two different accounts.")
        return data_of(_invoke(self._api, "createFxQuote", None, body))

    def create_order(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Executes a quote (HTTP 201): ``{order, replayed}``.

        Fields: ``quoteId``, optional ``description`` (at most 140
        characters). ``idempotency_key`` follows the rule of
        :meth:`BankTransferClient.create` and is generated when left out. 409
        ``bank_connect.fx.quote_expired`` / ``bank_connect.fx.quote_used``: ask
        for a new quote.
        """
        body = _check_body("createFxOrder", merge_request(request, fields))
        if "description" in body:
            _check_description(body["description"])
        key = transfer_idempotency_key(idempotency_key)
        return data_of(_invoke(self._api, "createFxOrder", None, body, key))

    def list_orders(self, **filters: Any) -> Page:
        """Exchange orders, newest first. Filters: ``status`` (one or a list of
        :class:`~lunixi.bank_connect.values.BankFxOrderStatus`), ``limit``, ``cursor``."""
        query = _transfer_query(filters, "listFxOrders")
        return items_page(_invoke(self._api, "listFxOrders", {"query": query}))

    def iterate_orders(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_orders(**page), filters)

    def get_order(self, order_id: str) -> Any:
        """One exchange order. 404 ``bank_connect.fx.order_not_found`` for an unknown id."""
        return data_of(_invoke(self._api, "getFxOrder", {"orderId": order_id}))


def transfer_idempotency_key(value: Optional[str]) -> str:
    """The caller's key, checked; a missing one is generated (UUID v4)."""
    if value is None or value == "":
        return str(uuid.uuid4())
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ConfigurationError(
            "idempotency_key must be 8-200 printable ASCII characters (no spaces)."
        )
    return value


def _invoke(
    api: ApiClient,
    route_name: str,
    params: Optional[Mapping[str, Any]] = None,
    body: Optional[Mapping[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Any:
    """Sends one route of :data:`BANK_TRANSFER_ROUTES`, signed."""
    route = BANK_TRANSFER_ROUTES[route_name]
    params = params or {}
    path = fill_path(route["path"], params)
    query = params.get("query") or None
    key = idempotency_key if route["idempotencyKey"] else None
    return api.request(
        route["method"],
        path,
        dict(body) if body is not None else None,
        query=query,
        step_up=True,
        idempotency_key=key,
    )


def _check_body(route_name: str, request: Mapping[str, Any]) -> Dict[str, Any]:
    """Whitelists the body against the route: unknown or missing fields fail before sending."""
    route = BANK_TRANSFER_ROUTES[route_name]
    allowed = (*route["required"], *route["optional"])
    body: Dict[str, Any] = {}
    for key, value in wire_fields(request, f"{route_name} body").items():
        if value is None or value == "":
            continue
        if key not in allowed:
            raise ConfigurationError(
                f"{route_name} does not accept {key} (the gateway rejects unknown fields with 400)."
            )
        body[key] = amount_minor(value) if key in _AMOUNT_FIELDS else value
    missing = [key for key in route["required"] if key not in body]
    if missing:
        raise ConfigurationError(f"{route_name} requires {', '.join(missing)}.")
    for key in route["required"]:
        if key not in _AMOUNT_FIELDS:
            body[key] = text(body[key], f"'{key}'")
    return body


def _check_transfer_body(body: Dict[str, Any]) -> None:
    if len(body["receiverIban"]) > BANK_TRANSFER_IBAN_MAX:
        raise ConfigurationError(
            f"'receiverIban' must be at most {BANK_TRANSFER_IBAN_MAX} characters."
        )
    name_length = len(body["receiverName"])
    if not BANK_TRANSFER_RECEIVER_NAME_MIN <= name_length <= BANK_TRANSFER_RECEIVER_NAME_MAX:
        raise ConfigurationError(
            f"'receiverName' must be {BANK_TRANSFER_RECEIVER_NAME_MIN}-"
            f"{BANK_TRANSFER_RECEIVER_NAME_MAX} characters."
        )
    if "currency" in body:
        body["currency"] = currency_text(body["currency"], "currency")
    purpose = body.get("paymentPurpose")
    if purpose is not None and (not isinstance(purpose, str) or not _PURPOSE.fullmatch(purpose)):
        raise ConfigurationError(
            "'paymentPurpose' must be a code from list_purposes() "
            "(letters, digits, underscore; at most 64)."
        )
    if "description" in body:
        _check_description(body["description"])


def _check_description(value: Any) -> None:
    if not isinstance(value, str) or len(value) > BANK_TRANSFER_DESCRIPTION_MAX:
        raise ConfigurationError(
            f"'description' must be a string of at most {BANK_TRANSFER_DESCRIPTION_MAX} characters."
        )


def _transfer_query(filters: Mapping[str, Any], route_name: str) -> Dict[str, Any]:
    """List filters of ``listTransfers`` / ``listFxOrders``, checked against the route's query fields."""
    allowed = BANK_TRANSFER_ROUTES[route_name]["query"]
    given = wire_fields(filters, "Filters")
    unknown = [key for key in given if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown filter(s): {', '.join(unknown)}. Allowed: {', '.join(allowed)}. "
            "The gateway rejects unknown query fields with 400."
        )
    query: Dict[str, Any] = {}
    for key in allowed:
        value = given.get(key)
        if not present(value):
            continue
        if key == "limit":
            query[key] = page_limit(value, BANK_CONNECT_MAX_LIMIT)
        elif key == "cursor":
            query[key] = cursor_text(value, BANK_CONNECT_CURSOR_MAX_LENGTH)
        elif key == "status":
            allowed_status = (
                BankFxOrderStatus.ALL if route_name == "listFxOrders" else BankTransferStatus.ALL
            )
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            for entry in values:
                if not isinstance(entry, str) or entry not in allowed_status:
                    raise ConfigurationError(
                        f"'status' must be one of {', '.join(allowed_status)}."
                    )
            query[key] = ",".join(str(entry) for entry in values)
        elif key == "accountId":
            query[key] = text(value, "accountId")
        else:
            query[key] = iso_time(value, key)
    return query
