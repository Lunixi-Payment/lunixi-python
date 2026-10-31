"""Merchant payment APIs. Card data belongs in the official browser form."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from ..api_client import ApiClient
from ..errors import ApiError, ConfigurationError
from ..validation import amount_minor, currency_code, header_value, identifier

_BASE = "/api/v1/payments"


def _key(value: str) -> str:
    return header_value(value, "idempotency_key")


def validate_amount_body(body: Mapping[str, Any]) -> None:
    if "price" in body or "paidPrice" in body:
        raise ConfigurationError(
            "Removed amount fields are not accepted; send amount in integer minor units."
        )
    amount_minor(body.get("amount"))


@dataclass(frozen=True)
class CreateIntent:
    amount: int
    currency: str
    order_id: str
    callback_url: Optional[str] = None
    preauth: bool = False
    locale: str = "en"
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

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

    def get(self, payment_id: str) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/" + identifier(payment_id))

    def list(self, **filters: Any) -> dict[str, Any]:
        return self._api.request("GET", _BASE, query=filters)

    def capture(self, payment_id: str, amount: int, *, idempotency_key: str) -> dict[str, Any]:
        return self._api.request(
            "POST",
            _BASE + "/" + identifier(payment_id) + "/capture",
            {"amount": amount_minor(amount)},
            step_up=True,
            idempotency_key=_key(idempotency_key),
        )

    def refund(
        self, payment_id: str, amount: int, *, idempotency_key: str, reason: Optional[str] = None
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

    def methods(self) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/methods", step_up=True)

    def get_split(self, split_payment_id: str) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/split/" + identifier(split_payment_id))

    def list_splits(self, **filters: Any) -> dict[str, Any]:
        return self._api.request("GET", _BASE + "/split", query=filters)

    def refund_split(
        self,
        split_payment_id: str,
        amount: int,
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

    def _refund(self, path: str, amount: int, key: str, reason: Optional[str]) -> dict[str, Any]:
        body: dict[str, Any] = {"amount": amount_minor(amount)}
        if reason is not None:
            if not isinstance(reason, str) or len(reason) > 500:
                raise ConfigurationError("Refund reason exceeds 500 characters.")
            body["reason"] = reason
        return self._api.request("POST", path, body, step_up=True, idempotency_key=_key(key))
