"""Wallet — ``/api/v1/wallet/*``, the merchant server-to-server surface of the closed-loop wallet.

Every route is authenticated by the API key's per-request Ed25519 signature,
so every call is sent signed (reads included); the merchant, its programs and
its end users come from the signing key. The key also needs the
``WALLET_SERVICE`` product (otherwise 403 ``PRODUCT_NOT_ENABLED``) and the
wallet permission behind the route (otherwise 403
``WALLET_INSUFFICIENT_SCOPE``): ``wallet:*:read`` for reads,
``wallet:program|enduser|limit|fee:manage`` for set-up,
``wallet:operation:intervene`` for moving money inside the wallet,
``wallet:bank-payout:operate`` for IBAN transfers and bank withdrawals,
``wallet:qr:manage``, ``wallet:bulk:create``, ``wallet:bulk:approve`` and
``wallet:enduser:kyc-override`` for the KYC level.

Amounts are minor units as digit strings (``"12550"`` = 125.50 TRY). A call
that moves money for an end user names that end user (``endUserId``,
``buyerEndUserId``); the source account must belong to them or the answer is
404 ``WALLET_NOT_FOUND``.

Every call is checked against :data:`~lunixi.wallet.values.WALLET_ROUTES`
before anything is sent: an unknown field, a missing required field, an
amount that is not a digit string or a missing ``Idempotency-Key`` raises
:class:`~lunixi.errors.ConfigurationError`. Body fields may be given as a
mapping or as keyword arguments, in camelCase or snake_case.

Single-record answers are the envelope's ``data``; list calls return a
:class:`~lunixi.http.envelope.Page`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from .._routes import (
    compact,
    cursor_page,
    data_of,
    fill_path,
    merge_request,
    paginate,
    wire_fields,
)
from ..api_client import ApiClient, BinaryResponse
from ..errors import ConfigurationError
from ..http.envelope import Page, page_info_of
from ..validation import amount_minor
from .values import (
    AMOUNT_PATTERN,
    WALLET_AMOUNT_FIELDS,
    WALLET_IDEMPOTENCY_KEY_MAX,
    WALLET_NESTED_FIELDS,
    WALLET_QR_SCALE_MAX,
    WALLET_QR_SCALE_MIN,
    WALLET_ROUTES,
    WalletQrImageFormat,
)

__all__ = [
    "WalletClient",
    "WalletPrograms",
    "WalletEndUsers",
    "WalletAccounts",
    "WalletDeposits",
    "WalletCorporate",
    "WalletFees",
    "WalletTransfers",
    "WalletWithdrawals",
    "WalletOperations",
    "WalletTopups",
    "WalletPayments",
    "WalletQr",
    "WalletBulkPayouts",
]

_AMOUNT = re.compile(AMOUNT_PATTERN)
_IMAGE_ACCEPT = "image/svg+xml, image/png, application/json"

Call = Callable[..., Any]


class WalletClient:
    """The wallet surface; money movement and records live on the sub-clients."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

        def call(
            route: str,
            params: Optional[Mapping[str, Any]] = None,
            body: Optional[Mapping[str, Any]] = None,
            idempotency_key: Optional[str] = None,
        ) -> Any:
            return invoke(api, route, params, body, idempotency_key)

        self.programs = WalletPrograms(call)
        self.end_users = WalletEndUsers(call)
        self.wallets = WalletAccounts(call)
        self.deposits = WalletDeposits(call)
        self.corporate = WalletCorporate(call)
        self.fees = WalletFees(call)
        self.transfers = WalletTransfers(call)
        self.withdrawals = WalletWithdrawals(call)
        self.operations = WalletOperations(call)
        self.topups = WalletTopups(call)
        self.payments = WalletPayments(call)
        self.qr = WalletQr(call)
        self.bulk_payouts = WalletBulkPayouts(call)

    def ping(self) -> Any:
        """Checks the key reaches the wallet (signature, product, a ``wallet:*:manage`` permission)."""
        return data_of(invoke(self._api, "ping"))


