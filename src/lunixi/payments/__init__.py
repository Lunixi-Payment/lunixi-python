"""Merchant payment APIs. Card data belongs in the official browser form."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from ..api_client import ApiClient, BinaryResponse
from ..errors import ApiError, ConfigurationError
from ..http.transport import encode_path_segment
from ..validation import amount_minor, currency_code, header_value, identifier
from .bank_transfer_values import (
    BANK_TRANSFER_EXCEPTION_ENVIRONMENTS,
    BANK_TRANSFER_EXCEPTION_LIMIT_MAX,
    BANK_TRANSFER_OTHER_BANKS_CODE,
    BankTransferInstruction,
    PaymentBankTransferEvents,
    PaymentBankTransferExceptionKind,
    PaymentBankTransferExceptionStatus,
    bank_transfer_exception_path,
    bank_transfer_exceptions_query,
)
from .card_requests import (
    InstallmentOptionsRequest,
    StoreCardRequest,
    installment_options_body,
    require_bin_or_pan,
)
from .direct_method_payment import DirectMethodPaymentRequest, assert_direct_method_payment_payload
from .enabled_installments import (
    ENABLED_INSTALLMENTS_MAX,
    ENABLED_INSTALLMENTS_MIN,
    validate_enabled_installments,
)
from .marketplace_intent import (
    MARKETPLACE_SELLER_FIELDS,
    MultiSellerPolicy,
    assert_marketplace_intent_payload,
    marketplace_intent_body,
)
from .payment_method_values import (
    CARD_ONLY_FIELDS,
    DIRECT_METHOD_PAYMENT_FIELDS,
    METHOD_BLOCK_FIELDS,
    PAYMENT_ACTION_CONFIRM_FIELDS,
    PAYMENT_METHOD_ALIASES,
    SHOPPING_LOAN_MAX_BASKET_ITEMS,
    MethodInputFieldType,
    PaymentActionType,
    PaymentMethod,
    ProviderSelection,
    ProviderSelectionMode,
    block_name_of,
    normalize_payment_method,
    require_method_fields,
)
from .product_category import ProductCategory
from .promissory_note_values import (
    PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS,
    PromissoryNoteCancelErrorCode,
    PromissoryNoteCancelResult,
    PromissoryNoteDocumentLocale,
    PromissoryNoteDocumentType,
    PromissoryNoteEvents,
    PromissoryNoteStatus,
    require_document_locale,
    require_serial_numbers,
)
from .split_payment_request import SplitPaymentRequest
from .split_payment_values import (
    LIST_SPLIT_PAYMENTS_FILTERS,
    SPLIT_IDEMPOTENCY_KEY_MAX_LENGTH,
    SPLIT_LEG_BLOCK_FIELDS,
    SPLIT_LEG_EVENTS_SUBSCRIPTION,
    SPLIT_PAYMENT_FIELDS,
    SPLIT_PAYMENT_IN_PROGRESS_STATUSES,
    SPLIT_PAYMENT_LEG_FIELDS,
    SplitPaymentEvents,
    SplitPaymentStatus,
    SplitPendingStep,
    assert_split_payment_payload,
    is_running_split_response,
    list_split_payments_query,
)

__all__ = [
    "CreateIntent",
    "IntentResult",
    "PaymentsClient",
    "ProductCategory",
    "ENABLED_INSTALLMENTS_MIN",
    "ENABLED_INSTALLMENTS_MAX",
    "validate_amount_body",
    "validate_enabled_installments",
    "DirectMethodPaymentRequest",
    "assert_direct_method_payment_payload",
    "SplitPaymentRequest",
    "InstallmentOptionsRequest",
    "StoreCardRequest",
    "MultiSellerPolicy",
    "MARKETPLACE_SELLER_FIELDS",
    "assert_marketplace_intent_payload",
    "PaymentMethod",
    "PAYMENT_METHOD_ALIASES",
    "PaymentActionType",
    "ProviderSelection",
    "ProviderSelectionMode",
    "MethodInputFieldType",
    "DIRECT_METHOD_PAYMENT_FIELDS",
    "METHOD_BLOCK_FIELDS",
    "CARD_ONLY_FIELDS",
    "PAYMENT_ACTION_CONFIRM_FIELDS",
    "SHOPPING_LOAN_MAX_BASKET_ITEMS",
    "normalize_payment_method",
    "block_name_of",
    "BANK_TRANSFER_OTHER_BANKS_CODE",
    "BANK_TRANSFER_EXCEPTION_LIMIT_MAX",
    "BANK_TRANSFER_EXCEPTION_ENVIRONMENTS",
    "PaymentBankTransferExceptionKind",
    "PaymentBankTransferExceptionStatus",
    "PaymentBankTransferEvents",
    "BankTransferInstruction",
    "PROMISSORY_NOTE_MAX_SCHEDULE_ITEMS",
    "PromissoryNoteStatus",
    "PromissoryNoteDocumentType",
    "PromissoryNoteCancelResult",
    "PromissoryNoteCancelErrorCode",
    "PromissoryNoteDocumentLocale",
    "PromissoryNoteEvents",
    "SplitPaymentStatus",
    "SPLIT_PAYMENT_IN_PROGRESS_STATUSES",
    "SplitPendingStep",
    "SplitPaymentEvents",
    "SPLIT_LEG_EVENTS_SUBSCRIPTION",
    "SPLIT_PAYMENT_FIELDS",
    "SPLIT_LEG_BLOCK_FIELDS",
    "SPLIT_PAYMENT_LEG_FIELDS",
    "LIST_SPLIT_PAYMENTS_FILTERS",
    "SPLIT_IDEMPOTENCY_KEY_MAX_LENGTH",
]

_BASE = "/api/v1/payments"
_BIN = "/api/v1/bin"
_PDF_ACCEPT = "application/pdf, application/json"
_OTP = re.compile(r"[0-9]{1,16}")


class _OmittedAmount:
    """Private marker: a missing argument is distinct from explicit None."""


_OMITTED_AMOUNT = _OmittedAmount()


def _key(value: str) -> str:
    return header_value(value, "idempotency_key")


def _required_key(value: Any, operation: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(
            f"A stable idempotency_key is required for {operation}. Reuse the same key when "
            "retrying the same operation."
        )
    return _key(value)


def _stored_card_path(stored_card_token: Any) -> str:
    source = "the storedCardToken from store_card() or list_stored_cards()"
    return f"{_BASE}/cards/{_segment(stored_card_token, 'stored_card_token', source)}"


def _segment(value: Any, name: str, source: str) -> str:
    """One caller-supplied path segment: non-empty, then percent-encoded."""
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{name} is required ({source}).")
    return encode_path_segment(value)


def _action_path(payment_id: Any, action_id: Any, operation: str) -> str:
    source = "from the payment response: data.paymentId and data.action.id"
    return (
        f"{_BASE}/{_segment(payment_id, 'payment_id', source)}"
        f"/actions/{_segment(action_id, 'action_id', source)}/{operation}"
    )


def _promissory_notes_path(payment_id: Any) -> str:
    source = "data.paymentId of the promissory-note payment"
    return f"{_BASE}/{_segment(payment_id, 'payment_id', source)}/promissory-notes"


def _confirm_body(
    otp: Optional[str], consent_accepted: Optional[bool], fields: Optional[Mapping[str, Any]]
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if otp is not None:
        if not isinstance(otp, str) or _OTP.fullmatch(otp) is None:
            raise ConfigurationError(
                "otp must be the code the buyer entered, as a string of digits."
            )
        body["otp"] = otp
    if consent_accepted is not None:
        if not isinstance(consent_accepted, bool):
            raise ConfigurationError(
                f"consent_accepted must be a boolean; got {consent_accepted!r}."
            )
        body["consentAccepted"] = consent_accepted
    if fields is not None:
        body["fields"] = require_method_fields(fields, "fields")
    if not body:
        raise ConfigurationError("confirm_payment_action needs otp, consent_accepted or fields.")
    return body


def _split_key(value: Any, operation: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(
            f"A stable idempotency_key is required for {operation}. Reuse the same key when "
            "retrying, and to continue the same split payment after a step."
        )
    return header_value(value, "idempotency_key", SPLIT_IDEMPOTENCY_KEY_MAX_LENGTH)


def validate_amount_body(body: Mapping[str, Any]) -> None:
    if "price" in body or "paidPrice" in body:
        raise ConfigurationError(
            "Removed amount fields are not accepted; send amount in integer minor units."
        )
    amount_minor(body.get("amount"))


@dataclass(frozen=True)
class CreateIntent:
    """Body of ``POST /api/v1/payments/intents``.

    ``enabled_installments`` lists the installment counts the hosted form may
    offer for this payment, e.g. ``[1, 2, 3]``; ``[1]`` allows a single payment
    only. The form shows only the counts also allowed by your panel settings,
    the card and the platform maximum. ``None`` means no restriction. Integers
    1–36, no duplicates, 1 included; sent as ``enabledInstallments`` in
    ascending order.
    """

    amount: str
    currency: str
    order_id: str
    callback_url: Optional[str] = None
    preauth: bool = False
    locale: str = "en"
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    enabled_installments: Optional[list[int]] = None

    def to_dict(self) -> dict[str, Any]:
        amount_minor(self.amount)
        currency_code(self.currency)
        if (
            not isinstance(self.order_id, str)
            or not 1 <= len(self.order_id) <= 128
            or any(ord(c) < 32 for c in self.order_id)
        ):
            raise ConfigurationError("A persisted order_id of 1–128 characters is required.")
        if not isinstance(self.preauth, bool) or self.locale not in ("en", "tr"):
            raise ConfigurationError("preauth must be boolean and locale en or tr.")
        body = {
            "amount": self.amount,
            "currency": self.currency,
            "orderId": self.order_id,
            "preauth": self.preauth,
            "locale": self.locale,
            "metadata": dict(self.metadata),
        }
        if self.callback_url is not None:
            u = urlsplit(self.callback_url)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.username is not None
                or u.password is not None
                or "#" in self.callback_url
                or any(ord(c) <= 32 for c in self.callback_url)
            ):
                raise ConfigurationError("callback_url must be a trusted HTTPS URL.")
            body["callbackUrl"] = self.callback_url
        if self.enabled_installments is not None:
            body["enabledInstallments"] = validate_enabled_installments(self.enabled_installments)
        return body


@dataclass(frozen=True)
class IntentResult:
    payment_id: str
    token: str = field(repr=False)
    payment_page_url: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.payment_page_url != "":
            self._validated_page_url(self.payment_page_url)

    @staticmethod
    def _validated_page_url(value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"https://pay\.lunixi\.com/payment/[A-Za-z0-9_.~-]{16,4096}", value)
            is None
        ):
            raise ApiError("The gateway returned an invalid paymentPageUrl.")
        return value

    @classmethod
    def from_response(cls, response: Mapping[str, Any]) -> IntentResult:
        value = response.get("data", response)
        if not isinstance(value, dict):
            raise ApiError("Intent response is uncertain.")
        payment = value.get("paymentId", value.get("intentId"))
        if "paymentId" in value and "intentId" in value and value["paymentId"] != value["intentId"]:
            raise ApiError("Intent response contains conflicting identities.")
        if (
            not isinstance(payment, str)
            or not isinstance(value.get("token"), str)
            or not value["token"]
            or len(value["token"]) > 8192
        ):
            raise ApiError("Intent response is uncertain.")
        identifier(payment)
        return cls(payment, value["token"], value.get("paymentPageUrl", ""))

    @property
    def hosted_url(self) -> str:
        if not self.payment_page_url:
            raise ApiError("The gateway did not return paymentPageUrl; reconcile the attempt.")
        return self._validated_page_url(self.payment_page_url)

    def browser_config(self) -> dict[str, Any]:
        return {
            "type": "payment",
            "target": "lunixi-checkout-form",
            "options": {"token": self.token},
        }


class PaymentsClient:
    """Stable-key payment helpers; responses remain full gateway envelopes."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def create_intent(self, request: CreateIntent, *, idempotency_key: str) -> IntentResult:
        return IntentResult.from_response(
            self._api.request(
                "POST",
                _BASE + "/intents",
                request.to_dict(),
                step_up=True,
                idempotency_key=_key(idempotency_key),
            )
        )

    def create_marketplace_intent(
        self,
        request: CreateIntent | Mapping[str, Any],
        *,
        sellers: Optional[Sequence[Mapping[str, Any]]] = None,
        multi_seller_policy: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """A hosted checkout split by seller (``POST /payments/marketplace/intents``, signed).

        The body is the intent body plus ``sellers`` (``[{"subDealerId",
        "amountMinor", "scenario"?}]``, ``amountMinor`` a canonical minor-unit
        string) and ``multi_seller_policy`` (:class:`MultiSellerPolicy`). The
        sellers' ``amountMinor`` values must add up to ``amount``; any other
        total raises :class:`~lunixi.errors.ConfigurationError` before sending.
        Pass a :class:`CreateIntent` with ``sellers=``, or a raw body mapping
        that carries them. Reuse the same ``idempotency_key`` when retrying.
        Returns the full envelope (``data.token`` opens the hosted form).
        """
        if isinstance(request, CreateIntent):
            if sellers is None:
                raise ConfigurationError("create_marketplace_intent needs sellers=.")
            intent_body = request.to_dict()
        elif isinstance(request, Mapping):
            intent_body = dict(request)
        else:
            raise ConfigurationError(
                "create_marketplace_intent takes a CreateIntent or a body mapping."
            )
        body = marketplace_intent_body(intent_body, sellers, multi_seller_policy)
        return self._api.request(
            "POST",
            _BASE + "/marketplace/intents",
            body,
            step_up=True,
            idempotency_key=None if idempotency_key is None else _key(idempotency_key),
        )

    def get(self, payment_id: str) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/" + identifier(payment_id))

    def list(self, **filters: Any) -> dict[str, Any]:
        return self._api.request("GET", _BASE, query=filters)

    def capture(
        self,
        payment_id: str,
        amount: str | _OmittedAmount = _OMITTED_AMOUNT,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._api.request(
            "POST",
            _BASE + "/" + identifier(payment_id) + "/capture",
            ({} if amount is _OMITTED_AMOUNT else {"amount": amount_minor(amount)}),
            step_up=True,
            idempotency_key=_key(idempotency_key),
        )

    def refund(
        self,
        payment_id: str,
        amount: str | _OmittedAmount = _OMITTED_AMOUNT,
        *,
        idempotency_key: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._refund(
            _BASE + "/" + identifier(payment_id) + "/refund", amount, idempotency_key, reason
        )

    def void(self, payment_id: str, *, idempotency_key: str) -> dict[str, Any]:
        return self._api.request(
            "POST",
            _BASE + "/" + identifier(payment_id) + "/void",
            step_up=True,
            idempotency_key=_key(idempotency_key),
        )

    def methods(self, payment_method: Optional[str] = None) -> dict[str, Any]:
        """Same as :meth:`list_payment_methods`."""
        return self.list_payment_methods(payment_method)

    def list_payment_methods(self, payment_method: Optional[str] = None) -> dict[str, Any]:
        """The payment methods open for your account (``GET /payments/methods``, signed).

        For each method: ``blockName``, ``providerSelection``,
        ``providerSelectionMode``, ``preauth`` support, limits,
        ``splitEligible`` / ``splitBehavior`` and the providers with their
        ``providerCode`` and the ``inputFields`` to send in the method block.
        Read the provider code from this answer; do not hard-code it.

        ``payment_method`` lists that method only (``QR`` is sent as
        ``QR_CODE``); a method that is not open gives ``{"methods": []}``.
        """
        query = (
            None
            if payment_method is None
            else {"paymentMethod": normalize_payment_method(payment_method)}
        )
        return self._api.request("GET", _BASE + "/methods", query=query, step_up=True)

    def direct_method_payment(
        self,
        request: DirectMethodPaymentRequest | Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Starts a payment with any method from your server (``POST /payments/direct/payment``).

        Build the body with :class:`DirectMethodPaymentRequest`; a raw mapping
        is checked with the same rules. Reuse the same ``idempotency_key`` when
        retrying the same payment. The envelope's ``data`` holds
        ``paymentId``, ``status``, ``paymentMethod``, ``providerCode`` and,
        when the buyer must act, ``action`` (HTTP 202): confirm it with
        :meth:`confirm_payment_action`, or show a bank transfer instruction
        read with :meth:`BankTransferInstruction.from_response`.
        """
        if isinstance(request, DirectMethodPaymentRequest):
            body = request.to_dict()
        elif isinstance(request, Mapping):
            body = dict(request)
            assert_direct_method_payment_payload(body)
        else:
            raise ConfigurationError(
                "direct_method_payment takes a DirectMethodPaymentRequest or a body mapping."
            )
        return self._api.request(
            "POST",
            _BASE + "/direct/payment",
            body,
            step_up=True,
            idempotency_key=_key(idempotency_key),
        )

    def confirm_payment_action(
        self,
        payment_id: str,
        action_id: str,
        *,
        otp: Optional[str] = None,
        consent_accepted: Optional[bool] = None,
        fields: Optional[Mapping[str, Any]] = None,
        **unexpected: Any,
    ) -> dict[str, Any]:
        """Completes the open action of a payment (``POST .../actions/{actionId}/confirm``, signed).

        Send the buyer's one-time code (``otp``, digits), the agreement consent
        (``consent_accepted``) when ``action.consent.required`` is true, or the
        values an ``INPUT`` action asks for (``fields``). A signed request never
        carries the hosted form's token fields.
        """
        if unexpected:
            raise ConfigurationError(
                f"Unknown confirm field(s): {', '.join(sorted(unexpected))}. A merchant server "
                "confirms with its signature and sends only otp, consent_accepted and fields."
            )
        return self._api.request(
            "POST",
            _action_path(payment_id, action_id, "confirm"),
            _confirm_body(otp, consent_accepted, fields),
            step_up=True,
        )

    def resend_payment_action(self, payment_id: str, action_id: str) -> dict[str, Any]:
        """Sends a new one-time code; confirm with the new ``data.action.id``."""
        return self._api.request(
            "POST", _action_path(payment_id, action_id, "resend"), step_up=True
        )

    def get_promissory_notes(self, payment_id: str) -> dict[str, Any]:
        """The notes of a promissory-note payment (``GET .../{id}/promissory-notes``, signed)."""
        return self._api.request("GET", _promissory_notes_path(payment_id), step_up=True)

    def cancel_promissory_notes(
        self,
        payment_id: str,
        serial_numbers: Optional[Sequence[str]] = None,
        *,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Cancels notes (``POST /payments/{id}/promissory-notes/cancel``, signed).

        Without ``serial_numbers`` every open note is cancelled. The answer
        carries ``cancelResults[]`` per note (:class:`PromissoryNoteCancelResult`,
        :class:`PromissoryNoteCancelErrorCode`).
        """
        body = (
            None
            if serial_numbers is None
            else {"serialNumbers": require_serial_numbers(serial_numbers)}
        )
        return self._api.request(
            "POST",
            _promissory_notes_path(payment_id) + "/cancel",
            body,
            step_up=True,
            idempotency_key=None if idempotency_key is None else _key(idempotency_key),
        )

    def download_promissory_note_document(
        self, payment_id: str, locale: Optional[str] = None
    ) -> BinaryResponse:
        """The printable notes as a PDF (``GET /payments/{id}/promissory-notes/document``, signed).

        ``locale`` is :class:`PromissoryNoteDocumentLocale` (``tr-TR`` or
        ``en-GB``). The document is built on request and not stored. Returns
        :class:`~lunixi.api_client.BinaryResponse` with the PDF bytes in
        ``content``; an error answer raises as usual.
        """
        query = None if locale is None else {"locale": require_document_locale(locale)}
        document = self._api.request_binary(
            "GET",
            _promissory_notes_path(payment_id) + "/document",
            query=query,
            step_up=True,
            accept=_PDF_ACCEPT,
        )
        if not (document.content_type or "").lower().startswith("application/pdf"):
            raise ApiError("The gateway did not return a PDF document.")
        return document

    def list_bank_transfer_exceptions(
        self,
        *,
        environment: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """Late, short and excess transfers of ``BANK_TRANSFER`` payments (signed).

        Filters: ``environment`` (``TEST`` | ``LIVE``), ``status``
        (:class:`PaymentBankTransferExceptionStatus`) and ``limit`` (1–200);
        ``None`` is not sent.
        """
        query = bank_transfer_exceptions_query(environment, status, limit)
        return self._api.request(
            "GET", _BASE + "/bank-transfer/exceptions", query=query or None, step_up=True
        )

    def accept_bank_transfer_exception(self, exception_id: str) -> dict[str, Any]:
        """Accepts a ``LATE`` or ``UNDERPAID`` exception (``POST .../{id}/accept``, signed)."""
        return self._api.request(
            "POST", bank_transfer_exception_path(_BASE, exception_id, "accept"), step_up=True
        )

    def mark_bank_transfer_exception_refunded(self, exception_id: str) -> dict[str, Any]:
        """Reports that you refunded the money yourself (``POST .../{id}/refunded``, signed)."""
        return self._api.request(
            "POST", bank_transfer_exception_path(_BASE, exception_id, "refunded"), step_up=True
        )

    def create_split_payment(
        self,
        request: SplitPaymentRequest | Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Starts a split payment, or continues it (``POST /payments/split``, signed).

        ``idempotency_key`` (at most 200 characters) is the identity of the
        split payment: after a step (an OTP confirmed, the buyer back from 3D
        Secure) send the SAME request with the SAME key and the payment
        continues where it stopped. The answer carries ``splitPaymentId``,
        ``status``, ``steps`` and ``pendingStep`` (:class:`SplitPendingStep`).

        While the payment is running the gateway answers HTTP 400 with the
        status as ``code`` (:data:`SPLIT_PAYMENT_IN_PROGRESS_STATUSES`); that
        answer is returned here, not raised. A failed payment raises
        :class:`~lunixi.errors.ValidationError`.
        """
        if isinstance(request, SplitPaymentRequest):
            body = request.to_dict()
        elif isinstance(request, Mapping):
            body = dict(request)
            assert_split_payment_payload(body)
        else:
            raise ConfigurationError(
                "create_split_payment takes a SplitPaymentRequest or a body mapping."
            )
        return self._api.request(
            "POST",
            _BASE + "/split",
            body,
            step_up=True,
            idempotency_key=_split_key(idempotency_key, "a split payment"),
            result_on_error=is_running_split_response,
        )

    def get_split(self, split_payment_id: str) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/split/" + identifier(split_payment_id))

    def list_splits(self, **filters: Any) -> dict[str, Any]:
        """Split payments, newest first (``GET /payments/split``).

        Filters: ``status`` and ``currency`` (a value or a list),
        ``createdFrom``, ``createdTo``, ``orderId``, ``ownerRef``, ``limit``
        (1–100) and ``after`` (``pageInfo.endCursor`` of the previous page).
        """
        return self._api.request(
            "GET", _BASE + "/split", query=list_split_payments_query(filters) or None
        )

    def refund_split(
        self,
        split_payment_id: str,
        amount: str,
        *,
        idempotency_key: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._refund(
            _BASE + "/split/" + identifier(split_payment_id) + "/refund",
            amount,
            idempotency_key,
            reason,
        )

    def bin_info(self, bin_or_pan: str) -> dict[str, Any]:
        """Card, bank and installment eligibility of a BIN (``POST /bin/info``).

        ``bin_or_pan`` is the card's BIN (6 or 8 digits) or its leading digits.
        The value is never placed in an error message.
        """
        body = {"binOrPan": require_bin_or_pan(bin_or_pan)}
        return self._api.request("POST", _BIN + "/info", body)

    def installment_options(
        self, request: InstallmentOptionsRequest | Mapping[str, Any]
    ) -> dict[str, Any]:
        """The installment table for an amount (``POST /bin/installments``).

        With a BIN and ``installment`` > 1 the answer carries a binding
        ``quoteToken``. ``enabled_installments`` (or a raw
        ``enabledInstallments``) narrows the table: integers 1–36, no
        duplicates, 1 included; sent in ascending order.
        """
        return self._api.request("POST", _BIN + "/installments", installment_options_body(request))

    def card_taxonomy(self) -> dict[str, Any]:
        """Card brand, family and bank reference lists (``GET /bin/card-taxonomy``)."""
        return self._api.request("GET", _BIN + "/card-taxonomy")

    def store_card(self, request: StoreCardRequest, *, idempotency_key: str) -> dict[str, Any]:
        """Verifies and stores a card (``POST /payments/cards``, signed, key required).

        The answer carries the ``storedCardToken``; charge it later with
        ``cardUserKey`` + ``cardToken`` in :meth:`DirectMethodPaymentRequest.with_card`.
        """
        if not isinstance(request, StoreCardRequest):
            raise ConfigurationError("store_card takes a StoreCardRequest.")
        return self._api.request(
            "POST",
            _BASE + "/cards",
            request.to_dict(),
            step_up=True,
            idempotency_key=_required_key(idempotency_key, "store card"),
        )

    def list_stored_cards(self, card_user_key: str) -> dict[str, Any]:
        """The stored cards of one buyer (``GET /payments/cards?cardUserKey=``)."""
        if not isinstance(card_user_key, str) or card_user_key.strip() == "":
            raise ConfigurationError("card_user_key is required.")
        return self._api.request("GET", _BASE + "/cards", query={"cardUserKey": card_user_key})

    def get_stored_card(self, stored_card_token: str) -> dict[str, Any]:
        """One stored card (``GET /payments/cards/{storedCardToken}``)."""
        return self._api.request("GET", _stored_card_path(stored_card_token))

    def deactivate_stored_card(
        self, stored_card_token: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        """Deactivates a stored card (``DELETE /payments/cards/{token}``, signed, key required)."""
        return self._api.request(
            "DELETE",
            _stored_card_path(stored_card_token),
            step_up=True,
            idempotency_key=_required_key(idempotency_key, "deactivate stored card"),
        )

    def failover_recovery_analytics(self, **filters: Any) -> dict[str, Any]:
        """Payments rescued by provider failover (``GET /payments/analytics/failover-recovery``).

        Filters (e.g. ``from``, ``to``, ``range``) are sent as query parameters;
        ``None`` is not sent.
        """
        return self._api.request(
            "GET", _BASE + "/analytics/failover-recovery", query=filters or None
        )

    def provider_credential_analytics(self, credential_id: str, **filters: Any) -> dict[str, Any]:
        """One provider credential's performance (``GET …/provider-credentials/{id}``)."""
        source = "the provider credential id from your panel"
        return self._api.request(
            "GET",
            f"{_BASE}/analytics/provider-credentials/"
            f"{_segment(credential_id, 'credential_id', source)}",
            query=filters or None,
        )

    def _refund(
        self, path: str, amount: str | _OmittedAmount, key: str, reason: Optional[str]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {} if amount is _OMITTED_AMOUNT else {"amount": amount_minor(amount)}
        if reason is not None:
            if not isinstance(reason, str) or len(reason) > 500:
                raise ConfigurationError("Refund reason exceeds 500 characters.")
            body["reason"] = reason
        return self._api.request("POST", path, body, step_up=True, idempotency_key=_key(key))
