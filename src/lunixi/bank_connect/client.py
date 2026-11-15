"""Bank accounts — read your connected bank accounts, balances and transactions.

``/api/v1/bank-connect``, product ``BANK_CONNECT``. These routes accept the
API key's per-request Ed25519 signature only, so every call is sent signed,
reads included; an unsigned request is 401 ``AUTH_HEADERS_MISSING``. Scopes:
``bank-connect:view`` for banks, connections, accounts and
:meth:`BankConnectClient.request_sync`; ``bank-connect:transactions:view`` for
balances and transactions (403 ``API_INSUFFICIENT_SCOPE`` otherwise). The key
decides the environment: a TEST key reads only test-environment accounts, a
LIVE key only live ones.

Connecting a bank and entering bank credentials happen in the Lunixi
dashboard only. Another organisation's or the other environment's record is
404, the same as a record that does not exist.

Money movement lives on two sub-clients, available when the connection offers
it (``capabilities`` has ``OUTGOING_TRANSFER`` / ``FX_EXCHANGE``):
``transfers`` (:class:`~lunixi.bank_connect.transfers.BankTransferClient`) and
``fx`` (:class:`~lunixi.bank_connect.transfers.BankFxClient`).

Single-record answers are the envelope's ``data``; list calls return a
:class:`~lunixi.http.envelope.Page`. Filters are checked before anything is
sent (the gateway rejects an unknown query field with 400): an unknown
filter, a value outside its set or a malformed amount or date range raises
:class:`~lunixi.errors.ConfigurationError`. Filter names may be camelCase or
snake_case.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Mapping, Optional

from .._routes import (
    currency_text,
    cursor_text,
    data_of,
    epoch_seconds,
    iso_time,
    items_page,
    page_limit,
    paginate,
    path_segment,
    present,
    text,
    wire_fields,
)
from ..api_client import ApiClient
from ..errors import ConfigurationError
from ..http.envelope import Page
from ..validation import amount_minor
from .transfers import BankFxClient, BankTransferClient
from .values import (
    BANK_CONNECT_BOOKED_RANGE_MAX_DAYS,
    BANK_CONNECT_CURSOR_MAX_LENGTH,
    BANK_CONNECT_FILTERS,
    BANK_CONNECT_MAX_ACCOUNT_FILTER,
    BANK_CONNECT_MAX_LIMIT,
    BankAccountStatus,
    BankConnectionStatus,
    BankTransactionDirection,
    BankTransactionType,
)

__all__ = ["BankConnectClient", "build_query"]

_BASE = "/api/v1/bank-connect"
_DAY_SECONDS = 24 * 60 * 60


class BankConnectClient:
    """Banks, connections, accounts, balances and transactions; ``transfers`` and ``fx``."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api
        #: Outgoing transfers from a connected account (``bank-connect:transfer``).
        self.transfers = BankTransferClient(api)
        #: Currency exchange between two of your accounts on one connection (``bank-connect:transfer``).
        self.fx = BankFxClient(api)

    def list_banks(self, **filters: Any) -> Page:
        """The bank catalogue: whether each bank can be connected and what is read from it."""
        return items_page(self._read("/banks", build_query(filters, "listBanks")))

    def iterate_banks(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_banks(**page), filters)

    def list_connections(self, **filters: Any) -> Page:
        """Your bank connections, newest first. ``status`` takes one value or a list."""
        return items_page(self._read("/connections", build_query(filters, "listConnections")))

    def iterate_connections(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_connections(**page), filters)

    def get_connection(self, connection_id: str) -> Any:
        """404 ``bank_connect.connection.not_found`` for an unknown connection."""
        return data_of(self._read(f"/connections/{path_segment(connection_id, 'connection_id')}"))

    def list_accounts(self, **filters: Any) -> Page:
        """Your connected accounts, newest first, each with its data ``freshness``."""
        return items_page(self._read("/accounts", build_query(filters, "listAccounts")))

    def iterate_accounts(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_accounts(**page), filters)

    def get_account(self, account_id: str) -> Any:
        """404 ``bank_connect.account.not_found`` for an unknown account."""
        return data_of(self._read(_account_path(account_id)))

    def request_sync(self, account_id: str) -> Any:
        """Asks for a fresh read of the account from the bank (HTTP 202).

        It never reads earlier than the bank's minimum interval: when the
        interval has not passed the answer is ``SCHEDULED`` with
        ``scheduledAt``, and a request while one is already waiting joins it.
        Nothing is written, so no ``Idempotency-Key`` is needed. New
        transactions arrive by the ``bank_account.transaction.received``
        webhook.

        409 ``bank_connect.connection.not_active`` when the connection is not
        ``ACTIVE`` or ``DEGRADED``; 429 ``RATE_LIMITED``
        (:class:`~lunixi.errors.RateLimitError` with ``retry_after``) when the
        key sent too many sync requests in the last minute.
        """
        path = f"{_BASE}{_account_path(account_id)}/sync"
        return data_of(self._api.request("POST", path, None, step_up=True))

    def list_balances(self, **filters: Any) -> Page:
        """The latest balance of each account; without ``accountId`` every active account."""
        return items_page(self._read("/balances", build_query(filters, "listBalances")))

    def iterate_balances(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_balances(**page), filters)

    def list_transactions(self, **filters: Any) -> Page:
        """Transactions, newest recorded first.

        The order is ``receivedAt`` (when Lunixi recorded the transaction),
        which never changes, so paging forward never skips a transaction that
        arrives late with an older bank date. ``bookedFrom`` (inclusive) /
        ``bookedTo`` (exclusive) filter on the bank date: an aware datetime or
        an ISO-8601 string with a time zone, at most 92 days apart;
        ``bookedTo`` needs ``bookedFrom`` (``bookedFrom`` alone runs up to
        now). ``minAmountMinor`` / ``maxAmountMinor`` are inclusive canonical
        minor-unit strings.
        """
        query = build_query(filters, "listTransactions")
        _assert_booked_range(wire_fields(filters, "filters"))
        low, high = query.get("minAmountMinor"), query.get("maxAmountMinor")
        if low is not None and high is not None and int(low) > int(high):
            raise ConfigurationError("'minAmountMinor' must not be greater than 'maxAmountMinor'.")
        return items_page(self._read("/transactions", query))

    def iterate_transactions(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list_transactions(**page), filters)

    def get_transaction(self, transaction_id: str) -> Any:
        """One transaction with its detail fields (``balanceAfterMinor``, ``documentNo``, ``bank``)."""
        path = f"/transactions/{path_segment(transaction_id, 'transaction_id')}"
        return data_of(self._read(path))

    def _read(self, path: str, query: Optional[Mapping[str, Any]] = None) -> Any:
        return self._api.request("GET", f"{_BASE}{path}", query=query or None, step_up=True)


