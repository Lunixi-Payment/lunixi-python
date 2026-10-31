# Django integration

Read [server setup and invariants](FRAMEWORKS.md) first. This is a runnable source application with real native framework tests, not a separately registered plugin. Configure `LUNIXI_PUBLIC_ORIGIN` for the HTTPS origin/port used below and use a trusted certificate. The TLS paths are operator-provided examples; no certificate/private key is committed.

```sh
python -m integrations.django_app.manage migrate
python -m integrations.django_app.manage createsuperuser
python -m integrations.django_app.manage seed_checkout --username YOUR_USER --amount 19.90 --currency TRY
uvicorn integrations.django_app.asgi:application --host 127.0.0.1 --port 8000 --ssl-keyfile /secure/tls/key.pem --ssl-certfile /secure/tls/cert.pem
```

Open the generated order URL, sign in with the native Django login form and pay. Each order belongs to a real auth user. Native CSRF middleware validates the checkout header; callback/webhook exemptions are limited to their informational/signed routes.

The included real Django migration creates sample native orders/stock plus protected attempts, event inbox and notification outbox. The SQLite transaction mode is IMMEDIATE; native PostgreSQL row-lock support requires a separate deployment acceptance run.

The root worker command should be scheduled every minute. Financial operator commands require server access and an existing durable operation ID; a returned pending/uncertain result needs reconciliation/retry with that same ID, not another request with a fresh ID.

```sh
python -m integrations.django_app.manage lunixi_reconcile
python -m integrations.django_app.manage lunixi_operation refund --order-id ORDER_ID --operation-id PERSISTED_REFUND_ID --amount 1.00
```

`/webhook` consumes raw bytes, verifies v2 HMAC and signed identity, obtains authenticated GET evidence and atomically updates native order/stock/inbox/outbox. Browser return parameters never finalize payment. Native manual holds and changed snapshots are enforced.23 hour replay fences apply to unconfirmed financial POSTs; GET reads remain available. Native notification outbox rows are retained for the existing application's post-commit delivery worker.

Tests: `pytest -q tests/frameworks`; full SDK/security tests: `pytest -q`. [Turkish](DJANGO.tr.md), [source SDK](../README.md), [security](../SECURITY.md).

## Provider browser return

Lunixi hosted, split and 3DS flows POST to `/return/<order-key>`. A cross-site POST may omit the SameSite=Lax cookie. This informational route therefore ignores the entire body and sends **303** to the same relative `/return/<order-key>` GET without accessing the session, order, database or gateway. Only that subsequent GET restores normal customer ownership checks and authenticated reconciliation, then redirects to the protected checkout page. Posted status, payment IDs and redirect URLs have no authority.

The return POST has a **64 KiB** declared-body bound; enforce that wire limit at the HTTPS proxy too, including chunked requests. The signed webhook retains its separate 1 MiB bound. Only the informational return and signed webhook are exempt from checkout CSRF; all financial customer requests still require CSRF and ownership. Real loopback WSGI/Uvicorn HTTP tests prove no-session303, ignored forged fields and zero database/gateway calls on this hop.
