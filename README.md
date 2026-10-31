<p align="center">
  <a href="https://lunixi.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Lunixi-Payment/lunixi-python/main/.github/assets/lunixi-logo-dark.svg">
      <img src="https://raw.githubusercontent.com/Lunixi-Payment/lunixi-python/main/.github/assets/lunixi-logo.svg" alt="Lunixi" height="64">
    </picture>
  </a>
</p>

# Lunixi Python SDK

[![CI](https://github.com/Lunixi-Payment/lunixi-python/actions/workflows/ci.yml/badge.svg)](https://github.com/Lunixi-Payment/lunixi-python/actions/workflows/ci.yml) [![PyPI](https://img.shields.io/pypi/v/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Python](https://img.shields.io/pypi/pyversions/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Downloads](https://img.shields.io/pypi/dm/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Typed](https://img.shields.io/badge/typing-typed-blue)](https://peps.python.org/pep-0561/) [![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE) [![Docs](https://img.shields.io/badge/docs-docs.lunixi.com-FF6B35)](https://docs.lunixi.com/sdks/python)

**[Documentation](https://docs.lunixi.com/sdks/python) · [Changelog](https://github.com/Lunixi-Payment/lunixi-python/blob/main/CHANGELOG.md) · [Issues](https://github.com/Lunixi-Payment/lunixi-python/issues) · [Security](https://github.com/Lunixi-Payment/lunixi-python/blob/main/SECURITY.md)**

Version **0.2.0** adds typed payment APIs and durable checkout orchestration while preserving the existing fraud decision/event API. The SDK is synchronous, thread-safe per client, and ships `py.typed`.

[Turkish](README.tr.md) · [Framework examples](docs/FRAMEWORKS.md) · [Django](docs/DJANGO.md) · [FastAPI](docs/FASTAPI.md) · [Flask](docs/FLASK.md)

| Component | Requirement |
|---|---|
| Core SDK | Python 3.9+; use a maintained Python runtime for deployment |
| Runtime dependencies | `cryptography>=50.0.2,<51`, `rfc8785>=0.1.4,<0.2`; stdlib HTTP/SQLite |
| Verified framework targets | Django 6.1.2 / FastAPI 0.162.0 / Flask 3.1.3 on Python 3.12.14 |
| Payment form | Official Lunixi browser bundle or hosted `pay.lunixi.com` |
| Durable example storage | SQLite on disk; Django's native ORM with IMMEDIATE transactions |

## Installation

Version **0.2.0** is published on [PyPI](https://pypi.org/project/lunixi-sdk/0.2.0/):

```sh
pip install lunixi-sdk==0.2.0
```

Alternatively, install the same source tag from GitHub:

```sh
pip install "lunixi-sdk @ git+https://github.com/Lunixi-Payment/lunixi-python.git@v0.2.0"
```

From a source checkout, `pip install -e .` installs the SDK; `pip install -e '.[frameworks]'` installs optional runtime dependencies. Framework apps and full native tests need Python 3.12+ and the source checkout. They are runnable examples, not separately registered framework packages.

## Payment quick start

```python
import os
from lunixi import LunixiClient, CreateIntent

client = LunixiClient(
    base_url="https://api-gateway.lunixi.com",
    key_id=os.environ["LUNIXI_KEY_ID"],
    private_key=os.environ["LUNIXI_PRIVATE_KEY"],
    max_retries=0,
)
intent = client.payments().create_intent(
    CreateIntent(1990, "TRY", "persisted-order-123",
                 callback_url="https://shop.example/return/123"),
    idempotency_key=persisted_attempt_key,
)
# Return only after authenticating ownership of the persisted order:
public_form_configuration = intent.browser_config()
# Or redirect to the fixed hosted origin:
hosted_url = intent.hosted_url
```

Money is integer minor units, from 1 to 9,007,199,254,740,991; booleans, floats, zero and removed root amount fields fail before token exchange/network. `minor_units('19.90','TRY')` converts a plain decimal string exactly; JPY has0 decimals and KWD 3. Preauthorization is a JSON boolean; an authorization is on hold, not paid. Available methods, installments, eligible shopping credit/meal cards, insurance and multi-card options belong to the Lunixi form/panel. The examples never collect card numbers/CVV.

| Helper | Merchant API |
|---|---|
| `payments().create_intent(CreateIntent(...), idempotency_key=...)` | POST `/api/v1/payments/intents` → canonical response `paymentId` and `token` |
| `get(payment_id)`, `list(**filters)` | GET `/api/v1/payments/{id}`, `/api/v1/payments` |
| `capture(id, amount, idempotency_key=...)` | POST `/api/v1/payments/{id}/capture` |
| `refund(id, amount, idempotency_key=..., reason=...)` | POST `/api/v1/payments/{id}/refund` |
| `void(id, idempotency_key=...)` | POST `/api/v1/payments/{id}/void` |
| `methods()` | GET `/api/v1/payments/methods`, signed |
| `get_split(id)`, `list_splits(**filters)` | GET `/api/v1/payments/split/{id}`, `/api/v1/payments/split` |
| `refund_split(id, amount, idempotency_key=...)` | POST `/api/v1/payments/split/{id}/refund` |

Non-intent helpers return the complete response envelope, preserving `details`, `pageInfo` and request IDs. Financial helper keys are required and must come from durable application records. An HTTP 2xx mutation response does not prove settlement.

## Durable native checkout

`lunixi.commerce.CheckoutService` persists an immutable merchant/order/amount/currency snapshot and a stable attempt key **before** network I/O. It encrypts persisted browser tokens with a separate 32-byte server key. A native adapter supplies the transaction store and an idempotent native order callback using that **same connection/transaction**.

```python
from lunixi.commerce import CheckoutService, SqliteLedgerStore, SecretBox, OrderSnapshot

ledger = SqliteLedgerStore("/secure/state/commerce.sqlite3")
ledger.install()  # explicit schema setup, outside request handling
service = CheckoutService(client, ledger, SecretBox(server_encryption_key_bytes))
session = service.start(
    "order-123", OrderSnapshot(merchant_id, "order-123", 1990, "TRY"),
    "https://shop.example/return/order-123", hosted=True,
)
# `apply_native` validates current native totals/holds and writes using tx.connection.
decision = service.reconcile("order-123", apply_native)
```

The runnable [framework integrations](docs/FRAMEWORKS.md) implement real order, stock, inbox and native outbox writes; a no-op callback is not a fulfillment implementation. Native fraud/manual holds remain effective after capture. Changed native totals/currency cannot be completed by an older intent. Buyer installment fees require the persisted fingerprint and stay separate from the basket; split success requires complete, balanced parent evidence with no compensation/reconciliation requirement. Partial capture is on hold.

Browser query parameters/form events never mark paid. `service.webhook(raw_bytes, headers, secret, apply_native)` verifies raw-body v2 HMAC/freshness/signed id/type, then queries authenticated payment/split evidence. Payment GET's `data.id`, create result `paymentId` and webhook `data.intentId` identify the same payment. Durable row locking and unique event hashes commit with native writes; a failed callback rolls back both. Signed event-ID content collisions fail. Lost create responses recover only from a verified payment webhook plus authenticated GET echoing the original opaque reservation hash/fingerprint; an existing payment ID is never rebound.

`service.mutate(order_key, persisted_operation_id, 'capture'|'refund'|'void', amount_or_none, apply_native)` reserves a durable operation and stable gateway key. `operation_status(...)` returns `pending`, `uncertain` or `confirmed` without exposing the key. New IDs are blocked while a prior operation is unresolved. Only authenticated balances/releases confirm success; refunds cannot exceed captured funds. Retry the exact original operation ID/amount after a timeout. Unconfirmed create/mutation retries older than 23 hours are blocked before POST, since gateway key retention is finite. GET reconciliation remains available. `FAILED` without outcome certainty stays review; this version provides no automatic ambiguous-attempt reset.

## Authentication, transport and JSON

Generate Ed25519 keys with `generate_key_pair()` and register only the public key. The SDK accepts PKCS8 PEM/DER, base64/hex seeds and validated 64-byte seed/public exports. `cryptography` provides curve/AES-GCM primitives. Keep one client per origin/merchant key; token refresh coalesces concurrent threads. A custom `TokenStore` must be explicitly scoped to that origin/key. Cache lifetime respects expiration/skew; credentials do not appear in config representations.

HTTPS origins cannot contain credentials, path prefixes, query or fragment. API paths remain under `/api/v1/` without traversal or normalization escapes. Redirects are not followed, including authentication redirects. Defaults:30 seconds/request,8MiB response cap,2 extra retries; timeout is bounded to 120 seconds and retries to5. Writes retry only with a nonempty stable key, including a401 refresh. Signing uses exact compact UTF-8 JSON, JavaScript numeric-key ordering and RFC8785 ECMAScript scalar formatting; unsafe integers/non-finite numbers fail locally. An explicit numeric-loopback HTTP opt-in exists for transport tests; Commerce always requires HTTPS.

## Existing fraud API

```python
from lunixi import Channel
result = client.fraud().evaluate(
    channel=Channel.STANDALONE_API,
    transaction_ref="persisted-order-123",
    payment={"amount":1990,"currency":"TRY"},
)
if result.blocked:
    refuse_order()
elif result.requires_review or result.requires_three_d:
    hold_for_review_or_three_ds()
```

Fraud evaluate, decision-log list/get and event record/batch APIs retain their names/results. Decision/log calls remain bearer-authenticated; event ingest is signed per request. Batch ingestion supports up to 500 events and may partially succeed; inspect `result.failures()` and resend failed events with the same event IDs. `Page` preserves top-level cursor metadata; iterate using the returned cursor. No internal console route is a supported merchant API.

## Other documented services and errors

```python
response = client.api().request(
    "GET", "/api/v1/payments/methods", step_up=True,
)
```

The generic authenticated layer can reach other documented merchant services with explicit `step_up=True` when required. This release does not claim typed subscription, KYC, identity, sanction, wallet, insurance, bank-connect, direct-card or split-initiation workflows. Browser form submission belongs to the official bundle.

Catch `LunixiError` or typed `ApiError`/`ValidationError`/`AuthenticationError`/`RateLimitError`/`ServiceUnavailableError`. Status, machine code, request ID and quota metadata remain available; raw remote error messages/bodies and transport exception text are withheld. Do not log raw successful responses either: they can carry browser tokens/customer data.

Low-level `WebhookVerifier` verifies signatures but does not claim replay IDs. Default signed id/type binding is strict. `allow_legacy_header_fields=True` preserves the old nonfinancial fallback explicitly and produces no financial replay proof; never use it for order fulfillment. `tolerance_seconds=None` is an explicit offline-fixture option, not a live setting. A secret list supports rotation; retain old endpoint secrets through the grace window.

## Verify and build

```sh
pip install -r requirements-dev.lock
pip install --no-deps -e .
ruff check src integrations tests
ruff format --check src integrations tests
mypy src/lunixi
bandit -r src/lunixi integrations -q
pip-audit
pytest -q
python -m build
```

The lock targets the verified Python 3.12 development environment. Core CI also exercises Python 3.9/3.10/3.14; framework tests run on 3.12. Native tests use real framework clients/users/CSRF/ORM/databases and synthetic external gateway transport. The HTTPS transport fixture binds only loopback. No live charge, external email or automatic shipment occurs in tests. Wheel contains the typed SDK; sdist/source also contains runnable apps, tests, original logos and EN/TR guides.

MIT · [Security](SECURITY.md) · [Contribution guide](CONTRIBUTING.md) · [Changelog](CHANGELOG.md).