def build_query(filters: Mapping[str, Any], route: str) -> Dict[str, Any]:
    """Checks the filters of one read route against :data:`BANK_CONNECT_FILTERS`."""
    allowed = BANK_CONNECT_FILTERS[route]
    given = wire_fields(filters, "Bank-connect filters")
    unknown = [key for key in given if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown bank-connect filter(s): {', '.join(unknown)}. Allowed: "
            f"{', '.join(allowed)}. The gateway rejects unknown query fields with 400."
        )
    query: Dict[str, Any] = {}
    for key in allowed:
        value = given.get(key)
        if present(value):
            query[key] = _filter_value(key, value, route)
    return query


def _filter_value(key: str, value: Any, route: str) -> Any:
    if key == "limit":
        return page_limit(value, BANK_CONNECT_MAX_LIMIT)
    if key == "cursor":
        return cursor_text(value, BANK_CONNECT_CURSOR_MAX_LENGTH)
    if key == "status":
        if route == "listAccounts":
            return _one_of(key, value, BankAccountStatus.ALL)
        return _list_of(key, value, BankConnectionStatus.ALL)
    if key == "direction":
        return _one_of(key, value, BankTransactionDirection.ALL)
    if key == "canonicalType":
        return _list_of(key, value, BankTransactionType.ALL)
    if key == "accountId":
        return _id_list(value)
    if key in ("bankId", "connectionId"):
        return text(value, key)
    if key == "currency":
        return currency_text(value, key)
    if key in ("bookedFrom", "bookedTo"):
        return iso_time(value, key)
    if key in ("minAmountMinor", "maxAmountMinor"):
        return amount_minor(value, positive=False)
    raise ConfigurationError(f"Unknown bank-connect filter '{key}'.")  # pragma: no cover


def _one_of(key: str, value: Any, allowed: Any) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigurationError(f"'{key}' must be one of {', '.join(allowed)}.")
    return value


def _list_of(key: str, value: Any, allowed: Any) -> str:
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    return ",".join(_one_of(key, entry, allowed) for entry in values)


def _id_list(value: Any) -> str:
    ids = list(value) if isinstance(value, (list, tuple)) else [value]
    if len(ids) > BANK_CONNECT_MAX_ACCOUNT_FILTER:
        raise ConfigurationError(
            f"'accountId' takes at most {BANK_CONNECT_MAX_ACCOUNT_FILTER} account ids."
        )
    out = []
    for account_id in ids:
        if not isinstance(account_id, str) or account_id.strip() == "" or "," in account_id:
            raise ConfigurationError("'accountId' must be account ids (strings without commas).")
        out.append(account_id.strip())
    return ",".join(out)


def _assert_booked_range(filters: Mapping[str, Any]) -> None:
    """``bookedTo`` needs ``bookedFrom``, ``bookedFrom`` <= ``bookedTo``, at most 92 days."""
    if present(filters.get("bookedTo")) and not present(filters.get("bookedFrom")):
        raise ConfigurationError(
            "'bookedTo' needs 'bookedFrom': a window without a start is unbounded."
        )
    start = epoch_seconds(filters.get("bookedFrom"))
    end = epoch_seconds(filters.get("bookedTo"))
    if start is None or end is None:
        return
    if start > end:
        raise ConfigurationError("'bookedFrom' must not be after 'bookedTo'.")
    if end - start > BANK_CONNECT_BOOKED_RANGE_MAX_DAYS * _DAY_SECONDS:
        raise ConfigurationError(
            f"'bookedFrom' and 'bookedTo' may be at most {BANK_CONNECT_BOOKED_RANGE_MAX_DAYS} "
            "days apart. Page through narrower windows."
        )


def _account_path(account_id: str) -> str:
    return f"/accounts/{path_segment(account_id, 'account_id')}"
