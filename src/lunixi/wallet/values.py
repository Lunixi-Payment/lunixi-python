"""Wallet — the merchant (server-to-server) API surface, ``/api/v1/wallet/*``.

:data:`WALLET_ROUTES` is the single description of every route the client
calls: the HTTP method, the path template, whether the gateway requires an
``Idempotency-Key``, and the body / query fields the gateway DTO accepts. It is
the same table as the Node SDK's ``WALLET_ROUTES`` and the shared catalog
(``contracts/products/wallet.json``); the parity test compares them field by
field. The client checks every call against it before sending (the gateway
runs with ``forbidNonWhitelisted``, so an unknown body key is a 400).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .._routes import freeze_routes

__all__ = [
    "WalletAccountType",
    "WalletEndUserStatus",
    "WalletKycLevel",
    "WalletOtpChannel",
    "WalletQrType",
    "WalletQrImageFormat",
    "WalletBulkTargetType",
    "WalletCorporateAccountStatus",
    "WALLET_ROUTES",
    "WALLET_AMOUNT_FIELDS",
    "WALLET_NESTED_FIELDS",
    "WALLET_IDEMPOTENCY_KEY_MAX",
    "WALLET_QR_SCALE_MIN",
    "WALLET_QR_SCALE_MAX",
    "AMOUNT_PATTERN",
]


class WalletAccountType:
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"
    ALL = (PERSONAL, BUSINESS)


class WalletEndUserStatus:
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    ALL = (ACTIVE, FROZEN, CLOSED)


class WalletKycLevel:
    NONE = "NONE"
    LOW = "LOW"
    SUBSTANTIAL = "SUBSTANTIAL"
    HIGH = "HIGH"
    ALL = (NONE, LOW, SUBSTANTIAL, HIGH)


class WalletOtpChannel:
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
    ALL = (EMAIL, SMS, PUSH)


class WalletQrType:
    P2P_STATIC = "P2P_STATIC"
    P2P_DYNAMIC = "P2P_DYNAMIC"
    MERCHANT_STATIC = "MERCHANT_STATIC"
    MERCHANT_DYNAMIC = "MERCHANT_DYNAMIC"
    ALL = (P2P_STATIC, P2P_DYNAMIC, MERCHANT_STATIC, MERCHANT_DYNAMIC)


class WalletQrImageFormat:
    SVG = "svg"
    PNG = "png"
    ALL = (SVG, PNG)


class WalletBulkTargetType:
    WALLET = "WALLET"
    IBAN = "IBAN"
    ALL = (WALLET, IBAN)


class WalletCorporateAccountStatus:
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    ALL = (ACTIVE, ARCHIVED)


#: Minor units as a digit string: ``"12550"`` is 125.50 TRY. Never a float or a number.
AMOUNT_PATTERN = r"^\d{1,18}$"

#: The gateway trims the header and accepts 1–128 characters.
WALLET_IDEMPOTENCY_KEY_MAX = 128

#: ``scale`` of :meth:`~lunixi.wallet.client.WalletQr.image`.
WALLET_QR_SCALE_MIN = 1
WALLET_QR_SCALE_MAX = 20

_PAGE_QUERY = ["limit", "cursor"]
_MOVE_INITIATE = ["scheduleVersionId", "otpDestination", "otpChannel", "locale"]
_COMPLETE_REQUIRED = ["endUserId", "operationId", "integrityHash", "nonce"]
_COMPLETE_OPTIONAL = ["otpCode", "trustedActionToken"]
_W2W_REQUIRED = ["endUserId", "sourceWalletAccountId", "amount", "currency"]
_W2W_OPTIONAL = ["destinationWalletNo", "destinationPhone", "paymentPurpose"]
_IBAN_REQUIRED = [
    "endUserId",
    "sourceWalletAccountId",
    "beneficiaryName",
    "iban",
    "amount",
    "currency",
]
_IBAN_OPTIONAL = ["bankCode", "paymentPurpose"]

#: Every route the wallet client calls (Node ``WALLET_ROUTES``).
WALLET_ROUTES = freeze_routes(
    {
        "ping": {"method": "GET", "path": "/api/v1/wallet/ping", "idempotencyKey": False},
        # Programs
        "listMyPrograms": {
            "method": "GET",
            "path": "/api/v1/wallet/programs/me",
            "idempotencyKey": False,
        },
        "setCollectionAnchor": {
            "method": "PUT",
            "path": "/api/v1/wallet/programs/:programId/collection-anchor",
            "idempotencyKey": False,
            "optional": ["collectionEndUserId", "reason", "expectedVersion"],
        },
        # End users
        "createEndUser": {
            "method": "POST",
            "path": "/api/v1/wallet/end-users",
            "idempotencyKey": True,
            "required": ["programId", "accountType", "phone"],
            "optional": [
                "externalCustomerId",
                "kycRef",
                "kycLevelCache",
                "displayName",
                "corporateAccountId",
                "defaultCurrency",
            ],
        },
        "listEndUsers": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users",
            "idempotencyKey": False,
            "query": [
                "programId",
                "accountType",
                "status",
                "corporateAccountId",
                "merchantCategoryState",
                *_PAGE_QUERY,
            ],
        },
        "getEndUserByExternalId": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/by-external/:externalCustomerId",
            "idempotencyKey": False,
            "query": ["programId"],
        },
        "getEndUser": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/:endUserId",
            "idempotencyKey": False,
        },
        "freezeEndUser": {
            "method": "POST",
            "path": "/api/v1/wallet/end-users/:endUserId/freeze",
            "idempotencyKey": True,
            "optional": ["reason"],
        },
        "getBalances": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/:endUserId/balances",
            "idempotencyKey": False,
        },
        "getKycLevel": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/:endUserId/kyc-level",
            "idempotencyKey": False,
        },
        "updateKycLevel": {
            "method": "PUT",
            "path": "/api/v1/wallet/end-users/:endUserId/kyc-level",
            "idempotencyKey": True,
            "required": ["kycLevel", "sourceRef"],
            "optional": [
                "externalCustomerId",
                "programId",
                "reason",
                "effectiveAt",
                "expectedCurrentLevel",
            ],
        },
        "getLimits": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/:endUserId/limits",
            "idempotencyKey": False,
            "query": ["operationType", "currency"],
        },
        "createWallet": {
            "method": "POST",
            "path": "/api/v1/wallet/end-users/:endUserId/wallets",
            "idempotencyKey": True,
            "optional": ["name", "currencies"],
        },
        # Wallets and accounts
        "createWalletAccount": {
            "method": "POST",
            "path": "/api/v1/wallet/wallets/:walletId/accounts",
            "idempotencyKey": True,
            "required": ["currency"],
        },
        "lookupWallet": {
            "method": "POST",
            "path": "/api/v1/wallet/wallets/lookup",
            "idempotencyKey": False,
            "optional": ["programId", "phone", "walletNo"],
        },
        # Deposits (bank transfer in)
        "listDepositInstructions": {
            "method": "GET",
            "path": "/api/v1/wallet/end-users/:endUserId/deposit-instructions",
            "idempotencyKey": False,
        },
        "createDepositInstruction": {
            "method": "POST",
            "path": "/api/v1/wallet/end-users/:endUserId/deposit-instructions",
            "idempotencyKey": False,
            "required": ["walletAccountId"],
            "optional": ["currency"],
        },
        "simulateInboundCredit": {
            "method": "POST",
            "path": "/api/v1/wallet/bank-integrations/inbound-credits",
            "idempotencyKey": False,
            "required": ["programId", "railId", "amount", "currency", "rawReference"],
            "optional": ["senderName", "senderIban", "creditedIban", "receiptNumber"],
        },
        # Corporate accounts
        "createCorporateAccount": {
            "method": "POST",
            "path": "/api/v1/wallet/corporate-accounts",
            "idempotencyKey": True,
            "required": ["programId", "code", "name", "ownerEndUserId"],
            "optional": ["fundingCurrency"],
        },
        "listCorporateAccounts": {
            "method": "GET",
            "path": "/api/v1/wallet/corporate-accounts",
            "idempotencyKey": False,
            "query": ["programId", "status", *_PAGE_QUERY],
        },
        "importCorporateEmployees": {
            "method": "POST",
            "path": "/api/v1/wallet/corporate-accounts/:corporateAccountId/employees/import",
            "idempotencyKey": True,
            "required": ["rows"],
        },
        "offboardCorporateEmployees": {
            "method": "POST",
            "path": "/api/v1/wallet/corporate-accounts/:corporateAccountId/employees/offboard",
            "idempotencyKey": True,
            "required": ["rows"],
            "optional": ["reason"],
        },
        # Fees
        "quoteFees": {
            "method": "POST",
            "path": "/api/v1/wallet/fees/quote",
            "idempotencyKey": False,
            "required": ["programId", "operationType", "currency", "amount"],
            "optional": ["at"],
        },
        # Wallet-to-wallet transfers
        "quoteW2W": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2w/quote",
            "idempotencyKey": False,
            "required": _W2W_REQUIRED,
            "optional": _W2W_OPTIONAL,
        },
        "initiateW2W": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2w",
            "idempotencyKey": True,
            "required": _W2W_REQUIRED,
            "optional": [*_W2W_OPTIONAL, *_MOVE_INITIATE],
        },
        "completeW2W": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2w/:operationId/complete",
            "idempotencyKey": True,
            "required": _COMPLETE_REQUIRED,
            "optional": _COMPLETE_OPTIONAL,
        },
        # Transfers to an IBAN
        "quoteW2Iban": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2iban/quote",
            "idempotencyKey": False,
            "required": _IBAN_REQUIRED,
            "optional": _IBAN_OPTIONAL,
        },
        "initiateW2Iban": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2iban",
            "idempotencyKey": True,
            "required": _IBAN_REQUIRED,
            "optional": [*_IBAN_OPTIONAL, *_MOVE_INITIATE],
        },
        "completeW2Iban": {
            "method": "POST",
            "path": "/api/v1/wallet/transfers/w2iban/:operationId/complete",
            "idempotencyKey": True,
            "required": _COMPLETE_REQUIRED,
            "optional": _COMPLETE_OPTIONAL,
        },
        # Withdrawals to the end user's own bank account
        "quoteBankWithdrawal": {
            "method": "POST",
            "path": "/api/v1/wallet/withdrawals/bank/quote",
            "idempotencyKey": False,
            "required": _IBAN_REQUIRED,
            "optional": _IBAN_OPTIONAL,
        },
        "initiateBankWithdrawal": {
            "method": "POST",
            "path": "/api/v1/wallet/withdrawals/bank",
            "idempotencyKey": True,
            "required": _IBAN_REQUIRED,
            "optional": [*_IBAN_OPTIONAL, *_MOVE_INITIATE],
        },
        "completeBankWithdrawal": {
            "method": "POST",
            "path": "/api/v1/wallet/withdrawals/bank/:operationId/complete",
            "idempotencyKey": True,
            "required": _COMPLETE_REQUIRED,
            "optional": _COMPLETE_OPTIONAL,
        },
        "getWithdrawal": {
            "method": "GET",
            "path": "/api/v1/wallet/withdrawals/:operationId",
            "idempotencyKey": False,
        },
        # Operations
        "listOperations": {
            "method": "GET",
            "path": "/api/v1/wallet/operations",
            "idempotencyKey": False,
            "query": [
                "endUserId",
                "walletAccountId",
                "status",
                "operationType",
                "destinationWalletAccountId",
                *_PAGE_QUERY,
            ],
        },
        "getOperation": {
            "method": "GET",
            "path": "/api/v1/wallet/operations/:operationId",
            "idempotencyKey": False,
        },
        "getOperationReceipt": {
            "method": "GET",
            "path": "/api/v1/wallet/operations/:operationId/receipt",
            "idempotencyKey": False,
        },
        # Top-ups
        "startCardTopup": {
            "method": "POST",
            "path": "/api/v1/wallet/topups/card",
            "idempotencyKey": True,
            "required": ["creditWalletAccountId", "amount", "currency"],
            "optional": [
                "fundingMerchantId",
                "savedCardUserKey",
                "savedCardToken",
                "savedConsumerToken",
                "savedPublicCardStorageToken",
                "returnUrl",
            ],
        },
        "getTopup": {
            "method": "GET",
            "path": "/api/v1/wallet/topups/:operationId",
            "idempotencyKey": False,
        },
        "refundTopup": {
            "method": "POST",
            "path": "/api/v1/wallet/topups/:operationId/refund",
            "idempotencyKey": False,
            # The gateway DTO marks approverPrincipal optional, but the wallet
            # service refuses the refund without it: it is required in practice.
            "required": ["reason", "requesterPrincipal", "approverPrincipal"],
        },
        "agentTopup": {
            "method": "POST",
            "path": "/api/v1/wallet/agent-topups",
            "idempotencyKey": True,
            "required": ["agentId", "creditWalletAccountId", "amount", "currency"],
        },
        # Payments to the merchant (pay by wallet, payment code)
        "requestPayment": {
            "method": "POST",
            "path": "/api/v1/wallet/payments/buy",
            "idempotencyKey": True,
            "required": ["amount", "currency", "paymentPurpose"],
            "optional": [
                "buyerWalletNo",
                "buyerPhone",
                "orderRef",
                "cashierRef",
                "otpDestination",
                "otpChannel",
                "locale",
            ],
        },
        "approvePayment": {
            "method": "POST",
            "path": "/api/v1/wallet/payments/:operationId/approve",
            "idempotencyKey": True,
            "required": ["buyerEndUserId", "integrityHash", "nonce"],
            "optional": _COMPLETE_OPTIONAL,
        },
        "collectByCode": {
            "method": "POST",
            "path": "/api/v1/wallet/collect",
            "idempotencyKey": True,
            "required": ["code", "amount", "currency"],
            "optional": ["orderRef", "paymentPurpose", "locale"],
        },
        "getPayment": {
            "method": "GET",
            "path": "/api/v1/wallet/payments/:operationId",
            "idempotencyKey": False,
        },
        "getBusinessCommission": {
            "method": "GET",
            "path": "/api/v1/wallet/business-accounts/:businessAccountId/commission",
            "idempotencyKey": False,
        },
        # QR codes
        "createQr": {
            "method": "POST",
            "path": "/api/v1/wallet/qr",
            "idempotencyKey": True,
            "required": ["qrType", "currency"],
            "optional": [
                "targetEndUserId",
                "targetExternalCustomerId",
                "programId",
                "amount",
                "expiresInSeconds",
                "metadata",
            ],
        },
        "listQr": {
            "method": "GET",
            "path": "/api/v1/wallet/qr",
            "idempotencyKey": False,
            "query": ["programId", "qrType", "status", "targetEndUserId", *_PAGE_QUERY],
        },
        "getQr": {"method": "GET", "path": "/api/v1/wallet/qr/:qrId", "idempotencyKey": False},
        "getQrImage": {
            "method": "GET",
            "path": "/api/v1/wallet/qr/:qrId/image",
            "idempotencyKey": False,
            "binary": True,
            "query": ["format", "scale"],
        },
        "revokeQr": {
            "method": "POST",
            "path": "/api/v1/wallet/qr/:qrId/revoke",
            "idempotencyKey": False,
        },
        "parseQr": {
            "method": "POST",
            "path": "/api/v1/wallet/qr/parse",
            "idempotencyKey": False,
            "required": ["payload"],
        },
        # Bulk payouts
        "createBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts",
            "idempotencyKey": True,
            "required": ["programId", "sourceWalletAccountId", "currency", "items"],
            "optional": ["reason"],
        },
        "listBulkPayouts": {
            "method": "GET",
            "path": "/api/v1/wallet/bulk-payouts",
            "idempotencyKey": False,
            "query": ["programId", "status", "limit"],
        },
        "getBulkPayout": {
            "method": "GET",
            "path": "/api/v1/wallet/bulk-payouts/:batchId",
            "idempotencyKey": False,
        },
        "listBulkPayoutItems": {
            "method": "GET",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/items",
            "idempotencyKey": False,
            "query": ["status", "limit"],
        },
        "submitBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/submit",
            "idempotencyKey": False,
        },
        "approveBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/approve",
            "idempotencyKey": False,
            "required": ["approve"],
            "optional": ["reason"],
        },
        "rejectBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/reject",
            "idempotencyKey": False,
            "optional": ["reason"],
        },
        "processBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/process",
            "idempotencyKey": False,
        },
        "retryFailedBulkPayout": {
            "method": "POST",
            "path": "/api/v1/wallet/bulk-payouts/:batchId/retry-failed",
            "idempotencyKey": False,
        },
    }
)

#: Body fields that carry a minor-unit amount string.
WALLET_AMOUNT_FIELDS = ("amount",)

#: Fields of the nested rows / items the gateway validates element by element.
WALLET_NESTED_FIELDS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "importCorporateEmployees": MappingProxyType(
            {
                "field": "rows",
                "required": ("phone",),
                "optional": ("displayName", "externalCustomerId", "kycRef"),
            }
        ),
        "offboardCorporateEmployees": MappingProxyType(
            {"field": "rows", "required": (), "optional": ("endUserId", "externalCustomerId")}
        ),
        "createBulkPayout": MappingProxyType(
            {
                "field": "items",
                "required": ("targetType", "targetRef", "amount"),
                "optional": ("beneficiaryName",),
            }
        ),
    }
)
