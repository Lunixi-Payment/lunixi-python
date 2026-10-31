"""Shared example application code: persisted customer orders and atomic fulfillment."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

from lunixi import LunixiClient
from lunixi.commerce import (
    CheckoutService,
    CommerceError,
    OrderSnapshot,
    PaymentDecision,
    SecretBox,
    SqliteLedgerStore,
    SqliteTransaction,
    Transaction,
)
from lunixi.validation import amount_minor, currency_code, identifier, origin_url

DEFAULT_FORM_ACTION_ORIGINS = ("https://api-gateway.lunixi.com",)
_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_FORM_ORIGIN = re.compile(r"https://" + _DNS_LABEL + r"(?:\." + _DNS_LABEL + r")*(?::[0-9]{1,5})?")


def approved_form_action_origins(gateway: str, additional: str = "") -> tuple[str, ...]:
    """Server-only CSP destinations; never derive these from a payment response."""
    values = [gateway] + (additional.split(",") if additional else [])
    for value in values:
        if not isinstance(value, str) or not _FORM_ORIGIN.fullmatch(value):
            raise CommerceError("Form actions require explicit HTTPS origins without paths.")
        uri = urlsplit(value)
        try:
            port = 443 if uri.port is None else uri.port
        except ValueError:
            raise CommerceError("Invalid form-action origin.") from None
        if len(uri.hostname or "") > 253 or not 1 <= port <= 65535:
            raise CommerceError("Invalid form-action origin.")
    return tuple(dict.fromkeys(values))


TEXT = {
    "en": {
        "title": "Secure payment",
        "pay": "Continue to payment",
        "pending": "Your payment is awaiting verification.",
        "paid": "Your payment has been verified.",
        "methods": "Available payment methods are managed by the merchant through Lunixi.",
        "error": "Payment could not be verified. Please try again later.",
        "hold": "Your order is awaiting review.",
    },
    "tr": {
        "title": "Güvenli ödeme",
        "pay": "Ödemeye devam et",
        "pending": "Ödemenizin doğrulanması bekleniyor.",
        "paid": "Ödemeniz doğrulandı.",
        "methods": "Kullanılabilir ödeme yöntemleri mağaza tarafından Lunixi üzerinden yönetilir.",
        "error": "Ödeme doğrulanamadı. Lütfen daha sonra tekrar deneyin.",
        "hold": "Siparişinizin incelenmesi bekleniyor.",
    },
}


@dataclass(frozen=True)
class Settings:
    public_origin: str
    merchant_id: str
    webhook_secret: str
    session_secret: str
    encryption_key: bytes
    database: str
    mode: str = "embedded"
    preauth: bool = False
    locale: str = "en"
    form_action_origins: tuple[str, ...] = DEFAULT_FORM_ACTION_ORIGINS

    @classmethod
    def from_env(cls) -> Settings:
        required = [
            "LUNIXI_PUBLIC_ORIGIN",
            "LUNIXI_MERCHANT_ID",
            "LUNIXI_WEBHOOK_SECRET",
            "LUNIXI_SESSION_SECRET",
            "LUNIXI_ENCRYPTION_KEY",
            "LUNIXI_DATABASE",
        ]
        if any(not os.environ.get(key) for key in required):
            raise CommerceError(
                "Configure the required server environment before starting the example."
            )
        origin = origin_url(os.environ["LUNIXI_PUBLIC_ORIGIN"])
        try:
            key = base64.b64decode(os.environ["LUNIXI_ENCRYPTION_KEY"], validate=True)
        except ValueError:
            raise CommerceError("Invalid server encryption key.") from None
        settings = cls(
            origin,
            os.environ["LUNIXI_MERCHANT_ID"],
            os.environ["LUNIXI_WEBHOOK_SECRET"],
            os.environ["LUNIXI_SESSION_SECRET"],
            key,
            os.environ["LUNIXI_DATABASE"],
            os.environ.get("LUNIXI_CHECKOUT_MODE", "embedded"),
            os.environ.get("LUNIXI_PREAUTH", "false") == "true",
            os.environ.get("LUNIXI_LOCALE", "en"),
            approved_form_action_origins(
                os.environ.get("LUNIXI_GATEWAY_ORIGIN", DEFAULT_FORM_ACTION_ORIGINS[0]),
                os.environ.get("LUNIXI_FORM_ACTION_ORIGINS", ""),
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        origin_url(self.public_origin)
        if not isinstance(self.form_action_origins, tuple) or not self.form_action_origins:
            raise CommerceError("Explicit form-action origins are required.")
        for origin in self.form_action_origins:
            approved_form_action_origins(origin)
        if (
            len(self.webhook_secret) < 16
            or len(self.session_secret) < 32
            or len(self.encryption_key) != 32
            or self.mode not in ("hosted", "embedded")
            or self.locale not in TEXT
            or not self.merchant_id
        ):
            raise CommerceError(
                "Invalid server settings; secrets must be separate and sufficiently long."
            )
        if (
            self.session_secret == self.webhook_secret
            or self.encryption_key == self.session_secret.encode()
        ):
            raise CommerceError("Independent server secrets are required.")

    def __repr__(self) -> str:
        return f"Settings(public_origin={self.public_origin!r}, mode={self.mode!r}, secrets=<redacted>)"


def callback_post_allowed(length: Optional[str]) -> bool:
    """Bound declared callback bytes without parsing or reading untrusted form data.

    Reverse proxies must also enforce a wire body limit for chunked requests.
    """
    return length is None or (
        length.isascii() and length.isdigit() and len(length) <= 5 and int(length) <= 65536
    )


def sdk_from_env() -> LunixiClient:
    return LunixiClient(
        base_url=os.environ.get("LUNIXI_GATEWAY_ORIGIN", "https://api-gateway.lunixi.com"),
        key_id=os.environ["LUNIXI_KEY_ID"],
        private_key=os.environ["LUNIXI_PRIVATE_KEY"],
        max_retries=0,
    )


class Orders:
    """One actual SQLite DB holds orders, stock, attempt, inbox and native outbox."""

    def __init__(self, settings: Settings, client: Optional[LunixiClient] = None) -> None:
        settings.validate()
        self.settings = settings
        self.store = SqliteLedgerStore(settings.database)
        self.service = CheckoutService(
            client or sdk_from_env(), self.store, SecretBox(settings.encryption_key)
        )

    def install(self) -> None:
        self.store.install()
        connection = self.store.connect()
        try:
            connection.executescript("""CREATE TABLE IF NOT EXISTS sample_stock(sku TEXT PRIMARY KEY,quantity INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sample_order(id TEXT PRIMARY KEY,owner TEXT NOT NULL,amount INTEGER NOT NULL,currency TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',captured INTEGER NOT NULL DEFAULT 0,refunded INTEGER NOT NULL DEFAULT 0,stock_applied INTEGER NOT NULL DEFAULT 0,fulfillment_hold INTEGER NOT NULL DEFAULT 0,claim_hash TEXT,claim_expiry INTEGER NOT NULL DEFAULT 0,next_poll INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sample_outbox(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE,state TEXT NOT NULL DEFAULT 'pending',FOREIGN KEY(order_id) REFERENCES sample_order(id));
INSERT OR IGNORE INTO sample_stock(sku,quantity) VALUES('sample-product',100);""")
        finally:
            connection.close()

    def seed(
        self, owner: str, amount: int = 1990, currency: str = "TRY", *, hold: bool = False
    ) -> tuple[str, str]:
        amount_minor(amount)
        currency_code(currency)
        if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
            raise CommerceError("A trusted customer identity is required.")
        key = "order_" + secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        connection = self.store.connect()
        try:
            connection.execute(
                "INSERT INTO sample_order(id,owner,amount,currency,fulfillment_hold,claim_hash,claim_expiry) VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    owner,
                    amount,
                    currency,
                    int(hold),
                    hashlib.sha256(token.encode()).hexdigest(),
                    int(time.time()) + 900,
                ),
            )
        finally:
            connection.close()
        return key, token

    def claim(self, token: str) -> tuple[str, str]:
        if not isinstance(token, str) or not 16 <= len(token) <= 128:
            raise CommerceError("Invalid or expired checkout invitation.")
        digest = hashlib.sha256(token.encode()).hexdigest()
        connection = self.store.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,owner FROM sample_order WHERE claim_hash=? AND claim_expiry>?",
                (digest, int(time.time())),
            ).fetchone()
            if row is None:
                raise CommerceError("Invalid or expired checkout invitation.")
            connection.execute("UPDATE sample_order SET claim_hash=NULL WHERE id=?", (row["id"],))
            connection.commit()
            return row["id"], row["owner"]
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def owned(self, key: str, owner: Any) -> dict[str, Any]:
        identifier(key)
        connection = self.store.connect()
        try:
            row = connection.execute("SELECT * FROM sample_order WHERE id=?", (key,)).fetchone()
            if (
                row is None
                or not isinstance(owner, str)
                or not hmac.compare_digest(row["owner"].encode("utf-8"), owner.encode("utf-8"))
            ):
                raise CommerceError("Order ownership is required.")
            return dict(row)
        finally:
            connection.close()

    def start(self, key: str, owner: Any) -> dict[str, Any]:
        row = self.owned(key, owner)
        snapshot = OrderSnapshot(self.settings.merchant_id, key, row["amount"], row["currency"])
        result = self.service.start(
            key,
            snapshot,
            self.settings.public_origin + "/return/" + key,
            hosted=self.settings.mode == "hosted",
            preauth=self.settings.preauth,
            locale=self.settings.locale,
        )
        return (
            {"redirect": result.hosted_url}
            if self.settings.mode == "hosted"
            else {"config": result.browser_config()}
        )

    def apply(self, tx: Transaction, order: OrderSnapshot, decision: PaymentDecision) -> None:
        if not isinstance(tx, SqliteTransaction):
            raise CommerceError(
                "Native order and payment transaction must share SQLite connection."
            )
        row = tx.connection.execute(
            "SELECT * FROM sample_order WHERE id=?", (order.order_id,)
        ).fetchone()
        if (
            row is None
            or order.fingerprint
            != OrderSnapshot(
                self.settings.merchant_id, row["id"], row["amount"], row["currency"]
            ).fingerprint
        ):
            raise CommerceError("The persisted native order changed after reservation.")
        applied = row["stock_applied"]
        if decision.paid and not row["fulfillment_hold"] and not applied:
            cursor = tx.connection.execute(
                "UPDATE sample_stock SET quantity=quantity-1 WHERE sku='sample-product' AND quantity>0"
            )
            if cursor.rowcount != 1:
                raise CommerceError("Native stock is unavailable; hold for review.")
            applied = 1
        if decision.state == "refunded" and applied:
            tx.connection.execute(
                "UPDATE sample_stock SET quantity=quantity+1 WHERE sku='sample-product'"
            )
            applied = 0
        tx.connection.execute(
            "UPDATE sample_order SET state=?,captured=?,refunded=?,stock_applied=? WHERE id=?",
            (
                decision.state,
                decision.captured_amount,
                decision.refunded_amount,
                applied,
                order.order_id,
            ),
        )
        event_hash = hashlib.sha256(
            (order.order_id + json.dumps(decision.to_dict(), sort_keys=True)).encode()
        ).hexdigest()
        tx.connection.execute(
            "INSERT OR IGNORE INTO sample_outbox(order_id,event_hash) VALUES(?,?)",
            (order.order_id, event_hash),
        )

    def complete(self, key: str, owner: Any) -> bool:
        self.owned(key, owner)
        with self.store.transaction(key) as tx:
            if not isinstance(tx, SqliteTransaction):
                raise CommerceError("Native transaction context is required.")
            row = tx.connection.execute("SELECT * FROM sample_order WHERE id=?", (key,)).fetchone()
            record = tx.load()
            return (
                row is not None
                and isinstance(owner, str)
                and hmac.compare_digest(row["owner"].encode("utf-8"), owner.encode("utf-8"))
                and record is not None
                and record["snapshot"]
                == OrderSnapshot(
                    self.settings.merchant_id, key, row["amount"], row["currency"]
                ).to_dict()
                and row["state"] in ("paid", "partially_refunded")
                and not row["fulfillment_hold"]
                and bool(row["stock_applied"])
            )

    def status(self, key: str, owner: Any) -> dict[str, Any]:
        self.owned(key, owner)
        connection = self.store.connect()
        try:
            cursor = connection.execute(
                "UPDATE sample_order SET next_poll=? WHERE id=? AND next_poll<=?",
                (int(time.time()) + 15, key, int(time.time())),
            )
            poll = cursor.rowcount == 1
        finally:
            connection.close()
        if poll:
            self.service.reconcile(key, self.apply)
        return {"complete": self.complete(key, owner)}

    def webhook(self, raw: bytes, headers: MappingHeaders) -> None:
        self.service.webhook(raw, headers, self.settings.webhook_secret, self.apply)


MappingHeaders = dict[str, Any]


def require_csrf(session: Any, token: Optional[str]) -> None:
    expected = session.get("csrf")
    if (
        not isinstance(expected, str)
        or not isinstance(token, str)
        or not hmac.compare_digest(expected.encode("utf-8"), token.encode("utf-8"))
    ):
        raise CommerceError("Checkout request nonce is invalid.")


def checkout_page(
    key: str,
    csrf: str,
    locale: str,
    *,
    complete: bool = False,
    hold: bool = False,
    nonce: Optional[str] = None,
) -> str:
    t = TEXT.get(locale, TEXT["en"])
    data = (
        json.dumps(
            {
                "url": "/checkout/" + key,
                "status": "/status/" + key,
                "csrf": csrf,
                "error": t["error"],
            },
            ensure_ascii=True,
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    nonce = nonce or secrets.token_urlsafe(18)
    message = t["paid"] if complete else t["hold"] if hold else t["pending"]
    button = "" if complete or hold else '<button id="pay">' + html.escape(t["pay"]) + "</button>"
    return f'''<!doctype html><html lang="{html.escape(locale)}"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(t["title"])}</title><style nonce="{nonce}">body{{font:18px system-ui;max-width:45rem;margin:3rem auto;padding:1rem;color:#1e3a5f}}button{{background:#ff6b35;color:#fff;padding:.8rem;border:0;border-radius:.5rem}}img{{width:200px}}</style><img src="/assets/lunixi-logo.svg" alt="Lunixi"><h1>{html.escape(t["title"])}</h1><p>{html.escape(t["methods"])}</p><p id="message" role="status">{html.escape(message)}</p><div id="lunixi-checkout-form"></div>{button}<script src="https://cdn.lunixi.com/lunixi-checkout.min.js" nonce="{nonce}"></script><script nonce="{nonce}">const config={data};const button=document.getElementById('pay');if(button)button.onclick=async()=>{{button.disabled=true;try{{const response=await fetch(config.url,{{method:'POST',credentials:'same-origin',headers:{{'X-CSRF-Token':config.csrf}}}});const result=await response.json();if(!response.ok)throw Error();if(result.redirect){{location.assign(result.redirect);return;}}const form=Lunixi.checkout.create(result.config);form.mount('#lunixi-checkout-form');button.hidden=true;const timer=setInterval(async()=>{{if(!document.getElementById('message')){{clearInterval(timer);return;}}const res=await fetch(config.status,{{credentials:'same-origin',cache:'no-store'}});const value=await res.json();if(value.complete){{clearInterval(timer);location.reload();}}}},5000);}}catch(_){{document.getElementById('message').textContent=config.error;button.disabled=false;}}}};</script></html>'''


def security_headers(
    nonce: Optional[str] = None,
    form_origins: tuple[str, ...] = DEFAULT_FORM_ACTION_ORIGINS,
) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if nonce:
        if not form_origins:
            raise CommerceError("Explicit form-action origins are required.")
        for origin in form_origins:
            approved_form_action_origins(origin)
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'nonce-"
            + nonce
            + "' https://cdn.lunixi.com; style-src 'self' 'nonce-"
            + nonce
            + "'; frame-src https://*.lunixi.com; connect-src 'self' https://*.lunixi.com; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self' "
            + " ".join(form_origins)
        )
    return headers
