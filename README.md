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

Python client for the Lunixi platform. It carries the shared core — Ed25519
request signing, token exchange, response-envelope decoding, cursor paging and
a typed error hierarchy — plus the fraud decision and event API on top of it.

Türkçe: [README.tr.md](README.tr.md)

- **Requires:** Python 3.9 or newer
- **Dependency:** [`cryptography`](https://pypi.org/project/cryptography/) for
  Ed25519. HTTP uses the standard library, so nothing else is pulled in.
- **Typed:** ships `py.typed`; every public function is annotated.
- **License:** MIT

```bash
pip install lunixi-sdk
```

## Quick start

```python
from lunixi import Channel, Decision, LunixiClient

client = LunixiClient(
    base_url="https://api.lunixi.com",
    key_id="kid_...",                     # from the console
    private_key=private_key_pem,          # from your secret store
)

decision = client.fraud().evaluate(
    channel=Channel.STANDALONE_API,
    transaction_ref="order-2026-0001",
    payment={"amount": "149.90", "currency": "TRY"},
    customer={"id": "cus_88", "email": "buyer@example.com"},
)

if decision.blocked:
    refuse_the_order(decision.reasons)
elif decision.requires_three_d:
    retry_with_3d_secure()
elif decision.requires_review:
    hold_for_review(decision.trace_id)
else:
    authorize()
```

Build the client once at start-up and share it: the access-token cache lives on
it, so a fresh client per request means a fresh token exchange per request.

## Authentication

Two levels, and they are not interchangeable.

**Token exchange.** `POST /api/v1/auth/token` is signed with your Ed25519
private key and returns a short-lived access token. The SDK does this for you,
caches the token and refreshes it once when the gateway reports it expired.

**Per-request signature.** The event-ingest routes accept nothing less than a
signature on every call: it is what binds an event to your account, so a body
value cannot claim a different one. The SDK adds it where it is required.

The canonical string that is signed is:

```text
<METHOD>\n<URL>\nX-Date:<value>\nX-Nonce:<value>[\nDigest:<value>]
```

`<URL>` is the path exactly as sent, **including the `/api/v1` prefix and any
query string**. The `Digest` line appears only when a body is present.

### Key handling

You can generate the keypair yourself and upload only the public key, so the
private key never exists outside your systems:

```python
from lunixi import generate_key_pair

private_pem, public_pem = generate_key_pair()
# store private_pem in your secret manager; upload public_pem in the console
```

Accepted private-key shapes: a PKCS#8 PEM block (recommended), base64 or hex
PKCS#8 DER, or a bare 32-byte seed. Load it from a secret store — not from
source, and not from a file inside your repository.

## Fraud

The customer-facing surface is **five routes**:

| Call | Route |
|---|---|
| `fraud().evaluate(...)` | `POST /api/v1/fraud/decisions/evaluate` |
| `fraud().decisions.list(...)` | `GET /api/v1/fraud/decision-logs` |
| `fraud().decisions.get(trace_id)` | `GET /api/v1/fraud/decision-logs/{traceId}` |
| `fraud().events.record(event)` | `POST /api/v1/fraud/events/transactions` |
| `fraud().events.record_batch(events)` | `POST .../events/transactions/batch` |

The console's own routes are not part of this surface. They carry no stability
guarantee, so they are not published here.

### Decision outcomes

`allow`, `review`, `block`, `force_3d`. Note that `allowed` is **not** the
inverse of `blocked`: `review` and `force_3d` are neither, and `force_3d` asks
you to re-run the payment with 3-D Secure rather than refusing it.

Field names use Python's `snake_case`; the `camelCase` spelling from the API
reference is accepted as an alias. An unknown field raises locally and names
the key, rather than costing you a round trip to find out.

`tenant_id` is deliberately absent: the tenant is stamped from your access
token, and a body value is ignored.

### Event ingest

Events are the history that counting rules read.

```python
result = client.fraud().events.record(
    {
        "eventId": "evt-0001",          # your id; a retry with the same id is deduplicated
        "eventType": "card_sale",
        "subjectType": "customer",
        "occurredAt": "2026-10-11T08:29:00Z",
    },
    idempotency_key="evt-0001",
)
if result.deduplicated:
    ...  # this event was already recorded
```

Batches hold up to **500** events and the SDK refuses a larger one before it
reaches the network, because the gateway rejects the whole batch.

**A batch can succeed partially.** It answers `200` and keeps processing after
an event fails validation, so the status code alone never proves the batch
landed:

```python
result = client.fraud().events.record_batch(events, idempotency_key="feed-2026-10-11-01")
for failure in result.failures():
    log.warning("event %s rejected: %s", failure.event_id, failure.error)
```

Correct the body and resend a failure with the **same** `eventId`: the gateway
deduplicates, so a resend cannot double-count an event that did land.

## Reading a response

Every successful response is wrapped:

```json
{ "status": "success", "code": "SUCCESS", "data": {}, "pageInfo": {}, "requestId": "..." }
```

Two things to know if you ever read the envelope yourself:

- **There is no `success` field.** The outcome is in `status`, as the string
  `"success"`. Code written against `response["success"]` reads `None` on every
  response. Use `lunixi.is_success(response)`.
- **`pageInfo` is a sibling of `data`, not nested inside it.** List endpoints
  return `data` as a bare array, so paging metadata cannot live inside it.

The feature clients already handle both.

## Paging

```python
page = client.fraud().decisions.list(decision=Decision.REVIEW, limit=50)
while True:
    for row in page.items:
        handle(row)
    if not page.has_more or not page.next_cursor:
        break
    page = client.fraud().decisions.list(
        decision=Decision.REVIEW, limit=50, cursor=page.next_cursor
    )
```

Or let the SDK follow the cursors:

```python
for row in client.fraud().decisions.iterate(decision=Decision.REVIEW, limit=50):
    handle(row)
```

A cursor is opaque: pass it back unchanged. Do not decode, build or edit one —
a malformed cursor is rejected with `400`, it does not restart from page one.
`total_count` is `None` unless the server actually counted, because a filtered
count is expensive.

## Errors

Every error derives from `LunixiError`.

| Class | Raised when |
|---|---|
| `ConfigurationError` | A local value is unusable; nothing was sent. |
| `SignatureError` | The private key could not be loaded. |
| `ValidationError` | `400` — the gateway rejected the body. |
| `AuthenticationError` | `401` / `403` — signature, token or entitlement refused. |
| `RateLimitError` | `429` — carries `retry_after` and `quota`. |
| `ServiceUnavailableError` | `503` — carries `retry_after`. |
| `ApiError` | Any other non-2xx answer, or no answer at all. |
| `WebhookVerificationError` | An inbound webhook did not verify. |

`retry_after` and the quota fields are `None` when the gateway did not send the
header. It omits one rather than guessing, and so does this SDK — an invented
number would make you retry at the wrong rate.

```python
from lunixi import RateLimitError

try:
    client.fraud().events.record(event, idempotency_key=event["eventId"])
except RateLimitError as error:
    sleep(error.retry_after or 30)
```

### Retries

A `GET`, and any request you give an `idempotency_key`, is retried after a
transport failure or a `5xx`. Anything else is not: the SDK cannot tell a lost
request from a lost response, and replaying an unkeyed write can record the
same event twice.

`evaluate` is never retried automatically. It runs inside your payment flow, so
whether a timed-out decision is retried, treated as a soft allow, or held is
your policy to set.

## Webhooks

```python
from lunixi import FraudEvents, WebhookVerifier, WebhookVerificationError

verifier = WebhookVerifier(endpoint_secret)

try:
    event = verifier.verify(raw_body, request.headers)
except WebhookVerificationError:
    return 400                     # never act on an unverified payload

if event.type == FraudEvents.FLOW_ASYNC_COMPLETED:
    ...
```

**Pass the raw body.** The signature covers the exact bytes that arrived;
parsing JSON and re-serializing it reorders keys and changes spacing, and
verification then fails for every webhook. Capture the raw body before any JSON
middleware touches it.

Verification is fail-closed and checks timestamp freshness within a 300-second
window by default. During a secret rotation the gateway sends two signature
items and either one verifying is enough, so your endpoint keeps working while
you swap secrets.

The seven fraud event types are in `FraudEvents`; `FRAUD_EVENT_TYPES` holds
them all.

## Extending

Any gateway route this version does not wrap is reachable with the signing,
retry and error handling already in place:

```python
envelope = client.api().request(
    "GET", "/api/v1/some/other/route", query={"limit": 25}
)
rows = lunixi.items_of(envelope)
```

Supply your own HTTP stack (for pooling, proxies or tracing) by implementing
`HttpTransport` and passing `transport=`. In a multi-process deployment,
implement `TokenStore` against a shared cache and pass `token_store=` so the
workers share one token.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The suite runs entirely offline: it asserts on what the SDK puts on the wire
through an injected transport, and verifies signing and webhook logic against
committed vectors. Every key in it is synthetic and grants no access.

## Samples

Runnable examples are in [`samples/`](samples/). Each reads its settings from
the environment, so no credential is written into a file.
