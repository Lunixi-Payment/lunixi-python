"""Synthetic external gateway only; framework/database code remains real."""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import urlsplit

from lunixi.http.transport import HttpResponse, TransportError


class PaymentGateway:
    def __init__(self) -> None:
        self.payments: dict[str, Any] = {}
        self.splits: dict[str, Any] = {}
        self.calls = []
        self.keys = {}
        self.lost_create = False
        self.lost_mutation = False
        self.defer = False
        self.payment_page_url = "https://pay.lunixi.com/payment/server-issued-page-0123456789"
        self.lock = threading.Lock()

    def send(self, method, url, headers, body, timeout):
        with self.lock:
            path = urlsplit(url).path
            value = json.loads(body) if body is not None else None
            self.calls.append((method, path, dict(headers), value))
            if path == "/api/v1/auth/token":
                return self.response({"access_token": "at_SYNTHETIC_ONLY", "expires_in": 1800})
            key = headers.get("Idempotency-Key")
            if method == "POST" and key in self.keys:
                old_method, old_path, old_value, result = self.keys[key]
                if (method, path, value) != (old_method, old_path, old_value):
                    return self.response({"code": "IDEMPOTENCY_CONFLICT"}, 409)
                return self.response(result)
            if path == "/api/v1/payments/intents":
                payment_id = "pi_" + str(len(self.payments) + 1)
                data = {
                    "id": payment_id,
                    "merchantId": "merchant_test",
                    "orderId": value["orderId"],
                    "currency": value["currency"],
                    "amount": value["amount"],
                    "status": "AUTHORIZED" if value.get("preauth") else "PROCESSING",
                    "metadata": value.get("metadata", {}),
                }
                self.payments[payment_id] = {
                    "data": data,
                    "details": {"capturedAmount": 0, "refundedAmount": 0},
                }
                result = {
                    "data": {
                        "paymentId": payment_id,
                        "token": "synthetic_browser_token_" + payment_id,
                        "paymentPageUrl": self.payment_page_url,
                    }
                }
                self.keys[key] = (method, path, value, result)
                if self.lost_create:
                    self.lost_create = False
                    raise TransportError("SYNTHETIC lost create response")
                return self.response(result)
            if path.startswith("/api/v1/payments/split/"):
                split_id = path.split("/")[5]
                return self.response(self.splits[split_id])
            if path.startswith("/api/v1/payments/"):
                parts = path.split("/")
                payment_id = parts[4]
                payment = self.payments.get(payment_id)
                if payment is None:
                    return self.response({"code": "NOT_FOUND"}, 404)
                if method == "GET":
                    return self.response(payment)
                action = parts[5]
                if not self.defer:
                    if action == "capture":
                        payment["details"]["capturedAmount"] += value["amount"]
                        payment["data"]["status"] = (
                            "CAPTURED"
                            if payment["details"]["capturedAmount"] == payment["data"]["amount"]
                            else "PARTIALLY_CAPTURED"
                        )
                    if action == "refund":
                        payment["details"]["refundedAmount"] += value["amount"]
                        payment["data"]["status"] = (
                            "REFUNDED"
                            if payment["details"]["refundedAmount"]
                            == payment["details"]["capturedAmount"]
                            else "PARTIALLY_REFUNDED"
                        )
                    if action == "void":
                        payment["data"]["status"] = "VOIDED"
                result = {"data": {"accepted": True}}
                self.keys[key] = (method, path, value, result)
                if self.lost_mutation:
                    self.lost_mutation = False
                    raise TransportError("SYNTHETIC lost mutation response")
                return self.response(result, 202)
            return self.response({"code": "NOT_FOUND"}, 404)

    def capture(self, payment_id):
        self.payments[payment_id]["data"]["status"] = "CAPTURED"
        self.payments[payment_id]["details"]["capturedAmount"] = self.payments[payment_id]["data"][
            "amount"
        ]

    @staticmethod
    def response(value, status=200):
        return HttpResponse(
            status, {"content-type": "application/json"}, json.dumps(value).encode()
        )