class _Section:
    def __init__(self, call: Call) -> None:
        self._call = call


class WalletPrograms(_Section):
    def list_mine(self) -> Page:
        """The wallet programs of the signing merchant."""
        return to_page(self._call("listMyPrograms"))

    def set_collection_anchor(
        self, program_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Any:
        """Sets the end user whose wallet collects the program's merchant payments.

        Fields: ``collectionEndUserId``, ``reason``, ``expectedVersion``.
        Leaving ``collectionEndUserId`` out clears the anchor.
        """
        params = {"programId": program_id}
        return data_of(self._call("setCollectionAnchor", params, merge_request(request, fields)))


class WalletEndUsers(_Section):
    def create(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Creates an end user and their default wallet (``programId``, ``accountType``, ``phone`` …)."""
        body = merge_request(request, fields)
        return data_of(self._call("createEndUser", None, body, idempotency_key))

    def list(self, **filters: Any) -> Page:
        """Filters: ``programId``, ``accountType``, ``status``, ``corporateAccountId``,
        ``merchantCategoryState``, ``limit``, ``cursor``."""
        return to_page(self._call("listEndUsers", {"query": filters}))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def get(self, end_user_id: str) -> Any:
        return data_of(self._call("getEndUser", {"endUserId": end_user_id}))

    def get_by_external_id(
        self, external_customer_id: str, program_id: Optional[str] = None
    ) -> Any:
        """Finds an end user by the merchant's own customer id."""
        params = {
            "externalCustomerId": external_customer_id,
            "query": compact({"programId": program_id}),
        }
        return data_of(self._call("getEndUserByExternalId", params))

    def freeze(
        self,
        end_user_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Freezes the end user (optional ``reason``)."""
        params = {"endUserId": end_user_id}
        body = merge_request(request, fields)
        return data_of(self._call("freezeEndUser", params, body, idempotency_key))

    def get_balances(self, end_user_id: str) -> Any:
        return data_of(self._call("getBalances", {"endUserId": end_user_id}))

    def get_kyc_level(self, end_user_id: str) -> Any:
        return data_of(self._call("getKycLevel", {"endUserId": end_user_id}))

    def update_kyc_level(
        self,
        end_user_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Records the KYC level from your own verification (``sourceRef`` = your KYC session id)."""
        params = {"endUserId": end_user_id}
        body = merge_request(request, fields)
        return data_of(self._call("updateKycLevel", params, body, idempotency_key))

    def get_limits(self, end_user_id: str, **filters: Any) -> Any:
        """Limit usage per operation type; ``operationType`` and ``currency`` narrow the answer."""
        return data_of(self._call("getLimits", {"endUserId": end_user_id, "query": filters}))

    def create_wallet(
        self,
        end_user_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Adds a wallet to the end user (optional ``name``, ``currencies``)."""
        params = {"endUserId": end_user_id}
        body = merge_request(request, fields)
        return data_of(self._call("createWallet", params, body, idempotency_key))


class WalletAccounts(_Section):
    def create_account(
        self, wallet_id: str, currency: str, *, idempotency_key: Optional[str] = None
    ) -> Any:
        """Adds a currency account to a wallet."""
        params = {"walletId": wallet_id}
        body = {"currency": currency}
        return data_of(self._call("createWalletAccount", params, body, idempotency_key))

    def lookup(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        """Resolves a wallet number or phone to ``{exists, walletNo, maskedName}`` before a transfer."""
        return data_of(self._call("lookupWallet", None, merge_request(request, fields)))


class WalletDeposits(_Section):
    def list_instructions(self, end_user_id: str) -> Any:
        """Bank transfer details the end user pays into to top up."""
        return data_of(self._call("listDepositInstructions", {"endUserId": end_user_id}))

    def create_instruction(
        self, end_user_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Any:
        """``walletAccountId``, optional ``currency``."""
        params = {"endUserId": end_user_id}
        body = merge_request(request, fields)
        return data_of(self._call("createDepositInstruction", params, body))

    def simulate_inbound_credit(
        self, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Any:
        """Test only: books an incoming bank transfer as the bank rail would."""
        return data_of(self._call("simulateInboundCredit", None, merge_request(request, fields)))


class WalletCorporate(_Section):
    def create(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = merge_request(request, fields)
        return data_of(self._call("createCorporateAccount", None, body, idempotency_key))

    def list(self, **filters: Any) -> Page:
        """Filters: ``programId``, ``status``, ``limit``, ``cursor``."""
        return to_page(self._call("listCorporateAccounts", {"query": filters}))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def import_employees(
        self,
        corporate_account_id: str,
        rows: List[Mapping[str, Any]],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Imports up to 1000 employees at once; all or nothing (422 writes nothing).

        Each row: ``phone``, optional ``displayName``, ``externalCustomerId``, ``kycRef``.
        """
        params = {"corporateAccountId": corporate_account_id}
        body = {"rows": rows}
        return data_of(self._call("importCorporateEmployees", params, body, idempotency_key))

    def offboard_employees(
        self,
        corporate_account_id: str,
        rows: List[Mapping[str, Any]],
        *,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Each row: ``endUserId`` or ``externalCustomerId``."""
        params = {"corporateAccountId": corporate_account_id}
        body = compact({"rows": rows, "reason": reason})
        return data_of(self._call("offboardCorporateEmployees", params, body, idempotency_key))


class WalletFees(_Section):
    def quote(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        """The fee, tax and total charge an operation would cost."""
        return data_of(self._call("quoteFees", None, merge_request(request, fields)))


class WalletTransfers(_Section):
    """Money moves in two steps.

    ``initiate_*`` reserves the limit and returns ``{operationId,
    integrityHash, nonce, otpRequired, …}``; ``complete_*`` with the same
    ``integrityHash`` and ``nonce`` (and the OTP when ``otpRequired``) commits
    it. Quote first to show the fee; pass its ``scheduleVersionId`` to
    ``initiate_*`` to hold that fee.
    """

    def quote_w2w(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        """Quotes a wallet-to-wallet transfer."""
        return data_of(self._call("quoteW2W", None, merge_request(request, fields)))

    def initiate_w2w(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = merge_request(request, fields)
        return data_of(self._call("initiateW2W", None, body, idempotency_key))

    def complete_w2w(
        self,
        operation_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = with_operation_id(operation_id, merge_request(request, fields))
        params = {"operationId": operation_id}
        return data_of(self._call("completeW2W", params, body, idempotency_key))

    def quote_w2_iban(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        """Quotes a transfer to an IBAN."""
        return data_of(self._call("quoteW2Iban", None, merge_request(request, fields)))

    def initiate_w2_iban(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = merge_request(request, fields)
        return data_of(self._call("initiateW2Iban", None, body, idempotency_key))

    def complete_w2_iban(
        self,
        operation_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = with_operation_id(operation_id, merge_request(request, fields))
        params = {"operationId": operation_id}
        return data_of(self._call("completeW2Iban", params, body, idempotency_key))


class WalletWithdrawals(_Section):
    """Withdrawal to the end user's own bank account (the same two steps as transfers)."""

    def quote(self, request: Optional[Mapping[str, Any]] = None, **fields: Any) -> Any:
        return data_of(self._call("quoteBankWithdrawal", None, merge_request(request, fields)))

    def initiate(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = merge_request(request, fields)
        return data_of(self._call("initiateBankWithdrawal", None, body, idempotency_key))

    def complete(
        self,
        operation_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        body = with_operation_id(operation_id, merge_request(request, fields))
        params = {"operationId": operation_id}
        return data_of(self._call("completeBankWithdrawal", params, body, idempotency_key))

    def get(self, operation_id: str) -> Any:
        """``{operation, history}``."""
        return data_of(self._call("getWithdrawal", {"operationId": operation_id}))


class WalletOperations(_Section):
    def list(self, **filters: Any) -> Page:
        """Filters: ``endUserId``, ``walletAccountId``, ``status``, ``operationType``,
        ``destinationWalletAccountId``, ``limit``, ``cursor``."""
        return to_page(self._call("listOperations", {"query": filters}))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def get(self, operation_id: str) -> Any:
        """``{operation, history}``."""
        return data_of(self._call("getOperation", {"operationId": operation_id}))

    def get_receipt(self, operation_id: str) -> Any:
        return data_of(self._call("getOperationReceipt", {"operationId": operation_id}))


class WalletTopups(_Section):
    def start_card(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Starts a card top-up.

        Render ``checkoutFormContent`` (or follow ``redirectUrl`` /
        ``threeDsHtml``); the wallet is credited when the payment completes
        (``wallet.topup.completed``).
        """
        body = merge_request(request, fields)
        return data_of(self._call("startCardTopup", None, body, idempotency_key))

    def get(self, operation_id: str) -> Any:
        """``{operation, history}``."""
        return data_of(self._call("getTopup", {"operationId": operation_id}))

    def refund(
        self, operation_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Any:
        """Refunds a card top-up to the card.

        Four eyes: ``approverPrincipal`` is required and must differ from
        ``requesterPrincipal``; binding them to two real people is your
        approval flow's job.
        """
        params = {"operationId": operation_id}
        return data_of(self._call("refundTopup", params, merge_request(request, fields)))

    def agent(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Cash top-up through an agent of the program."""
        body = merge_request(request, fields)
        return data_of(self._call("agentTopup", None, body, idempotency_key))


class WalletPayments(_Section):
    """The end user pays the merchant.

    The creditor is the wallet terminal bound to the signing key
    (``WALLET_TERMINAL_*`` 403 without one); a ``businessAccountId`` in the
    body is refused.
    """

    def request(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Asks the buyer (by wallet number or phone) to pay; approve with :meth:`approve`."""
        body = merge_request(request, fields)
        return data_of(self._call("requestPayment", None, body, idempotency_key))

    def approve(
        self,
        operation_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        params = {"operationId": operation_id}
        body = merge_request(request, fields)
        return data_of(self._call("approvePayment", params, body, idempotency_key))

    def collect(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Collects with the payment code the buyer shows (customer-presented)."""
        body = merge_request(request, fields)
        return data_of(self._call("collectByCode", None, body, idempotency_key))

    def get(self, operation_id: str) -> Any:
        """``{operation, history}``."""
        return data_of(self._call("getPayment", {"operationId": operation_id}))

    def get_commission(self, business_account_id: str) -> Any:
        params = {"businessAccountId": business_account_id}
        return data_of(self._call("getBusinessCommission", params))


class WalletQr(_Section):
    def create(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """Static QR codes carry no amount; dynamic ones require it."""
        body = merge_request(request, fields)
        return data_of(self._call("createQr", None, body, idempotency_key))

    def list(self, **filters: Any) -> Page:
        """Filters: ``programId``, ``qrType``, ``status``, ``targetEndUserId``, ``limit``, ``cursor``."""
        return to_page(self._call("listQr", {"query": filters}))

    def iterate(self, **filters: Any) -> Iterator[Any]:
        return paginate(lambda page: self.list(**page), filters)

    def get(self, qr_id: str) -> Any:
        return data_of(self._call("getQr", {"qrId": qr_id}))

    def image(
        self, qr_id: str, *, format: Optional[str] = None, scale: Optional[int] = None
    ) -> BinaryResponse:
        """The QR as an image (``BinaryResponse``): ``format`` ``svg`` (default) or ``png``, ``scale`` 1–20."""
        if format is not None and format not in WalletQrImageFormat.ALL:
            raise ConfigurationError(
                f"QR image format must be one of {', '.join(WalletQrImageFormat.ALL)}."
            )
        if scale is not None and (
            isinstance(scale, bool)
            or not isinstance(scale, int)
            or not WALLET_QR_SCALE_MIN <= scale <= WALLET_QR_SCALE_MAX
        ):
            raise ConfigurationError(
                f"QR image scale must be an integer {WALLET_QR_SCALE_MIN}-{WALLET_QR_SCALE_MAX}."
            )
        query = compact({"format": format, "scale": scale})
        return self._call("getQrImage", {"qrId": qr_id, "query": query})

    def revoke(self, qr_id: str) -> Any:
        return data_of(self._call("revokeQr", {"qrId": qr_id}))

    def parse(self, payload: str) -> Any:
        """Decodes a scanned QR payload."""
        return data_of(self._call("parseQr", None, {"payload": payload}))


class WalletBulkPayouts(_Section):
    """Bulk payouts follow maker-checker.

    The approver must be a DIFFERENT key than the creator (the principal is
    the signing key id). Creating needs ``wallet:bulk:create``; submit,
    approve, process and retry-failed need ``wallet:bulk:approve`` — so the
    maker key holds both, the checker key holds ``wallet:bulk:approve``.
    """

    def create(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> Any:
        """``programId``, ``sourceWalletAccountId``, ``currency``, ``items`` (each ``targetType``,
        ``targetRef``, ``amount``, optional ``beneficiaryName``), optional ``reason``."""
        body = merge_request(request, fields)
        return data_of(self._call("createBulkPayout", None, body, idempotency_key))

    def list(self, **filters: Any) -> Page:
        """Filters: ``programId``, ``status``, ``limit``."""
        return to_page(self._call("listBulkPayouts", {"query": filters}))

    def get(self, batch_id: str) -> Any:
        return data_of(self._call("getBulkPayout", {"batchId": batch_id}))

    def list_items(self, batch_id: str, **filters: Any) -> Page:
        """Filters: ``status``, ``limit``."""
        return to_page(self._call("listBulkPayoutItems", {"batchId": batch_id, "query": filters}))

    def submit(self, batch_id: str) -> Any:
        return data_of(self._call("submitBulkPayout", {"batchId": batch_id}))

    def approve(self, batch_id: str, *, approve: bool = True, reason: Optional[str] = None) -> Any:
        """``approve=False`` declines the batch with ``reason``."""
        body = compact({"approve": approve, "reason": reason})
        return data_of(self._call("approveBulkPayout", {"batchId": batch_id}, body))

    def reject(self, batch_id: str, *, reason: Optional[str] = None) -> Any:
        body = compact({"reason": reason})
        return data_of(self._call("rejectBulkPayout", {"batchId": batch_id}, body))

    def process(self, batch_id: str) -> Any:
        return data_of(self._call("processBulkPayout", {"batchId": batch_id}))

    def retry_failed(self, batch_id: str) -> Any:
        return data_of(self._call("retryFailedBulkPayout", {"batchId": batch_id}))


# ── the caller ───────────────────────────────────────────────────────────────


def invoke(
    api: ApiClient,
    route_name: str,
    params: Optional[Mapping[str, Any]] = None,
    body: Optional[Mapping[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Any:
    """Sends one route of :data:`WALLET_ROUTES`, signed, after checking the call against it."""
    route = WALLET_ROUTES[route_name]
    params = params or {}
    path = fill_path(route["path"], params)
    query = pick_query(route_name, route, params["query"]) if "query" in params else {}
    has_body = route["method"] != "GET" and ("required" in route or "optional" in route)
    payload = check_body(route_name, route, body if body is not None else {}) if has_body else None
    key: Optional[str] = None
    if route["idempotencyKey"]:
        key = require_idempotency_key(route_name, idempotency_key)
    elif idempotency_key is not None:
        raise ConfigurationError(f"{route_name} does not take an Idempotency-Key.")
    if route.get("binary"):
        return api.request_binary(
            route["method"], path, query=query or None, step_up=True, accept=_IMAGE_ACCEPT
        )
    return api.request(
        route["method"], path, payload, query=query or None, step_up=True, idempotency_key=key
    )


def check_body(route_name: str, route: Mapping[str, Any], body: Any) -> Dict[str, Any]:
    """The wire body: known fields only, required fields present, amounts as digit strings."""
    required = route.get("required", ())
    plain = _fields(route_name, body, required, route.get("optional", ()))
    for field in WALLET_AMOUNT_FIELDS:
        if field in plain:
            plain[field] = require_amount(f"{route_name}.{field}", plain[field])
    nested = WALLET_NESTED_FIELDS.get(route_name)
    if nested is not None:
        list_field = nested["field"]
        plain[list_field] = _rows(f"{route_name}.{list_field}", nested, plain.get(list_field))
    return plain


def _fields(label: str, value: Any, required: Any, optional: Any) -> Dict[str, Any]:
    plain = compact(wire_fields(value, label))
    allowed = (*required, *optional)
    unknown = [key for key in plain if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"{label} does not accept {', '.join(unknown)} (the gateway rejects unknown fields)."
        )
    missing = [key for key in required if plain.get(key) is None or plain.get(key) == ""]
    if missing:
        raise ConfigurationError(f"{label} requires {', '.join(missing)}.")
    return plain


def _rows(label: str, spec: Mapping[str, Any], rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, (list, tuple)) or len(rows) == 0:
        raise ConfigurationError(f"{label} must be a non-empty list.")
    checked = []
    for index, row in enumerate(rows):
        plain = _fields(f"{label}[{index}]", row, spec["required"], spec["optional"])
        if "amount" in plain:
            plain["amount"] = require_amount(f"{label}[{index}].amount", plain["amount"])
        checked.append(plain)
    return checked


def pick_query(route_name: str, route: Mapping[str, Any], filters: Any) -> Dict[str, Any]:
    allowed = route.get("query", ())
    given = compact(wire_fields(filters, f"{route_name} filters"))
    unknown = [key for key in given if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"{route_name} does not accept the filter(s) {', '.join(unknown)}."
        )
    return {key: given[key] for key in allowed if key in given}


def require_amount(label: str, value: Any) -> str:
    """Minor units only, as a canonical digit string; a number or a decimal is refused."""
    if not isinstance(value, str) or not _AMOUNT.match(value):
        raise ConfigurationError(
            f"{label} must be minor units as a digit string (e.g. \"12550\" for 125.50)."
        )
    return amount_minor(value)


def require_idempotency_key(route_name: str, key: Any) -> str:
    value = key.strip() if isinstance(key, str) else ""
    if not value:
        raise ConfigurationError(
            f"A stable Idempotency-Key is required for {route_name}. "
            "Reuse the same key when retrying the same operation."
        )
    if len(value) > WALLET_IDEMPOTENCY_KEY_MAX or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ConfigurationError(
            f"Idempotency-Key must be 1-{WALLET_IDEMPOTENCY_KEY_MAX} printable ASCII characters."
        )
    return value


def with_operation_id(operation_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The complete DTOs require ``operationId`` in the body as well; the path wins on the server."""
    given = body.get("operationId", body.get("operation_id"))
    if given is not None and given != operation_id:
        raise ConfigurationError("operationId in the body must match the operation completed.")
    out = {key: value for key, value in body.items() if key not in ("operationId", "operation_id")}
    out["operationId"] = operation_id
    return out


def to_page(response: Any) -> Page:
    """Wallet lists answer ``{items, nextCursor}`` (operations: ``{operations, nextCursor}``,
    with ``items`` and ``pageInfo`` added by the gateway)."""
    payload = data_of(response)
    payload = payload if payload is not None else {}
    page_info = page_info_of(response) if isinstance(response, Mapping) else {}
    if isinstance(payload, list):
        items: Any = payload
        next_cursor = page_info.get("nextCursor")
    else:
        items = _first_list(payload) if isinstance(payload, Mapping) else []
        next_cursor = (
            payload.get("nextCursor") if isinstance(payload, Mapping) else None
        ) or page_info.get("nextCursor")
    has_more = page_info.get("hasMore")
    return cursor_page(
        response, items, next_cursor, has_more if isinstance(has_more, bool) else None
    )


def _first_list(payload: Mapping[str, Any]) -> Any:
    if isinstance(payload.get("items"), list):
        return payload["items"]
    for value in payload.values():
        if isinstance(value, list):
            return value
    return []
