# FastAPI integration

Read [server setup and invariants](FRAMEWORKS.md) first. This is a runnable source application with real native framework tests, not a separately registered plugin. Configure `LUNIXI_PUBLIC_ORIGIN` for the HTTPS origin/port used below and use a trusted certificate. The TLS paths are operator-provided examples; no certificate/private key is committed.

```sh
python -m integrations.cli init
python -m integrations.cli seed --customer-id TRUSTED_CUSTOMER_ID --amount 19.90 --currency TRY
uvicorn --factory integrations.fastapi_app:create_app --host 127.0.0.1 --port 8000 --ssl-keyfile /secure/tls/key.pem --ssl-certfile /secure/tls/cert.pem
```

The server CLI prints a one-use checkout invitation valid for 15 minutes. Disclose it only to the intended customer; the invitation is atomically consumed into a signed Secure/HttpOnly/SameSite session. There is no HTTP endpoint that lets a caller choose a customer ID or basket amount. Redact invitation paths in access logs. Checkout POST requires the session CSRF header and persisted order ownership.

FastAPI sends synchronous SDK/network work to Starlette's worker thread pool; the event loop does not run the blocking gateway request.

The root worker command should be scheduled every minute. Financial operator commands require server access and an existing durable operation ID; a returned pending/uncertain result needs reconciliation/retry with that same ID, not another request with a fresh ID.

```sh
python -m integrations.cli reconcile --limit 100
python -m integrations.cli operation refund --order-id ORDER_ID --operation-id PERSISTED_REFUND_ID --amount 1.00
```

`/webhook` consumes raw bytes, verifies v2 HMAC and signed identity, obtains authenticated GET evidence and atomically updates native order/stock/inbox/outbox. Browser return parameters never finalize payment. Native manual holds and changed snapshots are enforced.23 hour replay fences apply to unconfirmed financial POSTs; GET reads remain available. Native notification outbox rows are retained for the existing application's post-commit delivery worker.

Tests: `pytest -q tests/frameworks`; full SDK/security tests: `pytest -q`. [Turkish](FASTAPI.tr.md), [source SDK](../README.md), [security](../SECURITY.md).

## Provider browser return

Lunixi hosted, split and 3DS flows POST to `/return/<order-key>`. A cross-site POST may omit the SameSite=Lax cookie. This informational route therefore ignores the entire body and sends **303** to the same relative `/return/<order-key>` GET without accessing the session, order, database or gateway. Only that subsequent GET restores normal customer ownership checks and authenticated reconciliation, then redirects to the protected checkout page. Posted status, payment IDs and redirect URLs have no authority.

The return POST has a **64 KiB** declared-body bound; enforce that wire limit at the HTTPS proxy too, including chunked requests. The signed webhook retains its separate 1 MiB bound. Only the informational return and signed webhook are exempt from checkout CSRF; all financial customer requests still require CSRF and ownership. Real loopback WSGI/Uvicorn HTTP tests prove no-session303, ignored forged fields and zero database/gateway calls on this hop.
