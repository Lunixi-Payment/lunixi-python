# Runnable framework integrations

**[SDK 0.2.1 is published on PyPI](https://pypi.org/project/lunixi-sdk/0.2.1/)** and can be installed with `pip install lunixi-sdk==0.2.1`. The runnable framework applications and their locked environment come from the matching [v0.2.1 source tag](https://github.com/Lunixi-Payment/lunixi-python/tree/v0.2.1); they are not separate packages and are not included in the SDK wheel.

These are complete source applications around the same SDK/Commerce workflow, not separately published framework plugins. Use the pinned development lock on Python 3.12+ for the verified Django 6.1.2, FastAPI 0.162.0 and Flask 3.1.3 targets. Existing stores should adapt their own authentication/order/fulfillment models; the examples use real persisted sample orders/stock and enforce ownership.

## Server setup

Check out the matching example source, then install its locked environment:

```sh
git clone --branch v0.2.1 --depth 1 https://github.com/Lunixi-Payment/lunixi-python.git
cd lunixi-python
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
```

Set the following through the server's protected environment/secret manager (no real values belong in an env file committed to Git):

| Variable | Purpose |
|---|---|
| `LUNIXI_PUBLIC_ORIGIN` | Trusted HTTPS application origin, e.g. `https://shop.example` |
| `LUNIXI_MERCHANT_ID` | Merchant identity matched against authenticated payment GET |
| `LUNIXI_KEY_ID`, `LUNIXI_PRIVATE_KEY` | Registered Ed25519 merchant key, TEST/LIVE selected by key |
| `LUNIXI_WEBHOOK_SECRET` | Independent endpoint secret, at least 16 characters |
| `LUNIXI_SESSION_SECRET` | Independent session signing secret, at least 32 characters |
| `LUNIXI_ENCRYPTION_KEY` | Base64 of a separate random 32-byte key, backed up outside DB/web root |
| `LUNIXI_DATABASE` | Absolute persistent SQLite file path outside web root; parent directory exists |
| `LUNIXI_CHECKOUT_MODE` | `embedded` (default) or explicitly selected `hosted` |
| `LUNIXI_PREAUTH` | `true` enables authorization-only checkout; otherwise immediate capture |
| `LUNIXI_LOCALE` | `en` or `tr` |
| `LUNIXI_GATEWAY_ORIGIN` | Optional trusted operator override; defaults to `https://api-gateway.lunixi.com` |
| `LUNIXI_FORM_ACTION_ORIGINS` | Optional comma-separated exact HTTPS provider origins for form POSTs; gateway origin is always included |

Generate independent secrets locally with `secrets.token_urlsafe(48)` and the encryption key with `base64.b64encode(os.urandom(32)).decode()`. Never derive one from another. Configure TLS termination, backups, server body/time limits and protected logs. The examples accept only the configured Host and use Secure/HttpOnly/SameSite cookies. Provider callback POSTs are informational redirects into an owned GET; they do not require or replace the signed webhook.

Register **`<LUNIXI_PUBLIC_ORIGIN>/webhook`** in Lunixi. Preserve exact raw bytes and `X-Lunixi-*` headers; a 2xx webhook response is sent only after native commit, failures return retryable 503. Browser tokens are returned only after session/customer/order ownership and CSRF validation. Signed events are consumed transactionally with native stock/order/outbox updates.

## Native lifecycle

- SQLite store uses disk-backed per-transaction connections, WAL, full synchronization and `BEGIN IMMEDIATE`; never use an in-memory replay set.
- Django uses real auth users, native CSRF middleware, migrations, `transaction.atomic(durable=True)` and row locks; SQLite uses `transaction_mode=IMMEDIATE`. Disabling that setting loses the demonstrated concurrency guarantee.
- Capture/refund/void are server-operator CLI operations with a persisted operation ID; customers cannot invoke them from an HTTP admin-free endpoint. Uncertain operations retain the same key/body, block new operations and need authenticated confirmation.23 hour replay fences prevent retrying beyond gateway key retention.
- `FAILED` with unknown certainty remains review. Partial capture, split compensation/incomplete aggregates and native fulfillment holds do not ship goods. Changed native totals/currency invalidate old attempts. Native outbox rows queue notifications after commit; wire the existing application's delivery worker to this queue, preserving sending/uncertain review semantics. No external email/shipping provider is invoked by the examples.
- Keep the database, event IDs, operation IDs, server key and old credentials through reconciliation/refund retention. No uninstall/reset/purge endpoint exists.

The checkout UI loads only the official Lunixi bundle, escapes text and supports en/tr. Form method availability stays in the Lunixi panel. CSP uses a per-response nonce and trusted Lunixi origins; review the origins needed by your deployed3DS/form configuration. PAN/CVV never enters these servers.

## Verification

```sh
.venv/bin/pytest -q tests/frameworks
.venv/bin/pytest -q
.venv/bin/ruff check src integrations tests
.venv/bin/mypy src/lunixi
.venv/bin/bandit -r src/lunixi integrations -q
.venv/bin/pip-audit
```

Native framework tests exercise real users/cookies/CSRF, wrong customer/Host, raw webhook tamper/replay, rollback after native stock writes, concurrent database consumers, retained manual holds and changed-order denial. External gateway transport is synthetic. No live charge/Marketplace approval/third-party theme compatibility is claimed. See [Django](DJANGO.md), [FastAPI](FASTAPI.md), [Flask](FLASK.md).

## Provider browser return

Lunixi hosted, split and 3DS flows POST to `/return/<order-key>`. A cross-site POST may omit the SameSite=Lax cookie. This informational route therefore ignores the entire body and sends **303** to the same relative `/return/<order-key>` GET without accessing the session, order, database or gateway. Only that subsequent GET restores normal customer ownership checks and authenticated reconciliation, then redirects to the protected checkout page. Posted status, payment IDs and redirect URLs have no authority.

The return POST has a **64 KiB** declared-body bound; enforce that wire limit at the HTTPS proxy too, including chunked requests. The signed webhook retains its separate 1 MiB bound. Only the informational return and signed webhook are exempt from checkout CSRF; all financial customer requests still require CSRF and ownership. Real loopback WSGI/Uvicorn HTTP tests prove no-session303, ignored forged fields and zero database/gateway calls on this hop.

## Embedded default and optional backend payment page


The framework examples default to `LUNIXI_CHECKOUT_MODE=embedded`: the existing form mounts on the merchant website using only `https://cdn.lunixi.com/lunixi-checkout.min.js` and the official object/token/mount API. Explicit `hosted` remains supported. `IntentResult.payment_page_url` reads the optional backend `paymentPageUrl`; `hosted_url` validates and returns that exact URL, whose opaque page token can differ from the embedded token. Missing/invalid URLs fail closed; no URL is built from the browser token.

The shared form owns enabled methods, multi-card, installments and insurance in either mode; none requires a redirect. Persisted tokens and page URLs are encrypted with distinct authenticated contexts. The original callback/mode/body/hash/key remain bound to an existing attempt: changing configuration does not create a replacement charge. An older hosted record without a backend URL requires reconciliation. Strict raw webhooks, owner/session/CSRF checks, authenticated settlement and informational 3DS/split returns remain required.

Current source 0.2.1 focused checks: 27 SDK/native Django/FastAPI/Flask cases passed; prior full 0.2.0 verification remains the baseline. No live merchant charge or broad new merchant acceptance was run.

The checkout page’s CSP permits form POSTs only to `'self'` and the configured gateway origin (default `https://api-gateway.lunixi.com`). This preserves wallet/provider and legacy POST handoffs supported by the browser SDK. For another reviewed provider, set server-only `LUNIXI_FORM_ACTION_ORIGINS` to a comma-separated list of exact HTTPS origins, without spaces, paths, trailing slashes, credentials, query, fragment or wildcards. Invalid configuration fails closed; gateway responses and browser fields never expand this list. Script nonces, frame/connect restrictions and informational return handling remain in force.

The CSP follow-up adds 21 focused configuration and native rendered-response cases across all three frameworks; no live merchant transaction was run.
