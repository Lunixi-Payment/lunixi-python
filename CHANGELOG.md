# Changelog

## 1.0.0 — 2026-11-01

- Physical POS payment/item/filter/report money uses canonical signed64 strings; raw numeric/null amounts are rejected before HTTP, malformed monetary 2xx payment replies retain UNKNOWN semantics, and signed webhooks are checked after signature verification.

- Reject explicit null capture/refund amounts; full remaining operations use omission or the dedicated API described in MIGRATION-1.0.md.

- Breaking: public money request/response fields require canonical minor-unit strings; JSON numbers are rejected.
- Exact signed 64-bit fiat arithmetic and currency-aware decimal text conversion preserve values above JavaScript’s safe-integer limit.
- See [MIGRATION-1.0.md](MIGRATION-1.0.md) before upgrading.


### Physical POS additions

- Physical POS (`client.physical_pos()`): start, read, list, cancel and reverse in-store device payments (void, refund by amount or by item, pre-authorisation close/cancel); transaction trees and the ambiguous-outcome queue; sales and tax summaries; end-of-day settlement lines. Cursor iterators for every list.
- Physical POS management (`client.physical_pos_management()`): overview, catalog (vendors, device models, acquirers), stores and registers, logical terminals with bank rows and device links, devices with assignment, lifecycle and retirement, audit lists.
- `create_payment` and `create_reversal` require `idempotency_key` (keyword-only; `None` is refused before sending). Create it with `PhysicalPosClient.new_idempotency_key()`, store it with your order, then call; after an unknown outcome call again with the SAME key. `cancel_payment` and the keyed management writes generate a UUID v4 when the key is `None`. A given key is sent exactly as given: empty, blank or padded keys are refused, never trimmed or replaced.
- Payment writes run one attempt loop with the same key and body (the transport's own retries are off for these calls): only a 2xx with a usable `payment` is a success; no answer, a body that cannot be read, a non-JSON or payment-less 2xx and a 5xx without a "not started" code (`PHYSICAL_POS_NOT_STARTED_CODES`) are uncertain. Once an attempt was uncertain the call ends with `PhysicalPosOutcomeUnknownError` (with the key and the last error as cause), whatever the last answer was — a later 429 or 409 included. Payment writes report `status_code` 202 (accepted) or 200 (replay / cancel).
- Card numbers in values are refused before sending (`contains_pan_like_value`, the gateway rule: standalone 13–19 digits, plain or space/dash separated, Luhn valid): `merchant_reference`, item `name` (a 13/14 digit barcode is allowed) and `tax_group_code`, and the `merchant_reference` / `q` filters. Only the field path is reported.
- Filters: `date_from` / `date_to` take a `datetime.date` (sent as that calendar day, `YYYY-MM-DD`, not converted to Europe/Istanbul); `created_from` / `created_to` take an aware `datetime` (sent as ISO-8601 UTC). `None` and `""` are not sent, in bodies and filters; an empty required field is refused.
- `ApiClient.request()` gains an optional per-call `max_retries` (default unchanged) and `ApiClient.max_retries`.
- Typed errors: `PhysicalPosCardDataRejectedError` (also raised before sending when a request or filter key looks like card data — the API takes no card data), `PhysicalPosRateLimitError` (`retry_after` from `Retry-After` or `details.retryAfterSeconds`), `PhysicalPosOutcomeUnknownError` (no definite answer to a payment write — retry with the same key). `ApiError` gains `details` (field path, reason and retry hints only) and `idempotency_key`.
- Webhooks: `PhysicalPosEvents`, `PHYSICAL_POS_EVENT_TYPES`, `parse_webhook_event(raw_body, headers, secret_or_verifier)` verifies the signature with `WebhookVerifier` itself and then reads the `physical_pos.*` event from `data` or `payloadJson`; there is no path for an unverified or pre-decoded envelope. A too deeply nested `payloadJson` is a `WebhookVerificationError`.
- Sales made directly on the device: `PhysicalPosEvents.PAYMENT_DEVICE_SALE` (`physical_pos.payment.device_sale`, in `PHYSICAL_POS_EVENT_TYPES`). The parsed event gains `is_device_sale` and `original` (the reversal's original payment `{"paymentId", "origin"}`, `None` on a root; `origin` `API` or `DEVICE_DIRECT`).
- `PhysicalPosVoidAfterSettlementError` (409 `physical_pos.payment.void_after_settlement`, `allowed_operation`): a payment in a device end-of-day can no longer be voided; refund it instead. `ApiError.details` also keeps `allowedOperation`.
- `get_device()` documents `presence` (connection state, readiness for payment, `notReadyReason`); `list_settlements()` documents `settlementRef`, `acquirerRefRaw`, `acquirerName`, `deviceName` (`commandId` is `None` for an end-of-day started on the device). The acquirer catalog no longer lists `providerCode`.

## 0.2.1 — 2026-10-31

- Default Django, FastAPI and Flask examples to the existing on-site Lunixi form; retain explicit hosted mode.
- Read and strictly validate the backend `paymentPageUrl` independently of the embedded browser token; never derive a hosted URL from the token.
- Persist the optional URL encrypted with a field-specific context, validate it on cache reads, and preserve legacy request hashes/keys without unsafe retries or token-URL fallbacks.
- Preserve nonce CSP while allowing exact operator-approved HTTPS form-action origins for provider/legacy POSTs; reject unsafe origin configuration before use.


## 0.2.0 —2026-10-31

- Typed payment intents/read/list/capture/refund/void/methods and split read/list/refund helpers; existing fraud API preserved.
- JS-compatible numeric-key/scalar JSON, safe integer/header/path validation, HTTPS-only verified transport, bounded responses and redacted errors.
- Strict signed webhook id/type binding, raw-body proof and rotating secrets; legacy nonfinancial fallback requires explicit opt-in.
- Durable encrypted checkout reservations, authenticated fee/split settlement, native atomic inbox/order callbacks, uncertainty handling and23 hour replay fences.
- Runnable Django 6.1.2, FastAPI 0.162.0 and Flask 3.1.3 apps with real auth/session/CSRF/ORM/SQLite stock and outbox, English/Turkish guides and native framework tests.
- Dependency floors updated;0.2.0 is a source release, not a package registry publication claim.


This package follows semantic versioning. On the 0.x line a new API surface is
a minor increase.

## 0.1.0

First release.

### Added

- **Core.** `LunixiClient` facade; validated `Configuration`; `ApiClient` with
  bearer authentication, per-request Ed25519 step-up signing, an
  `Idempotency-Key` header and retries limited to idempotent requests.
- **Signing.** `Ed25519Signer` over `cryptography`, accepting a PKCS#8 PEM,
  base64/hex PKCS#8 DER or a bare 32-byte seed; `build_canonical_request` and
  `digest_for_body`; `generate_key_pair` and `verify_signature` for onboarding
  and offline checks.
- **Tokens.** `TokenManager` with a thread-safe `InMemoryTokenStore`, an
  expiry skew, single-flight exchange and a `TokenStore` seam for a shared
  cache.
- **Envelope.** `is_success`, `data_of`, `items_of`, `page_info_of` and `Page`,
  reading `pageInfo` as a sibling of `data`.
- **Errors.** `LunixiError` hierarchy with `ValidationError`,
  `AuthenticationError`, `RateLimitError` and `ServiceUnavailableError`
  carrying `retry_after` and the quota headers.
- **Transport.** `HttpTransport` protocol with a standard-library
  `UrllibTransport`; compact JSON serialization required by the gateway's
  digest check.
- **Fraud.** `evaluate`, decision-log `list` / `get` / `latest_for_payment` /
  `iterate`, and event `record` / `record_batch` with the 500-event limit and
  partial-result reading. Channel, surface, stage, operation-kind, auth-mode,
  product-context and decision dictionaries.
- **Webhooks.** `WebhookVerifier` for the v2 signature: raw-body HMAC,
  fail-closed verification, timestamp tolerance and rotation-window support.
  The seven fraud event types in `FraudEvents`.
- Type hints throughout with `py.typed`; samples under `samples/`; TR and EN
  READMEs.
